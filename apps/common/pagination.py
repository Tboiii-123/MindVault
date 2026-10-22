from rest_framework.pagination import CursorPagination


def paginate(request, queryset, serializer_class, *, ordering="-created_at", context=None):
    """Cursor (keyset) pagination for function-based views.

    Keyset pagination is O(log n) per page regardless of depth, unlike OFFSET which
    degrades linearly - important for containers holding thousands of entries.
    """

    class _Paginator(CursorPagination):
        page_size = 20
        page_size_query_param = "page_size"
        max_page_size = 100

    paginator = _Paginator()
    paginator.ordering = ordering
    page = paginator.paginate_queryset(queryset, request)
    data = serializer_class(page, many=True, context=context or {"request": request}).data
    return paginator.get_paginated_response(data)
