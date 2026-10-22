from django.shortcuts import render
from django.views.decorators.http import require_GET
from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.common.throttles import PublicRateThrottle
from apps.containers import services
from apps.containers.views import _own_container

from .selectors import get_public_payload


@extend_schema(methods=["POST"], request=None, responses={200: OpenApiTypes.OBJECT})
@extend_schema(methods=["DELETE"], responses={204: None})
@api_view(["POST", "DELETE"])
def container_share(request, pk):
    """POST = make the container public (idempotent). DELETE = make it private again."""
    container = _own_container(request, pk)
    if request.method == "DELETE":
        services.unpublish_container(container)
        return Response(status=204)
    services.publish_container(container)
    url = request.build_absolute_uri(f"/share/{container.public_id}/")
    return Response({"visibility": container.visibility, "public_id": container.public_id, "public_url": url})


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
@authentication_classes([])
@permission_classes([])
@throttle_classes([PublicRateThrottle])
def public_container(request, public_id):
    """Anonymous JSON endpoint for the public container (used by web/mobile viewers)."""
    payload = get_public_payload(public_id)
    if payload is None:
        raise NotFound("This page does not exist or is no longer public.")
    resp = Response(payload)
    resp["Cache-Control"] = "public, max-age=30"
    return resp


@require_GET
def public_page(request, public_id):
    """Server-rendered HTML page: anyone with the link can read it in a browser, no app needed."""
    payload = get_public_payload(public_id)
    if payload is None:
        return render(request, "sharing/not_found.html", status=404)
    resp = render(request, "sharing/public_container.html", {"c": payload})
    resp["Cache-Control"] = "public, max-age=30"
    resp["X-Robots-Tag"] = "noindex"  # link-only sharing, not search-engine discovery
    resp["Referrer-Policy"] = "no-referrer"
    return resp
