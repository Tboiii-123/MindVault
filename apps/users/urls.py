from django.urls import path

from . import views

urlpatterns = [
    path("register/", views.register),
    path("login/", views.login),
    path("refresh/", views.refresh),
    path("logout/", views.logout),
    path("me/", views.me),
    path("password-reset/", views.password_reset_request),
    path("password-reset/confirm/", views.password_reset_confirm),
]
