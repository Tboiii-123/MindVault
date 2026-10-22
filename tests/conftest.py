import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.users.models import User


@pytest.fixture
def api():
    return APIClient()


def _make_user(email):
    return User.objects.create_user(email=email, password="S3cure-pass!word", full_name=email.split("@")[0])


@pytest.fixture
def user(db):
    return _make_user("alice@example.com")


@pytest.fixture
def other_user(db):
    return _make_user("bob@example.com")


@pytest.fixture
def auth(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


@pytest.fixture
def other_auth(other_user):
    c = APIClient()
    c.force_authenticate(other_user)
    return c


@pytest.fixture
def audio_file():
    def make(spoken="Today we discussed B plus trees and database indexing."):
        return SimpleUploadedFile("lecture.webm", b"TRANSCRIPT:" + spoken.encode(), content_type="audio/webm")

    return make
