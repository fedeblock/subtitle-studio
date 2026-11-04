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
