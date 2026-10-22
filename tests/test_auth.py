import pytest
from django.core import mail

pytestmark = pytest.mark.django_db
PW = "S3cure-pass!word"


def test_register_login_refresh_logout(api):
    r = api.post("/api/v1/auth/register/", {"email": "New@Example.com", "password": PW}, format="json")
    assert r.status_code == 201
    assert r.data["user"]["email"] == "new@example.com"

    r = api.post("/api/v1/auth/login/", {"email": "new@example.com", "password": PW}, format="json")
    assert r.status_code == 200
    access, refresh = r.data["access"], r.data["refresh"]

    api.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    assert api.get("/api/v1/auth/me/").data["email"] == "new@example.com"

    r = api.post("/api/v1/auth/refresh/", {"refresh": refresh}, format="json")
    assert r.status_code == 200 and "access" in r.data

    new_refresh = r.data["refresh"]
    assert api.post("/api/v1/auth/logout/", {"refresh": new_refresh}, format="json").status_code == 204
    # blacklisted token can no longer be used
    assert api.post("/api/v1/auth/refresh/", {"refresh": new_refresh}, format="json").status_code == 401


def test_bad_login_and_weak_password(api, user):
    r = api.post("/api/v1/auth/login/", {"email": user.email, "password": "nope"}, format="json")
    assert r.status_code == 401
    assert r.data["error"]["code"] == "authentication_failed"
    r = api.post("/api/v1/auth/register/", {"email": "x@example.com", "password": "12345678"}, format="json")
    assert r.status_code == 400


def test_protected_endpoint_requires_auth(api):
    assert api.get("/api/v1/containers/").status_code == 401


def test_password_reset_flow(api, user):
    r = api.post("/api/v1/auth/password-reset/", {"email": user.email}, format="json")
    assert r.status_code == 202 and len(mail.outbox) == 1
    # unknown email gives the same response (no enumeration) and sends nothing
    r = api.post("/api/v1/auth/password-reset/", {"email": "ghost@example.com"}, format="json")
    assert r.status_code == 202 and len(mail.outbox) == 1

    body = mail.outbox[0].body
    uid = body.split("uid=")[1].split("&")[0]
    token = body.split("token=")[1].split()[0]
    r = api.post(
        "/api/v1/auth/password-reset/confirm/",
        {"uid": uid, "token": token, "new_password": "Brand-new-pass-99"},
        format="json",
    )
    assert r.status_code == 200
    assert (
        api.post(
            "/api/v1/auth/login/", {"email": user.email, "password": "Brand-new-pass-99"}, format="json"
        ).status_code
        == 200
    )
