import os
import uuid

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.common.models import TimeStampedModel, UUIDModel


def audio_upload_path(instance, filename):
    """audio/<owner>/<container>/<uuid>.<ext> - never trust client file names."""
    ext = os.path.splitext(filename)[1].lower() or ".bin"
    return f"audio/{instance.owner_id}/{instance.container_id}/{uuid.uuid4().hex}{ext}"


class Container(UUIDModel, TimeStampedModel):
    """A persistent 'conversation' around a topic that holds many entries."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archived"

    class Visibility(models.TextChoices):
        PRIVATE = "private", "Private"
        PUBLIC = "public", "Public"

    class SummaryStatus(models.TextChoices):
        NONE = "none", "None"
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="containers")
    title = models.CharField(max_length=200, default="New note")
    icon = models.CharField(max_length=16, blank=True)
    # True while the title is a placeholder the AI may replace. Flips to False once the AI
    # names it or the user renames it, so user edits are never overwritten.
    title_is_auto = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    visibility = models.CharField(max_length=10, choices=Visibility.choices, default=Visibility.PRIVATE)
    public_id = models.CharField(max_length=32, unique=True, null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)

    summary = models.TextField(blank=True)
    summary_period = models.CharField(max_length=20, blank=True)
    summary_status = models.CharField(max_length=10, choices=SummaryStatus.choices, default=SummaryStatus.NONE)
    summary_updated_at = models.DateTimeField(null=True, blank=True)

    # Denormalised counters: container lists never COUNT(*) over entries.
    entry_count = models.PositiveIntegerField(default=0)
    last_activity_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [
            # Serves: WHERE owner=? AND status=? ORDER BY last_activity_at DESC (home screen)
            models.Index(fields=["owner", "status", "-last_activity_at"], name="ct_owner_status_activity"),
        ]

    def __str__(self):
        return self.title

    @property
    def is_public(self) -> bool:
        return self.visibility == self.Visibility.PUBLIC and bool(self.public_id)


class Entry(UUIDModel, TimeStampedModel):
    """One piece of captured information: typed text or a voice recording (+ transcript)."""

    class Kind(models.TextChoices):
        TEXT = "text", "Text"
        VOICE = "voice", "Voice"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        TRANSCRIBING = "transcribing", "Transcribing"
        ANALYZING = "analyzing", "Analyzing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    container = models.ForeignKey(Container, on_delete=models.CASCADE, related_name="entries")
    # Denormalised from container so ownership checks & search never need a join.
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="entries")
    kind = models.CharField(max_length=10, choices=Kind.choices)

    text = models.TextField(blank=True)
    audio = models.FileField(upload_to=audio_upload_path, null=True, blank=True)
    audio_mime = models.CharField(max_length=60, blank=True)
    audio_size = models.PositiveIntegerField(null=True, blank=True)
    audio_duration_seconds = models.FloatField(null=True, blank=True)
    transcript = models.TextField(blank=True)
    language = models.CharField(max_length=10, blank=True)

    summary = models.TextField(blank=True)
    key_points = models.JSONField(default=list, blank=True)
    action_items = models.JSONField(default=list, blank=True)
    tags = models.JSONField(default=list, blank=True)

    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING)
    error_message = models.CharField(max_length=500, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    search_vector = SearchVectorField(null=True, editable=False)

    class Meta:
        verbose_name_plural = "entries"
        indexes = [
            # Entry timeline inside a container (keyset pagination on created_at).
            models.Index(fields=["container", "-created_at"], name="en_container_created"),
            # Full-text search, always scoped by owner in the query.
            GinIndex(fields=["search_vector"], name="en_search_gin"),
            GinIndex(fields=["tags"], name="en_tags_gin"),
            # Tiny partial index: the stuck-entry sweeper only ever looks at in-flight rows.
            models.Index(
                fields=["updated_at"],
                name="en_inflight_idx",
                condition=Q(status__in=["pending", "transcribing", "analyzing"]),
            ),
            models.Index(fields=["owner", "-created_at"], name="en_owner_created"),
        ]

    def __str__(self):
        return f"{self.kind}:{self.id}"

    @property
    def content(self) -> str:
        """The text the rest of the system works with (typed text, or the transcript)."""
        return self.text if self.kind == self.Kind.TEXT else self.transcript
