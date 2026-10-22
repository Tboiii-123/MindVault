from django.urls import path

from . import views

urlpatterns = [
    path("containers/<uuid:pk>/share/", views.container_share),
    path("public/<str:public_id>/", views.public_container),
]
