import os

from django.conf import settings
from django.urls import reverse
from drf_spectacular.utils import OpenApiTypes, extend_schema_field
from rest_framework import serializers

from .models import Container, Entry


# --------------------------------------------------------------------------- containers
class ContainerListSerializer(serializers.ModelSerializer):
    public_url = serializers.SerializerMethodField()

    class Meta:
        model = Container
        fields = (
            "id", "title", "icon", "status", "visibility", "public_url",
            "entry_count", "last_activity_at", "created_at", "summary_status",
        )  # fmt: skip

    @extend_schema_field(OpenApiTypes.URI)
    def get_public_url(self, obj):
        if not obj.is_public:
            return None
        return self.context["request"].build_absolute_uri(reverse("public-page", args=[obj.public_id]))


class ContainerDetailSerializer(ContainerListSerializer):
    class Meta(ContainerListSerializer.Meta):
        fields = ContainerListSerializer.Meta.fields + (
            "summary", "summary_period", "summary_updated_at", "published_at",
        )  # fmt: skip


class ContainerWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False, allow_blank=True)
    icon = serializers.CharField(max_length=16, required=False, allow_blank=True)
    status = serializers.ChoiceField(choices=Container.Status.choices, required=False)


# --------------------------------------------------------------------------- entries
class EntrySerializer(serializers.ModelSerializer):
    audio_url = serializers.SerializerMethodField()
    container_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Entry
        fields = (
            "id", "container_id", "kind", "text", "transcript", "summary", "key_points",
            "action_items", "tags", "status", "error_message", "audio_url",
            "audio_duration_seconds", "language", "created_at", "updated_at",
        )  # fmt: skip

    @extend_schema_field(OpenApiTypes.URI)
    def get_audio_url(self, obj):
        # storage.url() is computed locally (pre-signed for S3): no network call, no N+1.
        return obj.audio.url if obj.audio else None


class EntryUpdateSerializer(serializers.Serializer):
    text = serializers.CharField(required=False, allow_blank=False, max_length=50_000)
    transcript = serializers.CharField(required=False, allow_blank=False, max_length=100_000)
    tags = serializers.ListField(child=serializers.CharField(max_length=40), required=False, max_length=20)


def validate_audio_file(f):
    if f.size > settings.AUDIO_MAX_BYTES:
        raise serializers.ValidationError(f"Audio too large (max {settings.AUDIO_MAX_BYTES // (1024 * 1024)} MB).")
    ext = os.path.splitext(f.name)[1].lower()
    ctype = (getattr(f, "content_type", "") or "").split(";")[0].strip().lower()
    if ext not in settings.AUDIO_ALLOWED_EXTENSIONS or ctype not in settings.AUDIO_ALLOWED_TYPES:
        raise serializers.ValidationError("Unsupported audio format.")
    return f


class EntryCreateSerializer(serializers.Serializer):
    """Exactly one of `text` or `audio`."""

    text = serializers.CharField(required=False, allow_blank=True, max_length=50_000)
    audio = serializers.FileField(required=False, validators=[validate_audio_file])

    def validate(self, attrs):
        text = (attrs.get("text") or "").strip()
        audio = attrs.get("audio")
        if bool(text) == bool(audio):
            raise serializers.ValidationError("Provide exactly one of 'text' or 'audio'.")
        attrs["text"] = text
        return attrs


class CaptureSerializer(EntryCreateSerializer):
    container = serializers.UUIDField(required=False)


class SummaryRequestSerializer(serializers.Serializer):
    PERIODS = ("today", "yesterday", "week", "month", "all", "custom")
    period = serializers.ChoiceField(choices=PERIODS, default="all")
    start = serializers.DateTimeField(required=False)
    end = serializers.DateTimeField(required=False)

    def validate(self, attrs):
        if attrs["period"] == "custom":
            if "start" not in attrs or "end" not in attrs:
                raise serializers.ValidationError("'start' and 'end' are required for a custom period.")
            if attrs["start"] >= attrs["end"]:
                raise serializers.ValidationError("'start' must be before 'end'.")
        return attrs
