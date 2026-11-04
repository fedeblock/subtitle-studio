import pytest
from sqlalchemy import select
from app import worker
from app.core import SessionLocal, Project, Cue


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
    response = client.post(f"/api/projects/{pid}/improve")
    assert response.status_code == 200
    monkeypatch.setattr(
        worker, "mac_post", lambda path, json, **kw: {"texts": ["Hello world."]}
    )
    worker.improve_project(pid, response.json()["backup"])
    with SessionLocal() as db:
        cue = db.get(Cue, "p1")
        assert (cue.start, cue.end, cue.original, cue.translated) == (
            3,
            4,
            "Hello world.",
            "Hola mundo",
        )
        assert db.get(Project, pid).state == "ready"
    backup = json.loads(
        (folder / f"improvement-{response.json()['backup']}.json").read_text()
    )
    assert backup["cues"][0]["before"] == "hello world"
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
