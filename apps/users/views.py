"""Auth endpoints as function-based views (no class-based views anywhere in the project)."""

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from apps.common.throttles import AuthRateThrottle

from .serializers import (
    LoginSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RefreshSerializer,
    RegisterSerializer,
    UserSerializer,
)

User = get_user_model()


def _tokens_for(user):
    refresh = RefreshToken.for_user(user)
    return {"refresh": str(refresh), "access": str(refresh.access_token)}


@extend_schema(request=RegisterSerializer, responses={201: OpenApiTypes.OBJECT})
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AuthRateThrottle])
def register(request):
    serializer = RegisterSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = serializer.save()
    return Response({"user": UserSerializer(user).data, **_tokens_for(user)}, status=status.HTTP_201_CREATED)


@extend_schema(request=LoginSerializer, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AuthRateThrottle])
def login(request):
    serializer = LoginSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = authenticate(
        request,
        email=serializer.validated_data["email"].lower(),
        password=serializer.validated_data["password"],
    )
    if user is None or not user.is_active:
        raise AuthenticationFailed("Invalid email or password.")
    return Response({"user": UserSerializer(user).data, **_tokens_for(user)})


@extend_schema(request=RefreshSerializer, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AuthRateThrottle])
def refresh(request):
    serializer = TokenRefreshSerializer(data=request.data)
    try:
        serializer.is_valid(raise_exception=True)
    except TokenError as exc:
        raise InvalidToken(exc.args[0]) from exc
    return Response(serializer.validated_data)


@extend_schema(request=RefreshSerializer, responses={204: None})
@api_view(["POST"])
def logout(request):
    serializer = RefreshSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        RefreshToken(serializer.validated_data["refresh"]).blacklist()
    except TokenError:
        pass  # already invalid/blacklisted: logout is idempotent
    return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(methods=["GET"], responses=UserSerializer)
@extend_schema(methods=["PATCH"], request=UserSerializer, responses=UserSerializer)
@api_view(["GET", "PATCH"])
def me(request):
    if request.method == "PATCH":
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
    return Response(UserSerializer(request.user).data)


@extend_schema(request=PasswordResetRequestSerializer, responses={202: None})
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AuthRateThrottle])
def password_reset_request(request):
    serializer = PasswordResetRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = User.objects.filter(email__iexact=serializer.validated_data["email"], is_active=True).first()
    if user:
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        link = f"{settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}"
        send_mail(
            "Reset your password",
            f"Use this link to reset your password:\n\n{link}\n",
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
        )
    # Same response whether or not the account exists: no user enumeration.
    return Response({"detail": "If the account exists, a reset email was sent."}, status=202)


@extend_schema(request=PasswordResetConfirmSerializer, responses={200: None})
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AuthRateThrottle])
def password_reset_confirm(request):
    serializer = PasswordResetConfirmSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(data["uid"])))
    except (User.DoesNotExist, ValueError, TypeError, OverflowError, DjangoValidationError):
        user = None
    if user is None or not default_token_generator.check_token(user, data["token"]):
        raise serializers.ValidationError({"token": "Invalid or expired reset link."})
    try:
        validate_password(data["new_password"], user=user)
    except DjangoValidationError as exc:
        raise serializers.ValidationError({"new_password": list(exc.messages)}) from exc
    user.set_password(data["new_password"])
    user.save(update_fields=["password"])
    return Response({"detail": "Password updated."})
