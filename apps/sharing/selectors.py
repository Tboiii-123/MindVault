"""Read-side queries for public content (kept separate from write-side services)."""

from django.conf import settings
from django.core.cache import cache
from django.db.models import Prefetch, Q

from apps.containers.models import Container, Entry
from apps.containers.services import public_cache_key


def get_public_payload(public_id: str) -> dict | None:
    """Return a JSON-safe dict for a public container, or None.

    Cost: 2 queries on a cache miss (container+owner JOIN, entries PREFETCH), 0 on a hit.
    Only whitelisted fields are exposed - never emails, ids of other objects, or private entries.
    """
    key = public_cache_key(public_id)
    payload = cache.get(key)
    if payload is not None:
        return payload

    visible_entries = (
        Entry.objects.filter(
            Q(kind=Entry.Kind.TEXT) | ~Q(transcript="")  # hide voice notes still waiting for STT
        )
        .only("id", "container_id", "kind", "text", "transcript", "summary", "tags", "audio", "created_at")
        .order_by("created_at")
    )

    container = (
        Container.objects.filter(
            public_id=public_id,
            visibility=Container.Visibility.PUBLIC,
            status=Container.Status.ACTIVE,
        )
        .select_related("owner")
        .only("id", "title", "icon", "summary", "published_at", "public_id", "owner__full_name", "owner__email")
        .prefetch_related(Prefetch("entries", queryset=visible_entries, to_attr="visible_entries"))
        .first()
    )
    if container is None:
        return None

    payload = {
        "title": container.title,
        "icon": container.icon,
        "author": container.owner.display_name,
        "summary": container.summary,
        "published_at": container.published_at.isoformat() if container.published_at else None,
        "entries": [
            {
                "id": str(e.pk),
                "kind": e.kind,
                "content": e.content,
                "summary": e.summary,
                "tags": e.tags,
                "audio_url": e.audio.url if e.audio else None,
                "created_at": e.created_at.isoformat(),
            }
            for e in container.visible_entries
        ],
    }
    cache.set(key, payload, settings.PUBLIC_SHARE_CACHE_SECONDS)
    return payload
