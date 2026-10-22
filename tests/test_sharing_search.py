import pytest
from django.core.cache import cache

from apps.containers.models import Container

pytestmark = pytest.mark.django_db


@pytest.fixture
def shared(auth, audio_file, django_capture_on_commit_callbacks):
    cid = auth.post("/api/v1/containers/", {"title": "Database Systems"}, format="json").data["id"]
    with django_capture_on_commit_callbacks(execute=True):
        auth.post(f"/api/v1/containers/{cid}/entries/", {"text": "B-trees are balanced search trees."}, format="json")
        auth.post(
            f"/api/v1/containers/{cid}/entries/",
            {"audio": audio_file("Today we discussed B plus trees.")},
            format="multipart",
        )
    r = auth.post(f"/api/v1/containers/{cid}/share/")
    assert r.status_code == 200
    return cid, r.data["public_id"]


def test_container_is_private_by_default(auth):
    cid = auth.post("/api/v1/containers/", {"title": "T"}, format="json").data["id"]
    c = Container.objects.get(pk=cid)
    assert c.visibility == "private" and c.public_id is None


def test_public_json_and_html_without_auth(api, shared, django_assert_num_queries):
    _, pid = shared
    cache.clear()
    with django_assert_num_queries(2):  # container+owner JOIN, entries prefetch. Nothing else.
        r = api.get(f"/api/v1/public/{pid}/")
    assert r.status_code == 200
    assert r.data["title"] == "Database Systems" and r.data["author"] == "alice"
    assert len(r.data["entries"]) == 2
    assert "email" not in str(r.data)  # no PII leak

    with django_assert_num_queries(0):  # served from cache
        api.get(f"/api/v1/public/{pid}/")

    page = api.get(f"/share/{pid}/")
    assert page.status_code == 200
    html = page.content.decode()
    assert "Database Systems" in html and "B plus trees" in html and "<audio" in html
    assert page["X-Robots-Tag"] == "noindex"


def test_unpublish_kills_link_and_new_publish_issues_new_link(auth, api, shared):
    cid, pid = shared
    assert api.get(f"/api/v1/public/{pid}/").status_code == 200
    assert auth.delete(f"/api/v1/containers/{cid}/share/").status_code == 204
    assert api.get(f"/api/v1/public/{pid}/").status_code == 404
    assert api.get(f"/share/{pid}/").status_code == 404
    new_pid = auth.post(f"/api/v1/containers/{cid}/share/").data["public_id"]
    assert new_pid != pid


def test_archived_or_unknown_public_ids_404(api, auth, shared):
    cid, pid = shared
    auth.patch(f"/api/v1/containers/{cid}/", {"status": "archived"}, format="json")
    cache.clear()
    assert api.get(f"/api/v1/public/{pid}/").status_code == 404
    assert api.get("/api/v1/public/does-not-exist/").status_code == 404


def test_search_ranks_and_validates(auth, shared):
    r = auth.get("/api/v1/search/?q=trees")
    assert len(r.data["entries"]) == 2
    assert r.data["entries"][0]["container__title"] == "Database Systems"
    assert auth.get("/api/v1/search/?q=zzzzqqq").data["entries"] == []
    assert auth.get("/api/v1/search/?q=a").status_code == 400
    assert auth.get("/api/v1/search/?q=trees&container=not-a-uuid").status_code == 400
    assert auth.get("/api/v1/search/?q=database").data["containers"][0]["title"] == "Database Systems"


def test_health(api):
    assert api.get("/health/live/").status_code == 200
    r = api.get("/health/ready/")
    assert r.status_code == 200 and r.data["database"] == "ok"
