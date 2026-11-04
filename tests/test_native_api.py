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
