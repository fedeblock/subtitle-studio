import pytest
import time
from sqlalchemy import select
from app import worker
from app.core import SessionLocal, Project, Cue


def test_repeat_flag_uses_normalized_text_and_repeated_phrases():
    assert worker.repeated_text("Hola, mundo!", "hola mundo")
    assert worker.repeated_text("", "vamos a casa vamos a casa")
    assert not worker.repeated_text("Sí", "Sí, claro")
    assert not worker.repeated_text("", "sí sí")


def test_translation_worker_uses_recipe_language_and_model(client, monkeypatch):
    import json
    from pathlib import Path
    from app.core import DATA

    pid = "recipe-project"
    folder = Path(DATA) / pid
    folder.mkdir(parents=True)
    (folder / "source.json").write_text(
        json.dumps(
            {
                "action": "translate",
                "target_language": "Romanian",
                "translation_model": "local-model",
            }
        )
    )
    with SessionLocal() as db:
        db.add(
            Project(
                id=pid, name="clip", filename="source.json", state="queued", created=0
            )
        )
        db.add(
            Cue(
                id="r",
                project_id=pid,
                position=0,
                start=0,
                end=1,
                original="Hello",
                translated="",
            )
        )
        db.commit()
    sent = []
    monkeypatch.setattr(
        worker,
        "mac_post",
        lambda path, payload, **kw: sent.append(payload) or {"texts": ["Bună"]},
    )
    worker.process_project(pid)
    assert sent[0]["target_language"] == "Romanian"
    assert sent[0]["model"] == "local-model"


def test_batch_imports_matching_subtitle_then_translates_without_copying_source(
    client, monkeypatch
):
    import json
    from pathlib import Path
    from app.core import DATA, Recipe, Batch, BatchItem

    pid = "batch-ep"
    folder = Path(DATA) / pid
    folder.mkdir(parents=True)
    source = {
        "path": "/selected/video.mkv",
        "subtitles": [
            {"id": "wrong", "kind": "file", "supported": True, "match": False},
            {
                "id": "right",
                "kind": "file",
                "supported": True,
                "match": True,
                "recommended": True,
            },
        ],
        "audio_tracks": [],
    }
    (folder / "source.json").write_text(json.dumps(source))
    config = {
        "source_pref": "recommended",
        "asr_model": "qwen",
        "asr_language": None,
        "target_language": "Spanish",
        "translation_model": "model-a",
        "improve_before_translate": False,
        "flag_suspicious": True,
        "export_when_clean": False,
    }
    with SessionLocal() as db:
        db.add(Recipe(id="r", config=json.dumps(config), created=0))
        db.add(
            Project(
                id=pid,
                name="episode.mkv",
                filename="source.json",
                state="draft",
                created=0,
            )
        )
        db.add(
            Batch(
                id="batch",
                recipe_id="r",
                recipe=json.dumps(config),
                paused=0,
                created=0,
            )
        )
        db.flush()
        db.add(
            BatchItem(
                id="item",
                batch_id="batch",
                project_id=pid,
                position=0,
                status="queued",
                stage="source",
                error="",
            )
        )
        db.commit()
    seen = []

    def native(path, payload, **kwargs):
        seen.append((path, payload))
        if path == "/files/subtitle":
            return {"srt": "1\n00:00:01,000 --> 00:00:02,000\nHello\n"}
        if path == "/translate":
            return {"texts": ["Hola"]}
        raise AssertionError(path)

    monkeypatch.setattr(worker, "mac_post", native)
    worker.process_batch_item("item")
    assert seen[0][1]["subtitle_id"] == "right"
    assert seen[1][1]["model"] == "model-a"
    with SessionLocal() as db:
        assert db.get(BatchItem, "item").status == "done"
        cue = db.scalar(select(Cue).where(Cue.project_id == pid))
        assert (cue.original, cue.translated) == ("Hello", "Hola")
    assert (
        json.loads((folder / "source.json").read_text())["path"]
        == "/selected/video.mkv"
    )


def test_batch_waits_for_improvement_proposals_before_translation(client, monkeypatch):
    import json
    from pathlib import Path
    from app.core import DATA, Recipe, Batch, BatchItem, CueReview

    pid = "batch-review"
    folder = Path(DATA) / pid
    folder.mkdir(parents=True)
    (folder / "source.json").write_text(
        json.dumps(
            {
                "path": "/selected/video.mkv",
                "subtitles": [{"id": "s", "supported": True, "match": True}],
                "audio_tracks": [],
            }
        )
    )
    config = {
        "source_pref": "recommended",
        "asr_model": "qwen",
        "target_language": "Spanish",
        "translation_model": "model-a",
        "improve_before_translate": True,
        "flag_suspicious": True,
        "export_when_clean": False,
    }
    with SessionLocal() as db:
        db.add(Recipe(id="r", config=json.dumps(config), created=0))
        db.add(
            Project(
                id=pid,
                name="clip",
                filename="source.json",
                state="batch_queued",
                created=0,
            )
        )
        db.add(
            Batch(
                id="batch",
                recipe_id="r",
                recipe=json.dumps(config),
                paused=0,
                created=0,
            )
        )
        db.flush()
        db.add(
            BatchItem(
                id="item",
                batch_id="batch",
                project_id=pid,
                position=0,
                status="queued",
                stage="source",
                error="",
            )
        )
        db.commit()
    seen = []

    def native(path, payload, **kwargs):
        seen.append(path)
        if path == "/files/subtitle":
            return {"srt": "1\n00:00:01,000 --> 00:00:02,000\nhello\n"}
        if path == "/improve":
            return {"texts": ["Hello."]}
        if path == "/translate":
            return {"texts": ["Hola."]}
        raise AssertionError(path)

    monkeypatch.setattr(worker, "mac_post", native)
    worker.process_batch_item("item")
    with SessionLocal() as db:
        item = db.get(BatchItem, "item")
        cue = db.scalar(select(Cue).where(Cue.project_id == pid))
        review = db.get(CueReview, cue.id)
        assert (item.status, item.stage) == ("review", "review")
        assert cue.original == "hello" and review.proposal == "Hello."
        cue.original = review.proposal
        review.proposal = review.proposal_source = None
        item.status = "queued"
        db.commit()
    assert "/translate" not in seen
    worker.process_batch_item("item")
    with SessionLocal() as db:
        assert db.get(BatchItem, "item").status == "done"
        assert db.scalar(select(Cue).where(Cue.project_id == pid)).translated == "Hola."


def test_pausing_batch_waits_for_current_chunk_and_resumes_it(client, monkeypatch):
    import json
    from pathlib import Path
    from threading import Event, Thread
    from app.core import DATA, Recipe, Batch, BatchItem

    pid = "batch-pausing"
    folder = Path(DATA) / pid
    folder.mkdir(parents=True)
    (folder / "source.json").write_text(
        json.dumps({"path": "/selected/video.mkv", "subtitles": [], "audio_tracks": []})
    )
    config = {
        "source_pref": "asr",
        "asr_model": "qwen",
        "target_language": "Spanish",
        "translation_model": "model-a",
        "improve_before_translate": False,
        "flag_suspicious": True,
        "export_when_clean": False,
    }
    with SessionLocal() as db:
        db.add(Recipe(id="r", config=json.dumps(config), created=0))
        db.add(
            Project(
                id=pid,
                name="clip",
                filename="source.json",
                state="batch_queued",
                created=0,
            )
        )
        db.add(
            Batch(
                id="batch",
                recipe_id="r",
                recipe=json.dumps(config),
                paused=0,
                created=0,
            )
        )
        db.flush()
        db.add(
            BatchItem(
                id="item",
                batch_id="batch",
                project_id=pid,
                position=0,
                status="queued",
                stage="source",
                error="",
            )
        )
        db.commit()
    started, release = Event(), Event()

    def native(path, payload, **kwargs):
        if path == "/transcribe-chunk":
            started.set()
            assert release.wait(5)
            return {
                "srt": "1\n00:00:01,000 --> 00:00:02,000\nHello\n",
                "end_of_audio": True,
            }
        if path == "/translate":
            return {"texts": ["Hola"]}
        raise AssertionError(path)

    monkeypatch.setattr(worker, "mac_post", native)
    monkeypatch.setattr(
        "app.main.queue", lambda: type("Q", (), {"enqueue": lambda *a, **kw: None})()
    )
    thread = Thread(target=worker.process_batch_item, args=("item",))
    thread.start()
    assert started.wait(5)
    try:
        assert (
            client.post(
                "/api/batches/batch/pause", headers={"X-Studio-Local": "1"}
            ).status_code
            == 200
        )
    finally:
        release.set()
        thread.join(10)
    assert not thread.is_alive()
    with SessionLocal() as db:
        assert db.get(BatchItem, "item").status == "paused"
        assert db.get(Project, pid).state == "paused"
        assert len(db.scalars(select(Cue).where(Cue.project_id == pid)).all()) == 1
    assert (
        client.post(
            "/api/batches/batch/resume", headers={"X-Studio-Local": "1"}
        ).status_code
        == 200
    )
    worker.process_batch_item("item")
    with SessionLocal() as db:
        assert db.get(BatchItem, "item").status == "done"
        assert db.scalar(select(Cue).where(Cue.project_id == pid)).translated == "Hola"


def test_incremental_transcription_saves_repeat_flags(client, monkeypatch):
    import json
    from pathlib import Path
    from app.core import DATA, CueReview

    pid = "repeat-project"
    folder = Path(DATA) / pid
    folder.mkdir(parents=True)
    (folder / "source.json").write_text(
        json.dumps({"selected_source": "asr", "action": "edit"})
    )
    with SessionLocal() as db:
        db.add(
            Project(
                id=pid, name="clip", filename="source.json", state="queued", created=0
            )
        )
        db.commit()
    monkeypatch.setattr(
        worker,
        "mac_post",
        lambda *args, **kwargs: {
            "srt": "1\n00:00:01,000 --> 00:00:02,000\nHola mundo\n\n2\n00:00:03,000 --> 00:00:04,000\nHola, mundo!\n",
            "end_of_audio": True,
        },
    )
    worker.process_project(pid)
    with SessionLocal() as db:
        cues = db.scalars(
            select(Cue).where(Cue.project_id == pid).order_by(Cue.position)
        ).all()
        assert len(cues) == 2
        assert db.get(CueReview, cues[0].id) is None
        assert db.get(CueReview, cues[1].id).flag == "repeat"


def test_incremental_transcription_keeps_native_review_flags(client, monkeypatch):
    import json
    from pathlib import Path
    from app.core import DATA, CueReview

    pid = "flagged-project"
    folder = Path(DATA) / pid
    folder.mkdir(parents=True)
    (folder / "source.json").write_text(
        json.dumps({"selected_source": "asr", "action": "edit"})
    )
    with SessionLocal() as db:
        db.add(
            Project(
                id=pid, name="clip", filename="source.json", state="queued", created=0
            )
        )
        db.commit()
    monkeypatch.setattr(
        worker,
        "mac_post",
        lambda *a, **kw: {
            "srt": "1\n00:00:01,000 --> 00:00:02,000\nHallucination\n",
            "end_of_audio": True,
            "flags": ["silence"],
        },
    )
    worker.process_project(pid)
    with SessionLocal() as db:
        cue = db.scalar(select(Cue).where(Cue.project_id == pid))
        assert db.get(CueReview, cue.id).flag == "silence"


def test_gateway_retries_transient_failures_three_times_then_succeeds(monkeypatch):
    import requests

    calls, delays = [], []

    def post(*args, **kwargs):
        calls.append(kwargs["json"])
        if len(calls) <= 3:
            raise requests.ConnectionError("gateway unavailable")
        return type("Response", (), {"ok": True, "json": lambda self: {"srt": "ok"}})()

    monkeypatch.setattr(worker.requests, "post", post)
    monkeypatch.setattr(time, "sleep", delays.append)
    assert worker.mac_post("/transcribe-chunk", {"segment_start": 30}) == {"srt": "ok"}
    assert calls == [{"segment_start": 30}] * 4
    assert delays == [2, 4, 8]


def test_gateway_exhausted_retries_reports_final_error(monkeypatch):
    import requests

    calls = []

    def post(*args, **kwargs):
        calls.append(1)
        raise requests.Timeout("timeout")

    monkeypatch.setattr(worker.requests, "post", post)
    monkeypatch.setattr(time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="3 reintentos"):
        worker.mac_post("/transcribe-chunk", {})
    assert len(calls) == 4


def test_gateway_checks_for_pause_before_retrying(monkeypatch):
    import requests

    calls = []

    def post(*a, **kw):
        calls.append(1)
        raise requests.ConnectionError("temporary")

    checks = []

    def stop():
        checks.append(1)
        if len(checks) == 2:
            raise worker.TaskStopped()

    monkeypatch.setattr(worker.requests, "post", post)
    with pytest.raises(worker.TaskStopped):
        worker.mac_post("/improve", {}, should_stop=stop)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "status,attempts", [(400, 1), (401, 1), (429, 4), (502, 4), (503, 4)]
)
def test_gateway_retries_only_transient_http_responses(monkeypatch, status, attempts):
    calls = []

    class Response:
        ok = False
        status_code = status
        reason = "failure"

        def json(self):
            return {"detail": "failure"}

        def close(self):
            pass

    monkeypatch.setattr(
        worker.requests, "post", lambda *a, **kw: calls.append(1) or Response()
    )
    monkeypatch.setattr(time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError):
        worker.mac_post("/transcribe-chunk", {})
    assert len(calls) == attempts


def test_worker_keeps_completed_translation_batches(client, monkeypatch):
    with SessionLocal() as db:
        db.add(
            Project(
                id="p", name="clip", filename="source.wav", state="queued", created=0
            )
        )
        db.commit()
    srt = "\n\n".join(
        f"{i + 1}\n00:00:{i:02},000 --> 00:00:{i + 1:02},000\nLine {i}"
        for i in range(7)
    )

    def gateway(path, json, **kwargs):
        if path == "/transcribe":
            return {"srt": srt, "language": "English"}
        if len(json["texts"]) == 6:
            return {"texts": [f"Línea {i}" for i in range(6)]}
        raise RuntimeError("Ollama unavailable")

    monkeypatch.setattr(worker, "mac_post", gateway)
    with pytest.raises(RuntimeError):
        worker.process_project("p")
    with SessionLocal() as db:
        cues = db.scalars(select(Cue).order_by(Cue.position)).all()
        assert len(cues) == 7
        assert cues[0].translated == "Línea 0"
        assert db.get(Project, "p").state == "failed"
        assert db.get(Project, "p").language == "English"


def test_duplicate_job_does_not_replace_user_edits(client, monkeypatch):
    with SessionLocal() as db:
        db.add(
            Project(
                id="p", name="clip", filename="source.wav", state="ready", created=0
            )
        )
        db.add(
            Cue(
                id="c",
                project_id="p",
                position=0,
                start=0,
                end=1,
                original="User edit",
                translated="Edición",
            )
        )
        db.commit()
    calls = []

    def gateway(*args, **kwargs):
        calls.append(args)
        raise RuntimeError("Should not transcribe a completed project")

    monkeypatch.setattr(worker, "mac_post", gateway)
    worker.process_project("p")
    assert calls == []
    with SessionLocal() as db:
        assert db.get(Cue, "c").original == "User edit"
        assert db.get(Project, "p").state == "ready"


def test_retry_preserves_existing_text_and_translates_only_pending(client, monkeypatch):
    with SessionLocal() as db:
        db.add(
            Project(
                id="p", name="clip", filename="source.wav", state="queued", created=0
            )
        )
        db.add(
            Cue(
                id="saved",
                project_id="p",
                position=0,
                start=0,
                end=1,
                original="Edited original",
                translated="Mi edición",
            )
        )
        db.add(
            Cue(
                id="pending",
                project_id="p",
                position=1,
                start=1,
                end=2,
                original="Pending",
                translated="",
            )
        )
        db.commit()

    def gateway(path, json, **kwargs):
        assert path == "/translate"
        assert json["texts"] == ["Pending"]
        return {"texts": ["Pendiente"]}

    monkeypatch.setattr(worker, "mac_post", gateway)
    worker.process_project("p")
    with SessionLocal() as db:
        assert db.get(Cue, "saved").translated == "Mi edición"
        assert db.get(Cue, "saved").original == "Edited original"
        assert db.get(Cue, "pending").translated == "Pendiente"
        assert db.get(Project, "p").state == "ready"


def test_asr_edit_mode_does_not_call_translation(client, monkeypatch):
    import json
    from pathlib import Path
    from app.core import DATA

    folder = Path(DATA) / "edit-project"
    folder.mkdir(parents=True)
    (folder / "source.json").write_text(json.dumps({"action": "edit"}))
    with SessionLocal() as db:
        db.add(
            Project(
                id="edit-project",
                name="clip",
                filename="source.json",
                state="queued",
                created=0,
            )
        )
        db.commit()

    def native(path, json, **kwargs):
        assert path == "/transcribe"
        return {"srt": "1\n00:00:00,000 --> 00:00:01,000\nHello\n"}

    monkeypatch.setattr(worker, "mac_post", native)
    worker.process_project("edit-project")
    with SessionLocal() as db:
        assert db.get(Project, "edit-project").state == "ready"


def test_incremental_asr_persists_chunks_and_resumes_without_duplicates(
    client, monkeypatch
):
    import json
    from pathlib import Path
    from app.core import DATA, TranscriptionProgress

    pid = "incremental-project"
    folder = Path(DATA) / pid
    folder.mkdir(parents=True)
    (folder / "source.json").write_text(
        json.dumps(
            {
                "selected_source": "asr",
                "action": "edit",
                "asr_language": "Romanian",
                "asr_model": "whisper",
            }
        )
    )
    with SessionLocal() as db:
        db.add(
            Project(
                id=pid, name="clip", filename="source.json", state="queued", created=0
            )
        )
        db.commit()
    calls = []

    def first_pass(path, payload, **kwargs):
        assert payload["language"] == "Romanian"
        assert payload["model"] == "whisper"
        calls.append(payload["segment_start"])
        if payload["segment_start"] == 0:
            return {
                "srt": "1\n00:00:01,000 --> 00:00:02,000\nFirst\n",
                "language": "English",
                "end_of_audio": False,
                "estimated_timing": True,
            }
        with SessionLocal() as db:
            assert (
                db.scalars(select(Cue).where(Cue.project_id == pid)).first().original
                == "First"
            )
        raise RuntimeError("temporary failure")

    monkeypatch.setattr(worker, "mac_post", first_pass)
    with pytest.raises(RuntimeError):
        worker.process_project(pid)
    with SessionLocal() as db:
        assert db.get(TranscriptionProgress, pid).next_start == 30
        db.scalars(
            select(Cue).where(Cue.project_id == pid)
        ).first().original = "First corrected"
        db.get(Project, pid).state = "queued"
        db.commit()

    def retry(path, payload, **kwargs):
        assert payload["language"] == "Romanian"
        assert payload["model"] == "whisper"
        calls.append(payload["segment_start"])
        return {
            "srt": "1\n00:00:31,000 --> 00:00:32,000\nSecond\n",
            "language": "English",
            "end_of_audio": True,
        }

    monkeypatch.setattr(worker, "mac_post", retry)
    worker.process_project(pid)
    with SessionLocal() as db:
        cues = db.scalars(
            select(Cue).where(Cue.project_id == pid).order_by(Cue.position)
        ).all()
        assert [c.original for c in cues] == ["First corrected", "Second"]
        assert db.get(Project, pid).state == "ready"
        assert db.get(TranscriptionProgress, pid).completed
    assert calls == [0, 30, 30]
    from app.project_sources import reference

    assert reference(pid)["timing_warnings"] == [0]


def test_transcription_recovers_from_three_network_failures_without_duplicate_cues(
    client, monkeypatch
):
    import json
    from pathlib import Path
    import requests
    from app.core import DATA, TranscriptionProgress

    pid = "retry-incremental"
    folder = Path(DATA) / pid
    folder.mkdir(parents=True)
    (folder / "source.json").write_text(
        json.dumps({"selected_source": "asr", "action": "edit"})
    )
    with SessionLocal() as db:
        db.add(
            Project(
                id=pid, name="clip", filename="source.json", state="queued", created=0
            )
        )
        db.commit()
    calls = []

    def post(url, **kwargs):
        start = kwargs["json"]["segment_start"]
        calls.append(start)
        if start == 30 and calls.count(30) <= 3:
            raise requests.ConnectionError("temporary outage")
        data = {
            "srt": f"1\n00:00:{start + 1:02},000 --> 00:00:{start + 2:02},000\nSegment {start}\n",
            "end_of_audio": start == 30,
        }
        return type("Response", (), {"ok": True, "json": lambda self: data})()

    monkeypatch.setattr(worker.requests, "post", post)
    monkeypatch.setattr(time, "sleep", lambda _: None)
    worker.process_project(pid)
    with SessionLocal() as db:
        cues = db.scalars(
            select(Cue).where(Cue.project_id == pid).order_by(Cue.position)
        ).all()
        assert [cue.original for cue in cues] == ["Segment 0", "Segment 30"]
        assert db.get(Project, pid).state == "ready"
        assert db.get(TranscriptionProgress, pid).completed
    assert calls == [0, 30, 30, 30, 30]


def test_pause_transcription_saves_current_chunk_and_can_resume(client, monkeypatch):
    import json
    from pathlib import Path
    from app.core import DATA, TranscriptionProgress
    from app import main

    pid = "pause-transcription"
    folder = Path(DATA) / pid
    folder.mkdir(parents=True)
    (folder / "source.json").write_text(
        json.dumps({"selected_source": "asr", "action": "edit"})
    )
    with SessionLocal() as db:
        db.add(
            Project(
                id=pid, name="clip", filename="source.json", state="queued", created=0
            )
        )
        db.commit()
    calls = []

    def native(path, payload, **kwargs):
        start = payload["segment_start"]
        calls.append(start)
        if start == 0:
            assert (
                client.post(
                    f"/api/projects/{pid}/pause", headers={"X-Studio-Local": "1"}
                ).status_code
                == 200
            )
        return {
            "srt": f"1\n00:00:{start + 1:02},000 --> 00:00:{start + 2:02},000\ntext {start}\n",
            "end_of_audio": start == 30,
        }

    monkeypatch.setattr(worker, "mac_post", native)
    worker.process_project(pid)
    with SessionLocal() as db:
        assert db.get(Project, pid).state == "paused"
        assert db.get(TranscriptionProgress, pid).next_start == 30
    monkeypatch.setattr(
        main, "queue", lambda: type("Q", (), {"enqueue": lambda *a, **kw: None})()
    )
    assert (
        client.post(
            f"/api/projects/{pid}/resume", headers={"X-Studio-Local": "1"}
        ).status_code
        == 200
    )
    worker.process_project(pid)
    with SessionLocal() as db:
        cues = db.scalars(
            select(Cue).where(Cue.project_id == pid).order_by(Cue.position)
        ).all()
        assert [c.original for c in cues] == ["text 0", "text 30"]
        assert db.get(Project, pid).state == "ready"


def test_pause_translation_saves_current_batch_and_resumes_pending(client, monkeypatch):
    from app import main
    from types import SimpleNamespace

    pid = "pause-translation"
    with SessionLocal() as db:
        db.add(
            Project(
                id=pid, name="clip", filename="source.wav", state="queued", created=0
            )
        )
        for i in range(7):
            db.add(
                Cue(
                    id=f"p{i}",
                    project_id=pid,
                    position=i,
                    start=i,
                    end=i + 1,
                    original=f"text {i}",
                    translated="",
                )
            )
        db.commit()
    calls = []

    def infer(path, payload, **kwargs):
        calls.append(payload["texts"])
        if len(calls) == 1:
            assert (
                client.post(
                    f"/api/projects/{pid}/pause", headers={"X-Studio-Local": "1"}
                ).status_code
                == 200
            )
        return {"texts": [f"translated {text}" for text in payload["texts"]]}

    monkeypatch.setattr(worker, "mac_post", infer)
    worker.process_project(pid)
    with SessionLocal() as db:
        assert db.get(Project, pid).state == "paused"
        cues = db.scalars(
            select(Cue).where(Cue.project_id == pid).order_by(Cue.position)
        ).all()
        assert sum(bool(c.translated) for c in cues) == 6
    monkeypatch.setattr(
        main, "queue", lambda: SimpleNamespace(enqueue=lambda *a, **kw: None)
    )
    assert (
        client.post(
            f"/api/projects/{pid}/resume", headers={"X-Studio-Local": "1"}
        ).status_code
        == 200
    )
    worker.process_project(pid)
    assert calls[1] == ["text 6"]
    with SessionLocal() as db:
        assert db.get(Project, pid).state == "ready"


def test_polish_preserves_times_translation_and_can_be_restored(client, monkeypatch):
    import json
    from app import main
    from pathlib import Path
    from app.core import DATA

    pid = "polish-project"
    folder = Path(DATA) / pid
    folder.mkdir(parents=True)
    with SessionLocal() as db:
        db.add(
            Project(
                id=pid, name="clip", filename="source.wav", state="ready", created=0
            )
        )
        db.add(
            Cue(
                id="p1",
                project_id=pid,
                position=0,
                start=3,
                end=4,
                original="hello world",
                translated="Hola mundo",
            )
        )
        db.commit()
    monkeypatch.setattr(
        main, "queue", lambda: type("Q", (), {"enqueue": lambda *a, **kw: None})()
    )
    from types import SimpleNamespace

    monkeypatch.setattr(
        main,
        "native_request",
        lambda *a, **kw: SimpleNamespace(
            json=lambda: [{"name": "model-selected:latest"}]
        ),
    )
    response = client.post(
        f"/api/projects/{pid}/improve", json={"model": "model-selected:latest"}
    )
    assert response.status_code == 200
    calls = []
    monkeypatch.setattr(
        worker,
        "mac_post",
        lambda path, json, **kw: calls.append(json) or {"texts": ["Hello world."]},
    )
    worker.improve_project(pid, response.json()["backup"])
    with SessionLocal() as db:
        cue = db.get(Cue, "p1")
        assert (cue.start, cue.end, cue.original, cue.translated) == (
            3,
            4,
            "hello world",
            "Hola mundo",
        )
        assert db.get(Project, pid).state == "ready"
    backup = json.loads(
        (folder / f"improvement-{response.json()['backup']}.json").read_text()
    )
    assert backup["cues"][0]["before"] == "hello world"
    assert backup["model"] == "model-selected:latest"
    assert calls[0]["model"] == "model-selected:latest"
    assert (
        client.get(f"/api/projects/{pid}").json()["cues"][0]["proposal"]
        == "Hello world."
    )
    assert (
        client.post(
            f"/api/projects/{pid}/cues/p1/proposal/accept",
            headers={"X-Studio-Local": "1"},
        ).status_code
        == 200
    )
    assert client.post(f"/api/projects/{pid}/improve/undo").status_code == 200
    with SessionLocal() as db:
        assert db.get(Cue, "p1").original == "hello world"
        assert db.get(Cue, "p1").translated == "Hola mundo"


def test_polish_undo_refuses_to_overwrite_newer_edits(client, monkeypatch):
    import json
    from pathlib import Path
    from app.core import DATA

    pid = "edited-polish"
    folder = Path(DATA) / pid
    folder.mkdir(parents=True)
    (folder / "improvement-11111111-1111-4111-8111-111111111111.json").write_text(
        json.dumps(
            {
                "restored": False,
                "cues": [{"id": "p1", "before": "raw", "after": "Corrected"}],
            }
        )
    )
    with SessionLocal() as db:
        db.add(
            Project(
                id=pid, name="clip", filename="source.wav", state="ready", created=0
            )
        )
        db.add(
            Cue(
                id="p1",
                project_id=pid,
                position=0,
                start=0,
                end=1,
                original="User edit",
                translated="",
            )
        )
        db.commit()
    assert client.post(f"/api/projects/{pid}/improve/undo").status_code == 409
    with SessionLocal() as db:
        assert db.get(Cue, "p1").original == "User edit"


def test_improvement_keeps_selected_model_for_every_batch(client, monkeypatch):
    import json
    from pathlib import Path
    from app.core import DATA

    pid = "multiple-batches"
    folder = Path(DATA) / pid
    folder.mkdir(parents=True)
    backup = "11111111-1111-4111-8111-111111111111"
    (folder / f"improvement-{backup}.json").write_text(
        json.dumps(
            {
                "model": "selected:latest",
                "cues": [
                    {"id": f"c{i}", "before": f"text {i}", "after": None}
                    for i in range(7)
                ],
            }
        )
    )
    with SessionLocal() as db:
        db.add(
            Project(
                id=pid,
                name="clip",
                filename="source.wav",
                state="improve_queued",
                created=0,
            )
        )
        for i in range(7):
            db.add(
                Cue(
                    id=f"c{i}",
                    project_id=pid,
                    position=i,
                    start=i,
                    end=i + 1,
                    original=f"text {i}",
                    translated="",
                )
            )
        db.commit()
    seen = []

    def improve(path, payload, **kwargs):
        seen.append(payload["model"])
        return {"texts": [s.upper() for s in payload["texts"]]}

    monkeypatch.setattr(worker, "mac_post", improve)
    worker.improve_project(pid, backup)
    assert seen == ["selected:latest", "selected:latest"]


@pytest.mark.parametrize(
    "action,final_state", [("pause", "paused"), ("cancel", "cancelled")]
)
def test_improvement_stops_at_batch_boundary_and_preserves_undo(
    client, monkeypatch, action, final_state
):
    import json
    from pathlib import Path
    from types import SimpleNamespace
    from app import main
    from app.core import DATA

    pid = f"stop-improve-{action}"
    folder = Path(DATA) / pid
    folder.mkdir(parents=True)
    with SessionLocal() as db:
        db.add(
            Project(
                id=pid, name="clip", filename="source.wav", state="ready", created=0
            )
        )
        for i in range(7):
            db.add(
                Cue(
                    id=f"x{i}",
                    project_id=pid,
                    position=i,
                    start=i,
                    end=i + 1,
                    original=f"text {i}",
                    translated="",
                )
            )
        db.commit()
    monkeypatch.setattr(
        main, "queue", lambda: SimpleNamespace(enqueue=lambda *a, **kw: None)
    )
    backup = client.post(f"/api/projects/{pid}/improve").json()["backup"]
    calls = []

    def infer(path, payload, **kwargs):
        calls.append(payload["texts"])
        if len(calls) == 1:
            assert (
                client.post(
                    f"/api/projects/{pid}/{action}", headers={"X-Studio-Local": "1"}
                ).status_code
                == 200
            )
        return {"texts": [text.upper() for text in payload["texts"]]}

    monkeypatch.setattr(worker, "mac_post", infer)
    worker.improve_project(pid, backup)
    with SessionLocal() as db:
        assert db.get(Project, pid).state == final_state
        cues = db.scalars(
            select(Cue).where(Cue.project_id == pid).order_by(Cue.position)
        ).all()
        assert [c.original for c in cues] == [f"text {i}" for i in range(7)]
    snapshot = json.loads((folder / f"improvement-{backup}.json").read_text())
    assert sum(item["after"] is not None for item in snapshot["cues"]) == 6
    if action == "pause":
        assert (
            client.post(
                f"/api/projects/{pid}/resume", headers={"X-Studio-Local": "1"}
            ).status_code
            == 200
        )
        worker.improve_project(pid, backup)
        assert len(calls) == 2 and calls[1] == ["text 6"]
        assert client.get(f"/api/projects/{pid}").json()["project"]["state"] == "ready"
    assert client.post(f"/api/projects/{pid}/improve/undo").status_code == 200
    with SessionLocal() as db:
        assert db.get(Cue, "x0").original == "text 0"


def test_undo_partial_improvement_restores_previous_status(client, monkeypatch):
    from app import main
    from pathlib import Path
    from app.core import DATA

    pid = "failed-improvement"
    (Path(DATA) / pid).mkdir(parents=True)
    with SessionLocal() as db:
        db.add(
            Project(
                id=pid,
                name="clip",
                filename="source.wav",
                state="ready",
                progress=100,
                created=0,
            )
        )
        db.add(
            Cue(
                id="c-fail",
                project_id=pid,
                position=0,
                start=0,
                end=1,
                original="original",
                translated="",
            )
        )
        db.commit()
    monkeypatch.setattr(
        main, "queue", lambda: type("Q", (), {"enqueue": lambda *a, **kw: None})()
    )
    backup = client.post(f"/api/projects/{pid}/improve").json()["backup"]

    def fail(*args, **kwargs):
        raise RuntimeError("gateway down")

    monkeypatch.setattr(worker, "mac_post", fail)
    with pytest.raises(RuntimeError):
        worker.improve_project(pid, backup)
    assert client.get(f"/api/projects/{pid}").json()["project"]["state"] == "failed"
    assert client.post(f"/api/projects/{pid}/improve/undo").status_code == 200
    project = client.get(f"/api/projects/{pid}").json()["project"]
    assert (
        project["state"] == "ready"
        and project["error"] == ""
        and project["progress"] == 100
    )


def test_rq_child_replaces_parent_pool_before_running_job(monkeypatch):
    events = []
    monkeypatch.setattr(
        worker.engine, "dispose", lambda **kw: events.append(("dispose", kw))
    )
    monkeypatch.setattr(
        worker.Worker,
        "main_work_horse",
        lambda self, job, queue: events.append(("job", job, queue)),
    )
    instance = object.__new__(worker.ForkSafeWorker)
    instance.main_work_horse("job", "queue")
    assert events == [("dispose", {"close": False}), ("job", "job", "queue")]
