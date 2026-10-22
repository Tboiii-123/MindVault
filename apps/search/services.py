from django.conf import settings
from django.contrib.postgres.search import SearchHeadline, SearchQuery, SearchRank
from django.db.models import F, Value
from django.db.models.functions import Coalesce, NullIf

from apps.containers.models import Container, Entry


def search_entries(owner, q: str, *, container_id=None, limit: int = 20):
    """Full-text search over a user's entries (text + transcripts + summaries).

    Query plan: GIN index on `search_vector` finds matches, `owner_id` filter prunes to the
    user's rows. We select a handful of columns via .values() (no model hydration, no big
    TEXT columns) and compute the highlighted snippet only for the LIMITed rows.
    """
    cfg = settings.SEARCH_CONFIG
    query = SearchQuery(q, search_type="websearch", config=cfg)  # supports "quoted", -exclude, or
    qs = Entry.objects.filter(owner=owner, search_vector=query)
    if container_id:
        qs = qs.filter(container_id=container_id)
    return list(
        qs.annotate(
            rank=SearchRank(F("search_vector"), query),
            snippet=SearchHeadline(
                Coalesce(NullIf("transcript", Value("")), "text"),
                query,
                config=cfg,
                start_sel="<mark>",
                stop_sel="</mark>",
                max_words=30,
                min_words=10,
            ),
        )
        .order_by("-rank", "-created_at")
        .values("id", "container_id", "container__title", "kind", "created_at", "rank", "snippet")[:limit]
    )


def search_containers(owner, q: str, *, limit: int = 10):
    return list(
        Container.objects.filter(owner=owner, title__icontains=q)
        .order_by("-last_activity_at")
        .values("id", "title", "icon", "entry_count")[:limit]
    )
