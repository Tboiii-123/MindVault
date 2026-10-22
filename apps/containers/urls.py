from django.urls import path

from . import views

urlpatterns = [
    path("capture/", views.capture),
    path("containers/", views.container_list_create),
    path("containers/<uuid:pk>/", views.container_detail),
    path("containers/<uuid:pk>/summary/", views.container_summary),
    path("containers/<uuid:container_id>/entries/", views.entry_list_create),
    path("entries/<uuid:pk>/", views.entry_detail),
    path("entries/<uuid:pk>/retry/", views.entry_retry),
]
