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
