from rest_framework.permissions import SAFE_METHODS
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class AuthRateThrottle(AnonRateThrottle):
    scope = "auth"


class _WriteOnlyUserThrottle(UserRateThrottle):
    """Only counts unsafe methods, so one URL can serve a cheap GET and an expensive POST."""

    def allow_request(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return super().allow_request(request, view)


class UploadRateThrottle(_WriteOnlyUserThrottle):
    scope = "uploads"


class AIRateThrottle(_WriteOnlyUserThrottle):
    scope = "ai"


class PublicRateThrottle(AnonRateThrottle):
    scope = "public"
