import io
import json
import uuid
import pytest
from fastapi.testclient import TestClient
import server


@pytest.fixture
def gateway():
    with TestClient(server.app, raise_server_exceptions=False) as client:
        yield client


def test_health_requires_token_and_does_not_load_models(gateway):
    assert gateway.get("/health").status_code == 401
    result = gateway.get("/health", headers={"X-Worker-Token": server.TOKEN})
    assert result.status_code == 200
    assert result.json()["idle_seconds"] == 600


def test_multiple_selection_registers_references_without_copying_video(
    gateway, monkeypatch, tmp_path
):
    source_a, source_b = tmp_path / "a.mkv", tmp_path / "b.mp4"
    source_a.write_bytes(b"first video")
    source_b.write_bytes(b"second video")
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(server, "ROOT", data)
    monkeypatch.setattr(server, "choose_local_paths", lambda: [source_a, source_b])
    monkeypatch.setattr(server, "discover_subtitles", lambda source: ([], []))
    monkeypatch.setattr(server, "discover_audio", lambda source: [])
    response = gateway.post(
        "/files/select-many", headers={"X-Worker-Token": server.TOKEN}
    )
    assert response.status_code == 200
    entries = response.json()["projects"]
    assert [entry["name"] for entry in entries] == ["a.mkv", "b.mp4"]
    assert {
        json.loads((data / entry["id"] / "source.json").read_text())["path"]
        for entry in entries
    } == {str(source_a), str(source_b)}
    assert (
        source_a.read_bytes() == b"first video"
        and source_b.read_bytes() == b"second video"
    )
    assert all(
        [file.name for file in (data / entry["id"]).iterdir()] == ["source.json"]
        for entry in entries
    )


def test_chunk_transcription_passes_language_and_offset_to_runtime(
    gateway, monkeypatch, tmp_path
):
    source = tmp_path / "clip.mkv"
    source.write_bytes(b"video")
    monkeypatch.setattr(server, "resolve_source", lambda pid: source)
    seen = []
    monkeypatch.setattr(
        server.app.state.asr,
        "transcribe_chunk",
        lambda path, start, **kw: seen.append((path, start, kw))
        or {"srt": "", "end_of_audio": True},
    )
    pid = str(uuid.uuid4())
    response = gateway.post(
        "/transcribe-chunk",
        json={"project_id": pid, "segment_start": 30, "language": "Romanian"},
        headers={"X-Worker-Token": server.TOKEN},
    )
    assert response.status_code == 200
    assert seen == [
        (source, 30, {"audio_index": None, "language": "Romanian", "model": "qwen"})
    ]


def test_comparison_uses_same_source_track_and_time(gateway, monkeypatch, tmp_path):
    source = tmp_path / "clip.mkv"
    source.write_bytes(b"video")
    monkeypatch.setattr(server, "resolve_source", lambda pid: source)
    seen = []
    monkeypatch.setattr(
        server.app.state.asr,
        "compare_chunk",
        lambda path, start, **kw: seen.append((path, start, kw))
        or {"qwen": {"srt": "one"}, "whisper": {"srt": "two"}},
    )
    response = gateway.post(
        "/compare-models",
        json={
            "project_id": str(uuid.uuid4()),
            "segment_start": 30,
            "language": "Romanian",
        },
        headers={"X-Worker-Token": server.TOKEN},
    )
    assert response.status_code == 200
    assert seen == [(source, 30, {"audio_index": None, "language": "Romanian"})]
    assert set(response.json()["results"]) == {"qwen", "whisper"}


def test_symlink_source_cannot_escape_data(gateway, tmp_path):
    folder = server.ROOT / str(uuid.uuid4())
    folder.mkdir(parents=True)
    outside = tmp_path / "private.wav"
    outside.write_bytes(b"not a project file")
    (folder / "source.wav").symlink_to(outside)
    response = gateway.post(
        "/transcribe",
        json={"project_id": folder.name},
        headers={"X-Worker-Token": server.TOKEN},
    )
    assert response.status_code == 400


def test_translation_contract(gateway, monkeypatch):
    payloads = []

    def respond(request, timeout):
        payloads.append(json.loads(request.data))
        return io.BytesIO(json.dumps({"response": '{"1":"Hola"}'}).encode())

    monkeypatch.setattr(server.urllib.request, "urlopen", respond)
    result = gateway.post(
        "/translate",
        json={"texts": ["Hello"]},
        headers={"X-Worker-Token": server.TOKEN},
    )
    assert result.json() == {"texts": ["Hola"]}
    assert payloads[0]["keep_alive"] == "10m"


def test_translation_can_target_romanian(gateway, monkeypatch):
    instructions = []
    monkeypatch.setattr(
        server,
        "model_subtitles",
        lambda texts, context, instruction: instructions.append(instruction)
        or ["Bună"],
    )
    response = gateway.post(
        "/translate",
        json={"texts": ["Hola"], "target_language": "Romanian"},
        headers={"X-Worker-Token": server.TOKEN},
    )
    assert response.json() == {"texts": ["Bună"]}
    assert "rumano" in instructions[0].lower()


def test_translation_uses_requested_ollama_model(gateway, monkeypatch):
    seen = []
    monkeypatch.setattr(
        server,
        "model_subtitles",
        lambda texts, context, instruction, model=None: seen.append(model) or ["Hola"],
    )
    result = gateway.post(
        "/translate",
        headers={"X-Worker-Token": server.TOKEN},
        json={"texts": ["Hello"], "target_language": "Spanish", "model": "chosen"},
    )
    assert result.status_code == 200
    assert seen == ["chosen"]


def test_improvement_uses_selected_installed_model(gateway, monkeypatch):
    seen = []
    monkeypatch.setattr(server, "ollama_models", lambda: [{"name": "chosen:latest"}])
    monkeypatch.setattr(
        server,
        "model_subtitles",
        lambda texts, context, instruction, model=None: seen.append(model)
        or ["Hello."],
    )
    headers = {"X-Worker-Token": server.TOKEN}
    response = gateway.post(
        "/improve", headers=headers, json={"texts": ["hello"], "model": "chosen:latest"}
    )
    assert response.status_code == 200 and response.json()["texts"] == ["Hello."]
    assert seen == ["chosen:latest"]
    assert (
        gateway.post(
            "/improve",
            headers=headers,
            json={"texts": ["hello"], "model": "not-installed"},
        ).status_code
        == 400
    )


def test_compare_translations_only_uses_installed_models(gateway, monkeypatch):
    monkeypatch.setattr(
        server,
        "ollama_models",
        lambda: [{"name": "one:latest"}, {"name": "two:latest"}],
    )

    seen = []

    def run(texts, context, instruction, model=None):
        seen.append((texts, model))
        return [f"resultado {model}"]

    monkeypatch.setattr(server, "model_subtitles", run)
    headers = {"X-Worker-Token": server.TOKEN}
    response = gateway.post(
        "/compare-translations",
        headers=headers,
        json={
            "text": "Hola",
            "target_language": "Romanian",
            "models": ["one:latest", "two:latest"],
        },
    )
    assert response.status_code == 200
    assert [x[1] for x in seen] == ["one:latest", "two:latest"]
    assert len(response.json()["results"]) == 2
    assert (
        gateway.post(
            "/compare-translations",
            headers=headers,
            json={
                "text": "Hola",
                "target_language": "Romanian",
                "models": ["one:latest", "missing"],
            },
        ).status_code
        == 400
    )


def test_compare_translations_range_keeps_cue_alignment(gateway, monkeypatch):
    monkeypatch.setattr(
        server, "ollama_models", lambda: [{"name": "one"}, {"name": "two"}]
    )
    monkeypatch.setattr(
        server,
        "model_subtitles",
        lambda texts, context, instruction, model=None: [
            f"{model}:{text}" for text in texts
        ],
    )
    response = gateway.post(
        "/compare-translations-range",
        headers={"X-Worker-Token": server.TOKEN},
        json={
            "texts": ["Hello", "World"],
            "target_language": "Spanish",
            "models": ["one", "two"],
        },
    )
    assert response.status_code == 200
    assert response.json()["results"][0]["texts"] == ["one:Hello", "one:World"]
    assert response.json()["results"][1]["texts"] == ["two:Hello", "two:World"]


def test_translation_rejects_wrong_keys(gateway, monkeypatch):
    monkeypatch.setattr(
        server.urllib.request,
        "urlopen",
        lambda *a, **kw: io.BytesIO(b'{"response":"{\\"2\\":\\"Hola\\"}"}'),
    )
    result = gateway.post(
        "/translate",
        json={"texts": ["Hello"]},
        headers={"X-Worker-Token": server.TOKEN},
    )
    assert result.status_code == 502


def test_native_selection_records_reference_without_copy(
    gateway, monkeypatch, tmp_path
):
    source = tmp_path / "original.mp4"
    source.write_bytes(b"original-video")
    before = source.stat()
    monkeypatch.setattr(server, "choose_local_file", lambda: source, raising=False)
    pid = str(uuid.uuid4())
    response = gateway.post(
        "/files/select",
        json={"project_id": pid},
        headers={"X-Worker-Token": server.TOKEN},
    )
    assert response.status_code == 200
    folder = server.ROOT / pid
    assert [p.name for p in folder.iterdir()] == ["source.json"]
    assert json.loads((folder / "source.json").read_text())["path"] == str(source)
    assert source.read_bytes() == b"original-video"
    assert source.stat().st_mtime_ns == before.st_mtime_ns
    media = gateway.get(
        f"/files/{pid}/media",
        headers={"X-Worker-Token": server.TOKEN, "Range": "bytes=0-7"},
    )
    assert media.status_code == 206 and media.content == b"original"
    assert media.headers["content-range"] == "bytes 0-7/14"
    source.rename(tmp_path / "moved.mp4")
    assert (
        gateway.get(
            f"/files/{pid}/media", headers={"X-Worker-Token": server.TOKEN}
        ).status_code
        == 410
    )


def test_native_picker_cancel_creates_no_project(gateway, monkeypatch):
    monkeypatch.setattr(server, "choose_local_file", lambda: None, raising=False)
    pid = str(uuid.uuid4())
    response = gateway.post(
        "/files/select",
        json={"project_id": pid},
        headers={"X-Worker-Token": server.TOKEN},
    )
    assert response.status_code == 204
    assert not (server.ROOT / pid).exists()


def test_native_reference_is_transcribed_directly(gateway, monkeypatch, tmp_path):
    source = tmp_path / "original.wav"
    source.write_bytes(b"audio")
    monkeypatch.setattr(server, "choose_local_file", lambda: source, raising=False)
    pid = str(uuid.uuid4())
    gateway.post(
        "/files/select",
        json={"project_id": pid},
        headers={"X-Worker-Token": server.TOKEN},
    )
    paths = []
    monkeypatch.setattr(
        server.app.state.asr,
        "transcribe",
        lambda path: paths.append(path) or {"srt": "ok"},
    )
    response = gateway.post(
        "/transcribe",
        json={"project_id": pid},
        headers={"X-Worker-Token": server.TOKEN},
    )
    assert response.status_code == 200
    assert paths == [source]


def test_reference_rejects_redirected_parent(gateway, monkeypatch, tmp_path):
    parent = tmp_path / "selected"
    parent.mkdir()
    source = parent / "movie.mp4"
    source.write_bytes(b"selected")
    monkeypatch.setattr(server, "choose_local_file", lambda: source)
    pid = str(uuid.uuid4())
    headers = {"X-Worker-Token": server.TOKEN}
    assert (
        gateway.post(
            "/files/select", json={"project_id": pid}, headers=headers
        ).status_code
        == 200
    )
    parent.rename(tmp_path / "original")
    other = tmp_path / "other"
    other.mkdir()
    (other / "movie.mp4").write_bytes(b"unselected")
    parent.symlink_to(other)
    assert gateway.get(f"/files/{pid}/media", headers=headers).status_code == 409


def test_subtitle_conversion_failure_has_actionable_error(
    gateway, monkeypatch, tmp_path
):
    import subprocess

    source = tmp_path / "movie.mkv"
    source.write_bytes(b"video")
    monkeypatch.setattr(server, "choose_local_file", lambda: source)
    monkeypatch.setattr(
        server, "discover_subtitles", lambda _: ([{"id": "sub", "supported": True}], [])
    )
    pid = str(uuid.uuid4())
    headers = {"X-Worker-Token": server.TOKEN}
    gateway.post("/files/select", json={"project_id": pid}, headers=headers)

    def fail(*args):
        raise subprocess.CalledProcessError(1, ["ffmpeg"])

    monkeypatch.setattr(server, "read_subtitle", fail)
    response = gateway.post(
        "/files/subtitle",
        json={"project_id": pid, "subtitle_id": "sub"},
        headers=headers,
    )
    assert response.status_code == 409
    assert "FFmpeg" in response.json()["detail"]


def test_translation_retries_only_empty_entries_individually(gateway, monkeypatch):
    replies = iter(
        [
            {"response": '{"1":"Hola","2":""}'},
            {"response": '{"1":"Mundo"}'},
        ]
    )
    payloads = []

    def respond(request, timeout):
        payloads.append(json.loads(request.data))
        return io.BytesIO(json.dumps(next(replies)).encode())

    monkeypatch.setattr(server.urllib.request, "urlopen", respond)
    response = gateway.post(
        "/translate",
        json={"texts": ["Hello", "World"]},
        headers={"X-Worker-Token": server.TOKEN},
    )
    assert response.status_code == 200
    assert response.json()["texts"] == ["Hola", "Mundo"]
    assert len(payloads) == 2
    assert "World" in payloads[1]["prompt"] and "Hello" not in payloads[1]["prompt"]


def test_translation_retries_malformed_batch_individually(gateway, monkeypatch):
    replies = iter(
        [
            {"response": '{"1":"Hola","3":"Mundo"}'},
            {"response": '{"1":"Hola"}'},
            {"response": '{"1":"Mundo"}'},
        ]
    )
    monkeypatch.setattr(
        server.urllib.request,
        "urlopen",
        lambda *a, **kw: io.BytesIO(json.dumps(next(replies)).encode()),
    )
    response = gateway.post(
        "/translate",
        json={"texts": ["Hello", "World"]},
        headers={"X-Worker-Token": server.TOKEN},
    )
    assert response.status_code == 200
    assert response.json()["texts"] == ["Hola", "Mundo"]


def test_gateway_transcribes_only_selected_validated_audio_track(
    gateway, monkeypatch, tmp_path
):
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"video")
    monkeypatch.setattr(server, "choose_local_file", lambda: source)
    monkeypatch.setattr(
        server,
        "discover_audio",
        lambda p: [{"index": 2, "label": "English"}, {"index": 3, "label": "Español"}],
        raising=False,
    )
    pid = str(uuid.uuid4())
    headers = {"X-Worker-Token": server.TOKEN}
    assert (
        gateway.post(
            "/files/select", json={"project_id": pid}, headers=headers
        ).status_code
        == 200
    )
    seen = []
    monkeypatch.setattr(
        server.app.state.asr,
        "transcribe",
        lambda path, audio_index=None: seen.append((path, audio_index))
        or {"srt": "ok"},
    )
    assert (
        gateway.post(
            "/transcribe", json={"project_id": pid, "audio_index": 3}, headers=headers
        ).status_code
        == 200
    )
    assert seen == [(source, 3)]
    assert (
        gateway.post(
            "/transcribe", json={"project_id": pid, "audio_index": 99}, headers=headers
        ).status_code
        == 400
    )


def test_export_saves_next_to_original_without_overwriting(
    gateway, monkeypatch, tmp_path
):
    source = tmp_path / "Movie.mkv"
    source.write_bytes(b"video")
    existing = tmp_path / "Movie.es.srt"
    existing.write_text("existing subtitle")
    monkeypatch.setattr(server, "choose_local_file", lambda: source)
    pid = str(uuid.uuid4())
    headers = {"X-Worker-Token": server.TOKEN}
    gateway.post("/files/select", json={"project_id": pid}, headers=headers)
    result = gateway.post(
        "/files/export",
        headers=headers,
        json={
            "project_id": pid,
            "content": "1\n00:00:00,000 --> 00:00:01,000\nHola\n",
            "language": "es",
            "format": "srt",
        },
    )
    assert result.status_code == 200
    assert result.json()["filename"] == "Movie.es (1).srt"
    assert (tmp_path / result.json()["filename"]).read_text().endswith("Hola\n")
    assert (
        existing.read_text() == "existing subtitle" and source.read_bytes() == b"video"
    )


def test_audio_preview_uses_chosen_track_and_validates_it(
    gateway, monkeypatch, tmp_path
):
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"video")
    monkeypatch.setattr(server, "choose_local_file", lambda: source)
    monkeypatch.setattr(
        server,
        "discover_audio",
        lambda p: [{"index": 1, "label": "English"}, {"index": 2, "label": "Spanish"}],
    )
    pid = str(uuid.uuid4())
    headers = {"X-Worker-Token": server.TOKEN}
    assert (
        gateway.post(
            "/files/select", json={"project_id": pid}, headers=headers
        ).status_code
        == 200
    )
    seen = []
    monkeypatch.setattr(
        server,
        "audio_preview",
        lambda path, index, start: seen.append((path, index, start)) or b"mp3-content",
        raising=False,
    )
    response = gateway.get(
        f"/files/{pid}/audio-preview?index=2&start=12.5", headers=headers
    )
    assert response.status_code == 200 and response.content == b"mp3-content"
    assert seen == [(source, 2, 12.5)]
    assert (
        gateway.get(
            f"/files/{pid}/audio-preview?index=99&start=0", headers=headers
        ).status_code
        == 400
    )
    assert (
        gateway.get(
            f"/files/{pid}/audio-preview?index=2&start=nan", headers=headers
        ).status_code
        == 422
    )


def test_stream_audio_checks_track_and_streams_from_requested_time(
    gateway, monkeypatch, tmp_path
):
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"video")
    monkeypatch.setattr(server, "choose_local_file", lambda: source)
    monkeypatch.setattr(
        server, "discover_audio", lambda p: [{"index": 2, "label": "Spanish"}]
    )
    pid = str(uuid.uuid4())
    headers = {"X-Worker-Token": server.TOKEN}
    assert (
        gateway.post(
            "/files/select", json={"project_id": pid}, headers=headers
        ).status_code
        == 200
    )
    seen = []
    monkeypatch.setattr(
        server,
        "stream_audio",
        lambda path, index, start: seen.append((path, index, start))
        or iter([b"mp3-a", b"mp3-b"]),
        raising=False,
    )
    response = gateway.get(
        f"/files/{pid}/audio-stream?index=2&start=42.5", headers=headers
    )
    assert response.status_code == 200 and response.content == b"mp3-amp3-b"
    assert seen == [(source, 2, 42.5)]
    assert (
        gateway.get(f"/files/{pid}/audio-stream?index=3", headers=headers).status_code
        == 400
    )


def test_sync_uses_selected_audio_without_writing_original(gateway, monkeypatch, tmp_path):
    source = tmp_path / 'video.mkv'
    source.write_bytes(b'original video')
    pid = str(uuid.uuid4())
    monkeypatch.setattr(server, 'resolve_source', lambda value: source)
    monkeypatch.setattr(server, 'load_reference', lambda folder: {'audio_tracks': [{'index': 1}, {'index': 3}]})
    seen = []
    def fake_run(args, **kwargs):
        seen.append(args)
        output = args[args.index('-o') + 1]
        from pathlib import Path
        Path(output).write_text('1\n00:00:02,000 --> 00:00:03,000\nHola\n')
        return SimpleNamespace(returncode=0, stderr='')
    from types import SimpleNamespace
    monkeypatch.setattr(server.subprocess, 'run', fake_run)
    response = gateway.post('/files/sync-subtitles', headers={'X-Worker-Token': server.TOKEN}, json={'project_id': pid, 'audio_index': 3, 'srt': '1\n00:00:01,000 --> 00:00:02,000\nHola\n'})
    assert response.status_code == 200
    assert '00:00:02,000' in response.json()['srt']
    assert seen[0][seen[0].index('--reference-stream') + 1] == '0:a:1'
    assert source.read_bytes() == b'original video'
