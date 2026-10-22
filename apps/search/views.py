import uuid

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from . import services


@extend_schema(
    parameters=[
        OpenApiParameter("q", str, required=True),
        OpenApiParameter("container", OpenApiTypes.UUID, required=False),
        OpenApiParameter("limit", int, required=False),
    ],
    responses=OpenApiTypes.OBJECT,
)
@api_view(["GET"])
def search(request):
    q = request.query_params.get("q", "").strip()
    if len(q) < 2:
        raise ValidationError({"q": "Enter at least 2 characters."})
    try:
        limit = max(1, min(int(request.query_params.get("limit", 20)), 50))
    except ValueError:
        raise ValidationError({"limit": "Must be an integer."}) from None

    container_id = request.query_params.get("container")
    if container_id:
        try:
            container_id = uuid.UUID(container_id)
        except ValueError:
            raise ValidationError({"container": "Invalid id."}) from None
    entries = services.search_entries(request.user, q[:200], container_id=container_id, limit=limit)
    containers = [] if container_id else services.search_containers(request.user, q[:200])
    return Response({"query": q, "containers": containers, "entries": entries})
