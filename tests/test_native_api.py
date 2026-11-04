import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from app import main
from app.core import SessionLocal, Project


def local_project():
    pid = str(uuid.uuid4())
    folder = Path(main.DATA) / pid
    folder.mkdir(parents=True)
    (folder / "source.json").write_text(
        json.dumps(
            {
                "path": "/selected/original.mp4",
                "subtitles": [
                    {
                        "id": "srt1",
                        "kind": "file",
                        "label": "movie.en.srt",
                        "path": "/selected/movie.en.srt",
                        "supported": True,
                    }
                ],
            }
        )
    )
    with SessionLocal() as db:
        db.add(
            Project(
                id=pid,
                name="original.mp4",
                filename="source.json",
                state="draft",
                created=0,
            )
        )
        db.commit()
    return pid


def test_native_open_does_not_enqueue_until_source_chosen(client, monkeypatch):
    def native(method, path, **kwargs):
        pid = kwargs["json"]["project_id"]
        folder = Path(main.DATA) / pid
        folder.mkdir(parents=True)
        (folder / "source.json").write_text(
            json.dumps({"path": "/original.mp4", "subtitles": []})
        )
        return SimpleNamespace(
            status_code=200,
            json=lambda: {"name": "original.mp4", "filename": "source.json"},
        )

    monkeypatch.setattr(main, "native_request", native, raising=False)
    response = client.post("/api/projects/local", headers={"X-Studio-Local": "1"})
    assert response.status_code == 200
    detail = client.get("/api/projects/" + response.json()["id"]).json()
    assert detail["project"]["state"] == "draft"
    assert detail["project"]["source_kind"] == "reference"
    assert client.post("/api/projects/local").status_code == 403


def test_import_srt_for_edit_without_inference(client, monkeypatch):
    pid = local_project()

    def native(method, path, **kwargs):
        assert path == "/files/subtitle"
        return SimpleNamespace(
            json=lambda: {"srt": "1\n00:00:00,000 --> 00:00:01,000\nHello\n"}
        )

    monkeypatch.setattr(main, "native_request", native, raising=False)
    response = client.post(
        f"/api/projects/{pid}/start", json={"source": "srt1", "action": "edit"}
    )
    assert response.status_code == 200
    detail = client.get(f"/api/projects/{pid}").json()
    assert (
        detail["project"]["state"] == "ready"
        and detail["cues"][0]["original"] == "Hello"
    )
    assert detail["cues"][0]["translated"] == ""
    assert "path" not in detail["project"]["subtitle_options"][0]
    assert (
        client.post(
            f"/api/projects/{pid}/start", json={"source": "srt1", "action": "edit"}
        ).status_code
        == 409
    )


def test_import_subtitles_for_translation_enqueues_and_preserves_timing(
    client, monkeypatch
):
    pid = local_project()
    jobs = []
    monkeypatch.setattr(
        main, "queue", lambda: SimpleNamespace(enqueue=lambda *a, **kw: jobs.append(a))
    )
    monkeypatch.setattr(
        main,
        "native_request",
        lambda *a, **kw: SimpleNamespace(
            json=lambda: {"srt": "1\n00:00:02,000 --> 00:00:03,500\nHello\n"}
        ),
        raising=False,
    )
    assert (
        client.post(
            f"/api/projects/{pid}/start", json={"source": "srt1", "action": "translate"}
        ).status_code
        == 200
    )
    detail = client.get(f"/api/projects/{pid}").json()
    assert detail["project"]["state"] == "queued"
    assert detail["cues"][0]["start"] == 2 and detail["cues"][0]["end"] == 3.5
    assert len(jobs) == 1


def test_invalid_import_leaves_draft_recoverable(client, monkeypatch):
    pid = local_project()
    monkeypatch.setattr(
        main,
        "native_request",
        lambda *a, **kw: SimpleNamespace(
            json=lambda: {"srt": "1\ninvalid --> timestamp\nHello\n"}
        ),
    )
    response = client.post(
        f"/api/projects/{pid}/start", json={"source": "srt1", "action": "edit"}
    )
    assert response.status_code == 422
    detail = client.get(f"/api/projects/{pid}").json()
    assert detail["project"]["state"] == "draft" and not detail["cues"]


def test_translate_after_edit_preserves_cues_and_enqueues(client, monkeypatch):
    pid = local_project()
    with SessionLocal() as db:
        p = db.get(Project, pid)
        p.state = "ready"
        from app.core import Cue

        db.add(
            Cue(
                id="reviewed",
                project_id=pid,
                position=0,
                start=2,
                end=4,
                original="Corrected text.",
                translated="",
            )
        )
        db.commit()
    from app.project_sources import save_workflow, reference

    save_workflow(pid, "srt1", "edit")
    jobs = []
    monkeypatch.setattr(
        main, "queue", lambda: SimpleNamespace(enqueue=lambda *a, **kw: jobs.append(a))
    )
    assert client.post(f"/api/projects/{pid}/translate").status_code == 200
    detail = client.get(f"/api/projects/{pid}").json()
    assert (
        detail["project"]["state"] == "queued"
        and detail["cues"][0]["original"] == "Corrected text."
    )
    assert reference(pid)["action"] == "translate" and len(jobs) == 1


def test_selected_audio_is_saved_and_sent_to_worker(client, monkeypatch):
    import json
    from app.project_sources import reference
    from app import worker

    pid = local_project()
    path = Path(main.DATA) / pid / "source.json"
    info = json.loads(path.read_text())
    info["audio_tracks"] = [
        {"index": 2, "label": "English"},
        {"index": 3, "label": "Español"},
    ]
    path.write_text(json.dumps(info))
    jobs = []
    monkeypatch.setattr(
        main, "queue", lambda: SimpleNamespace(enqueue=lambda *a, **k: jobs.append(a))
    )
    assert (
        client.post(
            f"/api/projects/{pid}/start",
            json={"source": "asr", "action": "edit", "audio_index": 3},
        ).status_code
        == 200
    )
    assert reference(pid)["audio_index"] == 3
    seen = []

    def native(path, json, **kwargs):
        seen.append((path, json))
        return {"srt": "1\n00:00:00,000 --> 00:00:01,000\nHello\n"}

    monkeypatch.setattr(worker, "mac_post", native)
    worker.process_project(pid)
    assert seen == [("/transcribe", {"project_id": pid, "audio_index": 3})]


def test_selected_audio_must_be_from_inspected_tracks(client):
    pid = local_project()
    response = client.post(
        f"/api/projects/{pid}/start",
        json={"source": "asr", "action": "edit", "audio_index": 123},
    )
    assert response.status_code == 400
    assert client.get(f"/api/projects/{pid}").json()["project"]["state"] == "draft"


def test_export_local_passes_srt_to_native_gateway(client, monkeypatch):
    from app.core import Cue

    pid = local_project()
    with SessionLocal() as db:
        db.get(Project, pid).state = "ready"
        db.add(
            Cue(
                id="export-cue",
                project_id=pid,
                position=0,
                start=1,
                end=2,
                original="Hello",
                translated="Hola",
            )
        )
        db.commit()

    def native(method, path, **kwargs):
        assert path == "/files/export"
        assert kwargs["json"]["project_id"] == pid
        assert "Hola" in kwargs["json"]["content"]
        return SimpleNamespace(
            json=lambda: {
                "path": "/selected/original.es.srt",
                "filename": "original.es.srt",
            }
        )

    monkeypatch.setattr(main, "native_request", native)
    result = client.post(
        f"/api/projects/{pid}/export/local", json={"language": "es", "format": "srt"}
    )
    assert result.status_code == 200 and result.json()["filename"] == "original.es.srt"
