"""Business logic. Views stay thin; everything transactional lives here."""

from __future__ import annotations

import logging
import secrets

from django.conf import settings
from django.contrib.postgres.search import SearchVector
from django.core.cache import cache
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import Container, Entry

logger = logging.getLogger(__name__)

DEFAULT_TITLE = "New note"


# --------------------------------------------------------------------------- containers
def create_container(owner, *, title: str | None = None, icon: str = "") -> Container:
    title = (title or "").strip()
    return Container.objects.create(
        owner=owner,
        title=title or DEFAULT_TITLE,
        icon=icon,
        title_is_auto=not title,  # no user-supplied title -> let the AI name it
    )


def rename_container(container: Container, title: str) -> Container:
    container.title = title.strip()
    container.title_is_auto = False  # user decision wins forever
    container.save(update_fields=["title", "title_is_auto", "updated_at"])
    return container


# --------------------------------------------------------------------------- entries
def refresh_search_index(entry_id) -> None:
    """Recompute the tsvector in ONE UPDATE statement, entirely inside Postgres."""
    cfg = settings.SEARCH_CONFIG
    Entry.objects.filter(pk=entry_id).update(
        search_vector=(
            SearchVector("text", weight="A", config=cfg)
            + SearchVector("transcript", weight="A", config=cfg)
            + SearchVector("summary", weight="B", config=cfg)
        )
    )


@transaction.atomic
def add_entry(owner, container: Container, *, text: str = "", audio=None) -> Entry:
    """Create a text or voice entry, bump container counters, enqueue AI work after commit."""
    from apps.ai.tasks import process_entry  # local import: avoids import cycle at startup

    kind = Entry.Kind.VOICE if audio is not None else Entry.Kind.TEXT
    entry = Entry(container=container, owner=owner, kind=kind, text=text if kind == Entry.Kind.TEXT else "")
    if audio is not None:
        entry.audio_mime = (getattr(audio, "content_type", "") or "")[:60]
        entry.audio_size = getattr(audio, "size", None)
        entry.audio = audio
    entry.save()

    # Single atomic UPDATE using F(): no read-modify-write race under concurrent inserts.
    Container.objects.filter(pk=container.pk).update(entry_count=F("entry_count") + 1, last_activity_at=timezone.now())
    if kind == Entry.Kind.TEXT:
        refresh_search_index(entry.pk)  # text is searchable immediately, before the AI runs

    transaction.on_commit(lambda: process_entry.delay(str(entry.pk)))
    return entry


@transaction.atomic
def delete_entry(entry: Entry) -> None:
    Container.objects.filter(pk=entry.container_id, entry_count__gt=0).update(entry_count=F("entry_count") - 1)
    entry.delete()
    invalidate_public_cache(entry.container_id)


@transaction.atomic
def update_entry_content(entry: Entry, *, text=None, transcript=None, tags=None) -> Entry:
    from apps.ai.tasks import process_entry

    changed = False
    if text is not None and entry.kind == Entry.Kind.TEXT and text != entry.text:
        entry.text, changed = text, True
    if transcript is not None and entry.kind == Entry.Kind.VOICE and transcript != entry.transcript:
        entry.transcript, changed = transcript, True
    fields = ["updated_at"]
    if tags is not None:
        entry.tags = tags
        fields.append("tags")
    if changed:
        entry.status = Entry.Status.PENDING  # re-run AI on the edited content
        fields += ["text", "transcript", "status"]
    entry.save(update_fields=fields)
    if changed:
        refresh_search_index(entry.pk)
        transaction.on_commit(lambda: process_entry.delay(str(entry.pk)))
    invalidate_public_cache(entry.container_id)
    return entry


def retry_entry(entry: Entry) -> Entry:
    from apps.ai.tasks import process_entry

    entry.status, entry.error_message = Entry.Status.PENDING, ""
    entry.save(update_fields=["status", "error_message", "updated_at"])
    transaction.on_commit(lambda: process_entry.delay(str(entry.pk)))
    return entry


# --------------------------------------------------------------------------- capture
@transaction.atomic
def capture(owner, *, text: str = "", audio=None, container: Container | None = None):
    """'Capture first, organise later': drop a thought in, creating+naming a container if needed."""
    if container is None:
        container = create_container(owner)
    entry = add_entry(owner, container, text=text, audio=audio)
    container.refresh_from_db(fields=["entry_count", "last_activity_at"])  # counters were bumped via F()
    return container, entry


# --------------------------------------------------------------------------- sharing
def public_cache_key(public_id: str) -> str:
    return f"public:{public_id}"


def invalidate_public_cache(container_id) -> None:
    public_id = Container.objects.filter(pk=container_id).values_list("public_id", flat=True).first()
    if public_id:
        cache.delete(public_cache_key(public_id))


def publish_container(container: Container) -> Container:
    if not container.public_id:
        container.public_id = secrets.token_urlsafe(16)  # 128 bits: unguessable
    container.visibility = Container.Visibility.PUBLIC
    container.published_at = timezone.now()
    container.save(update_fields=["public_id", "visibility", "published_at", "updated_at"])
    return container


def unpublish_container(container: Container) -> Container:
    if container.public_id:
        cache.delete(public_cache_key(container.public_id))
    container.visibility = Container.Visibility.PRIVATE
    container.public_id = None  # old links die; re-publishing issues a NEW link
    container.published_at = None
    container.save(update_fields=["public_id", "visibility", "published_at", "updated_at"])
    return container
