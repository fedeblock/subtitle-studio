"""Real Docker pipeline with deterministic inference stand-in; no model downloads.

Run with .venv/bin/python scripts/smoke.py. Artifacts and volumes are retained.
"""

import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import wave
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import requests

ROOT = Path(__file__).resolve().parents[1]


def main():
    artifacts = Path(tempfile.mkdtemp(prefix="subtitle-studio-smoke-"))
    project = "subtitle-studio-check-" + artifacts.name.rsplit("-", 1)[-1]
    fail_translation = [True]
    env = dict(
        os.environ,
        FRONTEND_PORT="13000",
        MAC_URL="http://host.docker.internal:18765",
        MAC_TOKEN="smoke-only-token",
        STUDIO_DATA_DIR=str(artifacts),
    )
    compose = ["docker", "compose", "-p", project]

    def docker(*args):
        return subprocess.run(
            [*compose, *args],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    class Gateway(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if self.headers.get("X-Worker-Token") != "smoke-only-token":
                self.send_error(401)
                return
            raw_body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            body = json.loads(raw_body or b"{}")
            if self.path == "/transcribe":
                assert (artifacts / body["project_id"] / "source.wav").exists()
                response = {
                    "srt": "1\n00:00:00,000 --> 00:00:01,000\nHello world.\n",
                    "language": "English",
                }
            elif self.path == "/files/select-many":
                selected = []
                for number in (1, 2):
                    pid = str(uuid.uuid4())
                    source = artifacts / f"Synthetic.S01E{number:02}.mkv"
                    source.write_bytes(b"synthetic source")
                    folder = artifacts / pid
                    folder.mkdir()
                    (folder / "source.json").write_text(json.dumps({"path":str(source),"subtitles":[{"id":"sub","kind":"file","label":f"Synthetic.S01E{number:02}.en.srt","supported":True,"match":True,"recommended":True}],"audio_tracks":[]}))
                    selected.append({"id":pid,"name":source.name,"filename":"source.json"})
                response = {"projects":selected,"errors":[]}
            elif self.path == "/files/subtitle":
                response = {"srt":"1\n00:00:00,000 --> 00:00:01,000\nHello world.\n"}
            elif self.path == "/translate":
                if fail_translation[0]:
                    fail_translation[0] = False
                    # A non-retryable failure exercises the explicit recovery path;
                    # transient 503s are retried automatically by the worker.
                    self.send_error(400, "Simulated model failure")
                    return
                response = {"texts": ["Hola mundo." for _ in body["texts"]]}
            else:
                self.send_error(404)
                return
            data = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    gateway = ThreadingHTTPServer(("0.0.0.0", 18765), Gateway)
    threading.Thread(target=gateway.serve_forever, daemon=True).start()
    print(f"Project: {project}; retained data: {artifacts}", flush=True)
    try:
        print(
            docker("up", "-d", "--build", "--wait", "--wait-timeout", "120"), flush=True
        )
        base = "http://127.0.0.1:13000"
        assert requests.get(base, timeout=5).status_code == 200
        assert requests.get(base + "/app.js", timeout=5).status_code == 200
        assert requests.get(base + "/api/health", timeout=5).status_code == 200
        audio = io.BytesIO()
        with wave.open(audio, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\0\0" * 16000)
        raw = audio.getvalue()
        upload = requests.post(
            base + "/api/projects",
            files={"file": ("smoke.wav", raw, "audio/wav")},
            timeout=10,
        )
        upload.raise_for_status()
        pid = upload.json()["id"]
        for _ in range(60):
            response = requests.get(f"{base}/api/projects/{pid}", timeout=5)
            response.raise_for_status()
            detail = response.json()
            if detail["project"]["state"] in ("ready", "failed"):
                break
            time.sleep(1)
        assert detail["project"]["state"] == "failed", detail
        retry = requests.post(f"{base}/api/projects/{pid}/retry", timeout=5)
        retry.raise_for_status()
        for _ in range(60):
            detail = requests.get(f"{base}/api/projects/{pid}", timeout=5).json()
            if detail["project"]["state"] in ("ready", "failed"):
                break
            time.sleep(1)
        assert detail["project"]["state"] == "ready", detail
        assert detail["project"]["language"] == "English"
        cue = detail["cues"][0]
        assert cue["translated"] == "Hola mundo."
        body = {key: cue[key] for key in ["start", "end", "original", "translated"]}
        body["translated"] = "Hola, mundo editado."
        edited = requests.put(
            f"{base}/api/projects/{pid}/cues/{cue['id']}", json=body, timeout=5
        )
        edited.raise_for_status()
        assert (
            "Hola, mundo editado."
            in requests.get(f"{base}/api/projects/{pid}/export", timeout=5).text
        )
        vtt = requests.get(
            f"{base}/api/projects/{pid}/export?language=original&format=vtt", timeout=5
        ).text
        assert vtt.startswith("WEBVTT") and "Hello world." in vtt
        media = requests.get(
            f"{base}/api/projects/{pid}/media",
            headers={"Range": "bytes=0-15"},
            timeout=5,
        )
        assert media.status_code == 206 and media.content == raw[:16]
        empty = requests.post(
            base + "/api/projects",
            files={"file": ("empty.wav", b"", "audio/wav")},
            timeout=5,
        )
        assert empty.status_code == 400
        docker("exec", "-T", "redis", "redis-cli", "SET", "studio:smoke", "persistent")
        docker("restart", "db", "redis")
        docker("up", "-d", "--wait", "--wait-timeout", "120")
        assert "persistent" in docker(
            "exec", "-T", "redis", "redis-cli", "GET", "studio:smoke"
        )
        assert (
            requests.get(f"{base}/api/projects/{pid}", timeout=5).json()["cues"][0][
                "translated"
            ]
            == "Hola, mundo editado."
        )
        local = {"X-Studio-Local":"1"}
        selected = requests.post(base + "/api/projects/local-many", headers=local, timeout=10)
        selected.raise_for_status()
        ids = [item["id"] for item in selected.json()["projects"]]
        recipe = requests.post(base + "/api/recipes", headers=local, json={"name":"Prueba","translation_model":"mock-model"}, timeout=5)
        recipe.raise_for_status()
        batch = requests.post(base + "/api/batches", headers=local, json={"recipe_id":recipe.json()["id"],"project_ids":ids}, timeout=5)
        batch.raise_for_status()
        batch_id = batch.json()["id"]
        for _ in range(60):
            batch_state = requests.get(f"{base}/api/batches/{batch_id}",timeout=5).json()
            if all(item["status"] in ("done","failed","review") for item in batch_state["items"]):
                break
            time.sleep(1)
        assert all(item["status"] == "done" for item in batch_state["items"]), batch_state
        for project_id in ids:
            detail = requests.get(f"{base}/api/projects/{project_id}",timeout=5).json()
            assert detail["cues"][0]["translated"] == "Hola mundo."
            assert [p.name for p in (artifacts/project_id).iterdir()] == ["source.json"]
        print(docker("ps"), flush=True)
        print(
            f"PASS: upload → RQ → gateway stand-in → PostgreSQL → edit → SRT/VTT; media range; DB/Redis restart; two-item local batch. Project {pid}",
            flush=True,
        )
    except Exception:
        print(docker("logs", "--tail", "60"), flush=True)
        raise
    finally:
        gateway.shutdown()
        gateway.server_close()
        if os.environ.get("STUDIO_SMOKE_KEEP_RUNNING") == "1":
            print(f"Containers retained for UI inspection: {project}", flush=True)
        else:
            print(docker("stop"), flush=True)
            print(
                "Stopped only smoke containers. No volumes or data deleted.", flush=True
            )


if __name__ == "__main__":
    main()
