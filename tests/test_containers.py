import pytest

from apps.containers.models import Container, Entry

pytestmark = pytest.mark.django_db


def test_container_crud_and_rename_disables_auto_title(auth):
    r = auth.post("/api/v1/containers/", {}, format="json")
    assert r.status_code == 201
    cid = r.data["id"]
    assert Container.objects.get(pk=cid).title_is_auto is True

    r = auth.patch(f"/api/v1/containers/{cid}/", {"title": "Database Systems"}, format="json")
    assert r.data["title"] == "Database Systems"
    assert Container.objects.get(pk=cid).title_is_auto is False

    r = auth.patch(f"/api/v1/containers/{cid}/", {"status": "archived"}, format="json")
    assert r.data["status"] == "archived"
    assert auth.get("/api/v1/containers/").data["results"] == []
    assert len(auth.get("/api/v1/containers/?status=archived").data["results"]) == 1

    assert auth.delete(f"/api/v1/containers/{cid}/").status_code == 204
    assert auth.get(f"/api/v1/containers/{cid}/").status_code == 404


def test_users_cannot_see_each_others_data(auth, other_auth, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        c = auth.post("/api/v1/capture/", {"text": "private thought about redis caching"}, format="json").data
    cid, eid = c["container"]["id"], c["entry"]["id"]

    # every access path returns 404 (not 403) for the non-owner
    assert other_auth.get(f"/api/v1/containers/{cid}/").status_code == 404
    assert other_auth.patch(f"/api/v1/containers/{cid}/", {"title": "x"}, format="json").status_code == 404
    assert other_auth.delete(f"/api/v1/containers/{cid}/").status_code == 404
    assert other_auth.get(f"/api/v1/containers/{cid}/entries/").status_code == 404
    assert other_auth.post(f"/api/v1/containers/{cid}/entries/", {"text": "hi"}, format="json").status_code == 404
    assert other_auth.get(f"/api/v1/entries/{eid}/").status_code == 404
    assert other_auth.delete(f"/api/v1/entries/{eid}/").status_code == 404
    assert other_auth.post(f"/api/v1/containers/{cid}/share/").status_code == 404
    assert other_auth.get("/api/v1/containers/").data["results"] == []
    assert other_auth.get("/api/v1/search/?q=redis").data["entries"] == []


def test_text_entry_updates_counters_and_ai_names_container(auth, django_capture_on_commit_callbacks):
    cid = auth.post("/api/v1/containers/", {}, format="json").data["id"]
    with django_capture_on_commit_callbacks(execute=True):
        r = auth.post(
            f"/api/v1/containers/{cid}/entries/",
            {"text": "I need to improve Django API performance. Redis caching and Celery could help a lot here."},
            format="json",
        )
    assert r.status_code == 202
    c = Container.objects.get(pk=cid)
    assert c.entry_count == 1
    assert c.title_is_auto is False and c.title != "New note"  # AI named it

    entry = Entry.objects.get(pk=r.data["id"])
    assert entry.status == Entry.Status.COMPLETED
    assert entry.summary and entry.tags


def test_entry_validation(auth):
    cid = auth.post("/api/v1/containers/", {"title": "T"}, format="json").data["id"]
    url = f"/api/v1/containers/{cid}/entries/"
    assert auth.post(url, {}, format="json").status_code == 400
    assert auth.post(url, {"text": "   "}, format="json").status_code == 400


def test_delete_entry_decrements_counter(auth, django_capture_on_commit_callbacks):
    cid = auth.post("/api/v1/containers/", {"title": "T"}, format="json").data["id"]
    with django_capture_on_commit_callbacks(execute=True):
        eid = auth.post(f"/api/v1/containers/{cid}/entries/", {"text": "one"}, format="json").data["id"]
    assert Container.objects.get(pk=cid).entry_count == 1
    assert auth.delete(f"/api/v1/entries/{eid}/").status_code == 204
    assert Container.objects.get(pk=cid).entry_count == 0


def test_edit_entry_reprocesses(auth, django_capture_on_commit_callbacks):
    cid = auth.post("/api/v1/containers/", {"title": "T"}, format="json").data["id"]
    with django_capture_on_commit_callbacks(execute=True):
        eid = auth.post(f"/api/v1/containers/{cid}/entries/", {"text": "original text"}, format="json").data["id"]
    with django_capture_on_commit_callbacks(execute=True):
        r = auth.patch(f"/api/v1/entries/{eid}/", {"text": "edited text about kubernetes"}, format="json")
    assert r.data["text"] == "edited text about kubernetes"
    assert Entry.objects.get(pk=eid).status == Entry.Status.COMPLETED
    assert [str(e["id"]) for e in auth.get("/api/v1/search/?q=kubernetes").data["entries"]] == [eid]


def test_entry_pagination_is_cursor_based(auth, user, django_capture_on_commit_callbacks):
    cid = auth.post("/api/v1/containers/", {"title": "T"}, format="json").data["id"]
    with django_capture_on_commit_callbacks(execute=True):
        for i in range(5):
            auth.post(f"/api/v1/containers/{cid}/entries/", {"text": f"note {i}"}, format="json")
    r = auth.get(f"/api/v1/containers/{cid}/entries/?page_size=2")
    assert len(r.data["results"]) == 2 and r.data["next"]
    r2 = auth.get(r.data["next"])
    assert len(r2.data["results"]) == 2
    assert {e["id"] for e in r.data["results"]}.isdisjoint({e["id"] for e in r2.data["results"]})


def test_list_queries_are_constant(auth, user, django_assert_max_num_queries):
    """Guard against N+1: listing 10 containers must not issue per-row queries."""
    for i in range(10):
        Container.objects.create(owner=user, title=f"c{i}")
    with django_assert_max_num_queries(3):  # auth is forced, so: page query only (+ slack)
        r = auth.get("/api/v1/containers/")
    assert len(r.data["results"]) == 10
    with django_assert_max_num_queries(3):
        auth.get(f"/api/v1/containers/{Container.objects.first().pk}/entries/")
