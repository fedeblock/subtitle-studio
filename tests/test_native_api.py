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
        return {
            "srt": "1\n00:00:00,000 --> 00:00:01,000\nHello\n",
            "end_of_audio": True,
        }

    monkeypatch.setattr(worker, "mac_post", native)
    worker.process_project(pid)
    assert seen == [
        ("/transcribe-chunk", {"project_id": pid, "audio_index": 3, "segment_start": 0})
    ]


def test_transcribe_lands_editable_without_edit_mode(client, monkeypatch):
    from app import worker

    pid = local_project()
    monkeypatch.setattr(
        main, "queue", lambda: SimpleNamespace(enqueue=lambda *a, **kw: None)
    )
    seen = []

    def native(path, payload, **kwargs):
        seen.append(path)
        return {
            "srt": "1\n00:00:00,000 --> 00:00:01,000\nHello\n",
            "end_of_audio": True,
        }

    monkeypatch.setattr(worker, "mac_post", native)
    assert (
        client.post(
            f"/api/projects/{pid}/start", json={"source": "asr", "action": "edit"}
        ).status_code
        == 200
    )
    worker.process_project(pid)
    detail = client.get(f"/api/projects/{pid}").json()
    assert seen == ["/transcribe-chunk"]
    assert detail["project"]["state"] == "ready"
    assert detail["project"]["action"] == "edit"
    assert detail["cues"][0]["original"] == "Hello"
    assert client.post(f"/api/projects/{pid}/edit-mode").status_code == 404


def test_selected_audio_must_be_from_inspected_tracks(client):
    pid = local_project()
    response = client.post(
        f"/api/projects/{pid}/start",
        json={"source": "asr", "action": "edit", "audio_index": 123},
    )
    assert response.status_code == 400
    assert client.get(f"/api/projects/{pid}").json()["project"]["state"] == "draft"


def test_selected_asr_language_is_preserved_for_transcription(client, monkeypatch):
    from app.project_sources import reference

    pid = local_project()
    monkeypatch.setattr(
        main, "queue", lambda: SimpleNamespace(enqueue=lambda *a, **kw: None)
    )
    response = client.post(
        f"/api/projects/{pid}/start",
        json={"source": "asr", "action": "edit", "asr_language": "Romanian"},
    )
    assert response.status_code == 200
    assert reference(pid)["asr_language"] == "Romanian"


def test_start_rejects_new_view_mode_without_changing_draft(client):
    pid = local_project()
    response = client.post(
        f"/api/projects/{pid}/start", json={"source": "asr", "action": "view"}
    )
    assert response.status_code == 422
    assert client.get(f"/api/projects/{pid}").json()["project"]["state"] == "draft"


def test_audio_stream_proxies_selected_track_without_buffering(client, monkeypatch):
    pid = local_project()
    path = Path(main.DATA) / pid / "source.json"
    info = json.loads(path.read_text())
    info["audio_tracks"] = [{"index": 2, "label": "Spanish"}]
    path.write_text(json.dumps(info))
    seen = []

    import httpx

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=b"audio")

    monkeypatch.setattr(
        main,
        "audio_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        raising=False,
    )
    r = client.get(f"/api/projects/{pid}/audio-stream?index=2&start=25")
    assert r.status_code == 200 and r.content == b"audio"
    assert seen[0].url.path == f"/files/{pid}/audio-stream"
    assert seen[0].url.params["index"] == "2"
    assert float(seen[0].url.params["start"]) == 25.0
    assert client.get(f"/api/projects/{pid}/audio-stream?index=9").status_code == 400


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


def test_subtitle_preview_does_not_start_or_modify_project(client, monkeypatch):
    pid = local_project()

    def native(method, path, **kwargs):
        assert path == "/files/subtitle"
        assert kwargs["json"] == {"project_id": pid, "subtitle_id": "srt1"}
        return SimpleNamespace(
            json=lambda: {"srt": "1\n00:00:02,000 --> 00:00:03,000\nHello preview\n"}
        )

    monkeypatch.setattr(main, "native_request", native)
    result = client.get(
        f"/api/projects/{pid}/subtitle-preview", params={"subtitle_id": "srt1"}
    )
    assert result.status_code == 200
    assert result.json()["cues"][0]["original"] == "Hello preview"
    detail = client.get(f"/api/projects/{pid}").json()
    assert detail["project"]["state"] == "draft" and detail["cues"] == []


def test_audio_preview_passes_validated_track_and_position(client, monkeypatch):
    pid = local_project()
    path = Path(main.DATA) / pid / "source.json"
    data = json.loads(path.read_text())
    data["audio_tracks"] = [{"index": 3, "label": "Spanish"}]
    path.write_text(json.dumps(data))

    def native(method, url, **kwargs):
        assert method == "GET" and url == f"/files/{pid}/audio-preview"
        assert kwargs["params"] == {"index": 3, "start": 12.5}
        return SimpleNamespace(content=b"mp3")

    monkeypatch.setattr(main, "native_request", native)
    result = client.get(f"/api/projects/{pid}/audio-preview?index=3&start=12.5")
    assert result.status_code == 200 and result.content == b"mp3"
    assert result.headers["content-type"] == "audio/mpeg"
    assert (
        client.get(f"/api/projects/{pid}/audio-preview?index=99&start=0").status_code
        == 400
    )
    assert (
        client.get(f"/api/projects/{pid}/audio-preview?index=3&start=nan").status_code
        == 422
    )


def test_subtitle_preview_returns_all_segments_and_full_text(client, monkeypatch):
    pid = local_project()
    long_text = "A" * 700
    chunks = [
        f"{i}\n00:00:{i:02},000 --> 00:00:{i:02},900\n"
        + (long_text if i == 1 else f"Line {i}")
        for i in range(1, 13)
    ]
    monkeypatch.setattr(
        main,
        "native_request",
        lambda *a, **kw: SimpleNamespace(json=lambda: {"srt": "\n\n".join(chunks)}),
    )
    response = client.get(
        f"/api/projects/{pid}/subtitle-preview", params={"subtitle_id": "srt1"}
    )
    assert response.status_code == 200
    assert len(response.json()["cues"]) == 12
    assert response.json()["cues"][0]["original"] == long_text
    assert client.get(f"/api/projects/{pid}").json()["project"]["state"] == "draft"
