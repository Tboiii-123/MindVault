from django.core.cache import cache
from django.db import connection
from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.response import Response


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
@authentication_classes([])
@permission_classes([])
@throttle_classes([])
def health_live(request):
    """Liveness: process is up. Used by container orchestrators."""
    return Response({"status": "ok"})


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
@authentication_classes([])
@permission_classes([])
@throttle_classes([])
def health_ready(request):
    """Readiness: dependencies reachable."""
    checks = {}
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {exc.__class__.__name__}"
    try:
        cache.set("health", "1", 5)
        checks["cache"] = "ok" if cache.get("health") == "1" else "error"
    except Exception as exc:  # noqa: BLE001
        checks["cache"] = f"error: {exc.__class__.__name__}"
    healthy = all(v == "ok" for v in checks.values())
    return Response(checks, status=200 if healthy else 503)
