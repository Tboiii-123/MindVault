import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from apps.ai import tasks
from apps.ai.providers.base import PermanentAIError, TransientAIError
from apps.containers.models import Container, Entry

pytestmark = pytest.mark.django_db


def test_voice_upload_is_transcribed_analyzed_and_searchable(auth, audio_file, django_capture_on_commit_callbacks):
    cid = auth.post("/api/v1/containers/", {"title": "Databases"}, format="json").data["id"]
    with django_capture_on_commit_callbacks(execute=True):
        r = auth.post(f"/api/v1/containers/{cid}/entries/", {"audio": audio_file()}, format="multipart")
    assert r.status_code == 202
    assert r.data["kind"] == "voice" and r.data["status"] == "pending"  # returns BEFORE processing

    e = Entry.objects.get(pk=r.data["id"])
    assert e.status == Entry.Status.COMPLETED
    assert "B plus trees" in e.transcript
    assert e.audio_duration_seconds
    assert e.audio.name.startswith(f"audio/{e.owner_id}/{cid}/")  # server-generated path

    hits = auth.get("/api/v1/search/?q=indexing").data["entries"]
    assert [str(h["id"]) for h in hits] == [str(e.pk)]
    assert "<mark>" in hits[0]["snippet"]


def test_capture_voice_creates_and_names_container(auth, audio_file, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        r = auth.post(
            "/api/v1/capture/",
            {"audio": audio_file("I want to build a speech to text API with websockets for realtime transcription.")},
            format="multipart",
        )
    assert r.status_code == 202
    c = Container.objects.get(pk=r.data["container"]["id"])
    assert c.title != "New note" and c.icon


@pytest.mark.parametrize(
    "name,ctype",
    [("evil.exe", "application/octet-stream"), ("a.mp3", "text/html"), ("a.txt", "audio/mpeg")],
)
def test_rejects_non_audio(auth, name, ctype):
    cid = auth.post("/api/v1/containers/", {"title": "T"}, format="json").data["id"]
    f = SimpleUploadedFile(name, b"xxx", content_type=ctype)
    assert auth.post(f"/api/v1/containers/{cid}/entries/", {"audio": f}, format="multipart").status_code == 400


@override_settings(AUDIO_MAX_BYTES=10)
def test_rejects_oversized_audio(auth, audio_file):
    cid = auth.post("/api/v1/containers/", {"title": "T"}, format="json").data["id"]
    assert (
        auth.post(f"/api/v1/containers/{cid}/entries/", {"audio": audio_file()}, format="multipart").status_code == 400
    )


def test_permanent_failure_marks_failed_and_retry_works(
    auth, audio_file, monkeypatch, django_capture_on_commit_callbacks
):
    class Boom:
        def transcribe(self, *a, **k):
            raise PermanentAIError("corrupt audio")

    monkeypatch.setattr(tasks, "get_stt", lambda: Boom())
    cid = auth.post("/api/v1/containers/", {"title": "T"}, format="json").data["id"]
    with django_capture_on_commit_callbacks(execute=True):
        eid = auth.post(f"/api/v1/containers/{cid}/entries/", {"audio": audio_file()}, format="multipart").data["id"]
    e = Entry.objects.get(pk=eid)
    assert e.status == Entry.Status.FAILED and "corrupt audio" in e.error_message

    monkeypatch.undo()
    with django_capture_on_commit_callbacks(execute=True):
        assert auth.post(f"/api/v1/entries/{eid}/retry/").status_code == 202
    assert Entry.objects.get(pk=eid).status == Entry.Status.COMPLETED
    # only failed entries can be retried
    assert auth.post(f"/api/v1/entries/{eid}/retry/").status_code == 409


def test_transient_error_is_retried_and_transcript_not_recomputed(
    auth, audio_file, monkeypatch, django_capture_on_commit_callbacks
):
    stt_calls = {"n": 0}
    llm_calls = {"n": 0}
    real_llm = tasks.get_llm()

    class FlakyLLM:
        def analyze_entry(self, text):
            llm_calls["n"] += 1
            if llm_calls["n"] == 1:
                raise TransientAIError("rate limited")
            return real_llm.analyze_entry(text)

        suggest_title = real_llm.suggest_title

    real_stt = tasks.get_stt()

    class CountingSTT:
        def transcribe(self, *a, **k):
            stt_calls["n"] += 1
            return real_stt.transcribe(*a, **k)

    monkeypatch.setattr(tasks, "get_llm", lambda: FlakyLLM())
    monkeypatch.setattr(tasks, "get_stt", lambda: CountingSTT())

    cid = auth.post("/api/v1/containers/", {"title": "T"}, format="json").data["id"]
    long_speech = "Today we discussed B plus trees, database indexing, and why range scans are fast on leaf nodes."
    with django_capture_on_commit_callbacks(execute=True):
        eid = auth.post(
            f"/api/v1/containers/{cid}/entries/", {"audio": audio_file(long_speech)}, format="multipart"
        ).data["id"]
    e = Entry.objects.get(pk=eid)
    assert e.status == Entry.Status.COMPLETED
    assert llm_calls["n"] == 2  # failed once, succeeded on retry
    assert stt_calls["n"] == 1  # idempotent: the transcript was reused, STT not paid for twice


def test_deleting_container_removes_audio_files(auth, audio_file, django_capture_on_commit_callbacks):
    cid = auth.post("/api/v1/containers/", {"title": "T"}, format="json").data["id"]
    with django_capture_on_commit_callbacks(execute=True):
        eid = auth.post(f"/api/v1/containers/{cid}/entries/", {"audio": audio_file()}, format="multipart").data["id"]
    e = Entry.objects.get(pk=eid)
    storage, name = e.audio.storage, e.audio.name
    assert storage.exists(name)
    with django_capture_on_commit_callbacks(execute=True):
        auth.delete(f"/api/v1/containers/{cid}/")
    assert not storage.exists(name)


def test_container_summary_task(auth, django_capture_on_commit_callbacks):
    cid = auth.post("/api/v1/containers/", {"title": "Databases"}, format="json").data["id"]
    with django_capture_on_commit_callbacks(execute=True):
        for t in ("B-trees keep data sorted.", "Normalisation removes redundancy."):
            auth.post(f"/api/v1/containers/{cid}/entries/", {"text": t}, format="json")
    r = auth.post(f"/api/v1/containers/{cid}/summary/", {"period": "week"}, format="json")
    assert r.status_code == 202
    c = Container.objects.get(pk=cid)
    assert c.summary_status == "completed" and "B-trees" in c.summary

    assert auth.post(f"/api/v1/containers/{cid}/summary/", {"period": "custom"}, format="json").status_code == 400


def test_stuck_entries_are_requeued(auth, user):
    from datetime import timedelta

    from django.utils import timezone

    c = Container.objects.create(owner=user, title="T")
    stuck = Entry.objects.create(container=c, owner=user, kind="text", text="hello world", status="analyzing")
    Entry.objects.filter(pk=stuck.pk).update(updated_at=timezone.now() - timedelta(hours=1))
    assert tasks.requeue_stuck_entries() == 1
    assert Entry.objects.get(pk=stuck.pk).status == Entry.Status.COMPLETED
