from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.common.views import health_live, health_ready
from apps.sharing.views import public_page

api_v1 = [
    path("auth/", include("apps.users.urls")),
    path("", include("apps.containers.urls")),
    path("", include("apps.sharing.urls")),
    path("search/", include("apps.search.urls")),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/live/", health_live),
    path("health/ready/", health_ready),
    path("api/v1/", include(api_v1)),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema")),
    # Human-friendly public web page, viewable without the app or an account.
    path("share/<str:public_id>/", public_page, name="public-page"),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
