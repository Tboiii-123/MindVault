"""Background pipeline:  audio -> STT -> transcript -> LLM analysis -> title -> index -> done.

Design notes
* State lives in Postgres (`Entry.status`), not in Celery results -> survives broker restarts.
* Tasks are idempotent: re-running a COMPLETED entry is a no-op; a half-done entry resumes
  (an existing transcript is never re-transcribed, saving STT cost).
* Transient provider errors retry with exponential backoff + jitter; permanent ones fail fast.
* A beat-driven sweeper re-queues entries stuck in-flight (lost messages, killed workers).
"""

from __future__ import annotations

import logging
from datetime import timedelta

from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.containers.models import Container, Entry
from apps.containers.services import invalidate_public_cache, refresh_search_index

from .providers.base import PermanentAIError, TransientAIError
from .registry import get_llm, get_stt

logger = logging.getLogger(__name__)


def _set_status(entry_id, status, **extra):
    Entry.objects.filter(pk=entry_id).update(status=status, updated_at=timezone.now(), **extra)


class _EntryTask(Task):
    """Marks the entry FAILED once retries are exhausted (or on a permanent error)."""

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        entry_id = args[0] if args else kwargs.get("entry_id")
        if entry_id:
            _set_status(entry_id, Entry.Status.FAILED, error_message=f"{exc.__class__.__name__}: {exc}"[:500])
        logger.error("process_entry failed entry=%s err=%r", entry_id, exc)


@shared_task(
    bind=True,
    base=_EntryTask,
    name="ai.transcribe_and_process_entry",
    autoretry_for=(TransientAIError,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
    dont_autoretry_for=(PermanentAIError, SoftTimeLimitExceeded),
)
def process_entry(self, entry_id: str) -> str:
    entry = Entry.objects.select_related("container").filter(pk=entry_id).first()
    if entry is None:
        return "gone"  # deleted before the worker picked it up
    if entry.status == Entry.Status.COMPLETED:
        return "already_completed"

    # 1) Speech-to-text (voice only, and only if we do not already have a transcript)
    if entry.kind == Entry.Kind.VOICE and not entry.transcript:
        _set_status(entry.pk, Entry.Status.TRANSCRIBING)
        with entry.audio.open("rb") as fh:
            result = get_stt().transcribe(fh, filename=entry.audio.name.rsplit("/", 1)[-1], mime=entry.audio_mime)
        if not result.text.strip():
            raise PermanentAIError("No speech detected in the recording.")
        entry.transcript = result.text
        entry.language = result.language[:10]
        entry.audio_duration_seconds = result.duration_seconds
        entry.save(update_fields=["transcript", "language", "audio_duration_seconds", "updated_at"])
        refresh_search_index(entry.pk)  # transcript becomes searchable immediately

    content = entry.content.strip()

    # 2) LLM analysis (skipped for tiny notes: saves tokens, nothing worth summarising)
    _set_status(entry.pk, Entry.Status.ANALYZING)
    llm = get_llm()
    if len(content) >= settings.AI_MIN_CHARS_FOR_ANALYSIS:
        a = llm.analyze_entry(content)
        entry.summary, entry.key_points = a.summary, a.key_points
        entry.action_items, entry.tags = a.action_items, a.tags

    # 3) Name the container once, only if the user has not named it themselves
    if entry.container.title_is_auto and content:
        t = llm.suggest_title(content)
        Container.objects.filter(pk=entry.container_id, title_is_auto=True).update(
            title=t.title, icon=t.icon, title_is_auto=False, updated_at=timezone.now()
        )

    entry.status = Entry.Status.COMPLETED
    entry.error_message = ""
    entry.processed_at = timezone.now()
    entry.save(
        update_fields=[
            "summary",
            "key_points",
            "action_items",
            "tags",
            "status",
            "error_message",
            "processed_at",
            "updated_at",
        ]
    )
    refresh_search_index(entry.pk)
    invalidate_public_cache(entry.container_id)
    return "completed"


# --------------------------------------------------------------------------- container summary
def _period_bounds(period: str, start: str | None, end: str | None):
    now = timezone.now()
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "today":
        return day0, None
    if period == "yesterday":
        return day0 - timedelta(days=1), day0
    if period == "week":
        return now - timedelta(days=7), None
    if period == "month":
        return now - timedelta(days=30), None
    if period == "custom":
        from django.utils.dateparse import parse_datetime

        return parse_datetime(start), parse_datetime(end)
    return None, None


@shared_task(name="ai.summarize_container", autoretry_for=(TransientAIError,), retry_backoff=True, max_retries=3)
def summarize_container(container_id: str, period: str = "all", start=None, end=None) -> str:
    container = Container.objects.filter(pk=container_id).first()
    if container is None:
        return "gone"
    lo, hi = _period_bounds(period, start, end)
    qs = Entry.objects.filter(container=container).order_by("created_at")
    if lo:
        qs = qs.filter(created_at__gte=lo)
    if hi:
        qs = qs.filter(created_at__lt=hi)

    # Fetch only what we need, stream rows, stop at the prompt budget. For long entries
    # use the already-computed per-entry summary (map-reduce style) instead of raw text.
    notes, used = [], 0
    for text, transcript, summary, kind in qs.values_list("text", "transcript", "summary", "kind").iterator(
        chunk_size=200
    ):
        raw = text if kind == Entry.Kind.TEXT else transcript
        piece = (summary if summary and len(raw) > 600 else raw).strip()
        if not piece:
            continue
        if used + len(piece) > settings.AI_CONTAINER_SUMMARY_CHAR_BUDGET:
            break
        notes.append(piece)
        used += len(piece)

    if not notes:
        Container.objects.filter(pk=container.pk).update(
            summary="No notes in this period.",
            summary_period=period,
            summary_status=Container.SummaryStatus.COMPLETED,
            summary_updated_at=timezone.now(),
        )
        return "empty"

    try:
        text = get_llm().summarize_container(container.title, notes)
    except TransientAIError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("summary failed container=%s", container_id)
        Container.objects.filter(pk=container.pk).update(summary_status=Container.SummaryStatus.FAILED)
        raise PermanentAIError(str(exc)) from exc

    with transaction.atomic():
        Container.objects.filter(pk=container.pk).update(
            summary=text,
            summary_period=period,
            summary_status=Container.SummaryStatus.COMPLETED,
            summary_updated_at=timezone.now(),
        )
    invalidate_public_cache(container.pk)
    return "completed"


@shared_task(name="ai.requeue_stuck_entries")
def requeue_stuck_entries() -> int:
    """Beat job: re-enqueue entries stuck in-flight longer than AI_STUCK_ENTRY_MINUTES.

    Uses the partial index `en_inflight_idx`, so it is cheap even with millions of entries.
    """
    cutoff = timezone.now() - timedelta(minutes=settings.AI_STUCK_ENTRY_MINUTES)
    ids = list(
        Entry.objects.filter(
            status__in=[Entry.Status.PENDING, Entry.Status.TRANSCRIBING, Entry.Status.ANALYZING],
            updated_at__lt=cutoff,
        ).values_list("pk", flat=True)[:500]
    )
    for pk in ids:
        process_entry.delay(str(pk))
    if ids:
        Entry.objects.filter(pk__in=ids).update(updated_at=timezone.now())
        logger.warning("requeued %d stuck entries", len(ids))
    return len(ids)
