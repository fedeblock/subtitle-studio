from pathlib import Path
from types import SimpleNamespace
import pytest
from app import main
from app.core import SessionLocal, Project, Cue


@pytest.fixture
def queued(monkeypatch):
    monkeypatch.setattr(
        main, "queue", lambda: SimpleNamespace(enqueue=lambda *a, **kw: None)
    )


def upload(client):
    return client.post(
        "/api/projects", files={"file": ("clip.wav", b"audio", "audio/wav")}
    )


def test_queue_failure_preserves_source_and_records_failure(client, monkeypatch):
    def unavailable():
        raise ConnectionError("queue offline")

    monkeypatch.setattr(main, "queue", unavailable)
    response = upload(client)
    assert response.status_code == 503
    projects = client.get("/api/projects").json()
    assert projects[0]["state"] == "failed"
    pid = projects[0]["id"]
    assert (Path(main.DATA) / pid / "source.wav").read_bytes() == b"audio"


def test_empty_upload_rejected(client, queued):
    response = client.post(
        "/api/projects", files={"file": ("empty.wav", b"", "audio/wav")}
    )
    assert response.status_code == 400
    assert client.get("/api/projects").json() == []


def test_upload_detail_media_and_export(client, queued):
    response = upload(client)
    assert response.status_code == 200
    pid = response.json()["id"]
    assert client.get(f"/api/projects/{pid}/media").content == b"audio"
    with SessionLocal() as db:
        db.get(Project, pid).state = "ready"
        db.add(
            Cue(
                id="cue",
                project_id=pid,
                position=0,
                start=1,
                end=2,
                original="Hello",
                translated="Hola",
            )
        )
        db.commit()
    assert (
        "00:00:01,000 --> 00:00:02,000\nHola"
        in client.get(f"/api/projects/{pid}/export").text
    )
    vtt = client.get(f"/api/projects/{pid}/export?language=original&format=vtt").text
    assert vtt.startswith("WEBVTT\n\n") and "Hello" in vtt


@pytest.mark.parametrize("state", ["queued", "transcribing", "translating"])
def test_edits_cannot_race_worker(client, queued, state):
    pid = upload(client).json()["id"]
    with SessionLocal() as db:
        db.get(Project, pid).state = state
        db.add(
            Cue(id="cue", project_id=pid, position=0, start=1, end=2, original="Hello")
        )
        db.commit()
    response = client.put(
        f"/api/projects/{pid}/cues/cue",
        json={"start": 1, "end": 2, "original": "Edited", "translated": "Hola"},
    )
    assert response.status_code == 409


def test_non_finite_timestamp_rejected():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        main.CueUpdate(start=1, end=float("inf"), original="text", translated="texto")


def test_health_reports_queue_outage(client, monkeypatch):
    def unavailable():
        raise ConnectionError("private connection details")

    monkeypatch.setattr(main, "queue", unavailable)
    response = client.get("/api/health")
    assert response.status_code == 503
    assert "private connection details" not in response.text


def test_retry_failed_project_and_reject_duplicate(client, queued):
    pid = upload(client).json()["id"]
    with SessionLocal() as db:
        db.get(Project, pid).state = "failed"
        db.commit()
    assert client.post(f"/api/projects/{pid}/retry").status_code == 200
    assert client.get(f"/api/projects/{pid}").json()["project"]["state"] == "queued"
    assert client.post(f"/api/projects/{pid}/retry").status_code == 409


def test_retry_queue_failure_is_visible_and_keeps_media(client, queued, monkeypatch):
    pid = upload(client).json()["id"]
    with SessionLocal() as db:
        db.get(Project, pid).state = "failed"
        db.commit()

    def unavailable():
        raise ConnectionError("offline")

    monkeypatch.setattr(main, "queue", unavailable)
    assert client.post(f"/api/projects/{pid}/retry").status_code == 503
    assert client.get(f"/api/projects/{pid}").json()["project"]["state"] == "failed"
    assert client.get(f"/api/projects/{pid}/media").content == b"audio"


def test_stale_editor_does_not_overwrite_other_changes(client, queued):
    pid = upload(client).json()["id"]
    with SessionLocal() as db:
        db.get(Project, pid).state = "ready"
        db.add(
            Cue(
                id="cue",
                project_id=pid,
                position=0,
                start=1,
                end=2,
                original="New original",
                translated="",
            )
        )
        db.commit()
    old = {"start": 1, "end": 2, "original": "Old original", "translated": ""}
    change = {**old, "translated": "Hola", "expected": old}
    response = client.put(f"/api/projects/{pid}/cues/cue", json=change)
    assert response.status_code == 409
    assert (
        client.get(f"/api/projects/{pid}").json()["cues"][0]["original"]
        == "New original"
    )
