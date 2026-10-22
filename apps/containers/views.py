"""Container & entry endpoints (function-based).

Authorization rule: every query is filtered by `owner=request.user`, so another user's
object simply does not exist for you -> 404, never 403 (no information leak).
"""

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, throttle_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from apps.common.pagination import paginate
from apps.common.throttles import AIRateThrottle, UploadRateThrottle

from . import services
from .models import Container, Entry
from .serializers import (
    CaptureSerializer,
    ContainerDetailSerializer,
    ContainerListSerializer,
    ContainerWriteSerializer,
    EntryCreateSerializer,
    EntrySerializer,
    EntryUpdateSerializer,
    SummaryRequestSerializer,
)

_UPLOAD_THROTTLES = [UserRateThrottle, UploadRateThrottle]


def _own_container(request, pk) -> Container:
    return get_object_or_404(Container, pk=pk, owner=request.user)


def _own_entry(request, pk) -> Entry:
    return get_object_or_404(Entry, pk=pk, owner=request.user)


# --------------------------------------------------------------------------- containers
@extend_schema(methods=["GET"], responses=ContainerListSerializer(many=True))
@extend_schema(methods=["POST"], request=ContainerWriteSerializer, responses={201: ContainerDetailSerializer})
@api_view(["GET", "POST"])
def container_list_create(request):
    if request.method == "POST":
        w = ContainerWriteSerializer(data=request.data)
        w.is_valid(raise_exception=True)
        container = services.create_container(
            request.user, title=w.validated_data.get("title"), icon=w.validated_data.get("icon", "")
        )
        return Response(
            ContainerDetailSerializer(container, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    wanted = request.query_params.get("status", Container.Status.ACTIVE)
    qs = Container.objects.filter(owner=request.user, status=wanted).defer("summary")
    return paginate(request, qs, ContainerListSerializer, ordering="-last_activity_at")


@extend_schema(methods=["GET"], responses=ContainerDetailSerializer)
@extend_schema(methods=["PATCH"], request=ContainerWriteSerializer, responses=ContainerDetailSerializer)
@extend_schema(methods=["DELETE"], responses={204: None})
@api_view(["GET", "PATCH", "DELETE"])
def container_detail(request, pk):
    container = _own_container(request, pk)
    ctx = {"request": request}
    if request.method == "DELETE":
        container.delete()  # cascades to entries; post_delete signal removes audio files
        return Response(status=status.HTTP_204_NO_CONTENT)
    if request.method == "PATCH":
        w = ContainerWriteSerializer(data=request.data, partial=True)
        w.is_valid(raise_exception=True)
        data = w.validated_data
        if data.get("title"):
            services.rename_container(container, data["title"])
        fields = []
        for f in ("icon", "status"):
            if f in data:
                setattr(container, f, data[f])
                fields.append(f)
        if fields:
            container.save(update_fields=fields + ["updated_at"])
    return Response(ContainerDetailSerializer(container, context=ctx).data)


# --------------------------------------------------------------------------- entries
@extend_schema(methods=["GET"], responses=EntrySerializer(many=True))
@extend_schema(
    methods=["POST"],
    request={"multipart/form-data": EntryCreateSerializer},
    responses={202: EntrySerializer},
)
@api_view(["GET", "POST"])
# Multi Parser  Used for multipart/form-data, commonly needed when the frontend uploads an audio file along with text fields.
# FormParser Handles ordinary URL-encoded form submissions, such as fields sent as application/x-www-form-urlencoded
# JsonParser Handles JSON request bodies, which are convenient for text-only entries.
@parser_classes([MultiPartParser, FormParser, JSONParser])
@throttle_classes(_UPLOAD_THROTTLES)
def entry_list_create(request, container_id):
    container = _own_container(request, container_id)
    if request.method == "POST":
        s = EntryCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        entry = services.add_entry(
            request.user, container, text=s.validated_data["text"], audio=s.validated_data.get("audio")
        )
        # 202 Accepted: stored, AI work continues in the background (poll `status`).
        return Response(EntrySerializer(entry, context={"request": request}).data, status=202)

    qs = Entry.objects.filter(container=container)
    if tag := request.query_params.get("tag"):
        qs = qs.filter(tags__contains=[tag])  # served by the GIN index on tags
    return paginate(request, qs, EntrySerializer, ordering="-created_at")


@extend_schema(methods=["GET"], responses=EntrySerializer)
@extend_schema(methods=["PATCH"], request=EntryUpdateSerializer, responses=EntrySerializer)
@extend_schema(methods=["DELETE"], responses={204: None})
@api_view(["GET", "PATCH", "DELETE"])
def entry_detail(request, pk):
    entry = _own_entry(request, pk)
    if request.method == "DELETE":
        services.delete_entry(entry)
        return Response(status=status.HTTP_204_NO_CONTENT)
    if request.method == "PATCH":
        s = EntryUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        entry = services.update_entry_content(entry, **s.validated_data)
    return Response(EntrySerializer(entry, context={"request": request}).data)


@extend_schema(request=None, responses={202: EntrySerializer})
@api_view(["POST"])
@throttle_classes([UserRateThrottle, AIRateThrottle])
def entry_retry(request, pk):
    entry = _own_entry(request, pk)
    if entry.status != Entry.Status.FAILED:
        return Response(
            {"error": {"code": "invalid_state", "message": "Only failed entries can be retried.", "details": None}},
            status=status.HTTP_409_CONFLICT,
        )
    services.retry_entry(entry)
    return Response(EntrySerializer(entry, context={"request": request}).data, status=202)


# --------------------------------------------------------------------------- capture
@extend_schema(request={"multipart/form-data": CaptureSerializer}, responses={202: OpenApiTypes.OBJECT})
@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser, JSONParser])
@throttle_classes(_UPLOAD_THROTTLES)
def capture(request):
    """Quick capture: drop text or voice in. Creates (and AI-names) a container if none given."""
    s = CaptureSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    container = _own_container(request, s.validated_data["container"]) if "container" in s.validated_data else None
    container, entry = services.capture(
        request.user, text=s.validated_data["text"], audio=s.validated_data.get("audio"), container=container
    )
    ctx = {"request": request}
    return Response(
        {
            "container": ContainerListSerializer(container, context=ctx).data,
            "entry": EntrySerializer(entry, context=ctx).data,
        },
        status=202,
    )


# --------------------------------------------------------------------------- AI summary
@extend_schema(request=SummaryRequestSerializer, responses={202: ContainerDetailSerializer})
@api_view(["POST"])
@throttle_classes([UserRateThrottle, AIRateThrottle])
def container_summary(request, pk):
    from apps.ai.tasks import summarize_container

    container = _own_container(request, pk)
    s = SummaryRequestSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    d = s.validated_data
    Container.objects.filter(pk=container.pk).update(summary_status=Container.SummaryStatus.PENDING)
    container.summary_status = Container.SummaryStatus.PENDING
    summarize_container.delay(
        str(container.pk),
        d["period"],
        d["start"].isoformat() if "start" in d else None,
        d["end"].isoformat() if "end" in d else None,
    )
    return Response(ContainerDetailSerializer(container, context={"request": request}).data, status=202)
