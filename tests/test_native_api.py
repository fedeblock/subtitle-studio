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


def test_multiple_local_selection_creates_drafts_without_copying(client, monkeypatch):
    selected = [
        {"id": str(uuid.uuid4()), "name": "S01E01.mkv", "filename": "source.json"},
        {"id": str(uuid.uuid4()), "name": "S01E02.mkv", "filename": "source.json"},
    ]
    monkeypatch.setattr(
        main,
        "native_request",
        lambda *args, **kwargs: SimpleNamespace(
            status_code=200, json=lambda: {"projects": selected, "errors": []}
        ),
    )
    assert client.post("/api/projects/local-many").status_code == 403
    response = client.post("/api/projects/local-many", headers={"X-Studio-Local": "1"})
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["projects"]] == [
        item["id"] for item in selected
    ]
    with SessionLocal() as db:
        assert all(db.get(Project, item["id"]).state == "draft" for item in selected)
        assert all(
            db.get(Project, item["id"]).filename == "source.json" for item in selected
        )


def test_envelope_uses_selected_track_and_validates_range(client, monkeypatch):
    pid = local_project()
    path = Path(main.DATA) / pid / "source.json"
    info = json.loads(path.read_text())
    info.update(audio_tracks=[{"index": 2}, {"index": 3}], audio_index=3)
    path.write_text(json.dumps(info))
    calls = []

    def native(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return SimpleNamespace(json=lambda: {"amplitudes": [0.1, 0.2]})

    monkeypatch.setattr(main, "native_request", native)
    response = client.get(f"/api/projects/{pid}/envelope?start=2&end=4&buckets=2")
    assert response.json() == {"amplitudes": [0.1, 0.2]}
    assert calls[0][2]["params"] == {"index": 3, "start": 2, "end": 4, "buckets": 2}
    assert client.get(f"/api/projects/{pid}/envelope?start=4&end=2").status_code == 422
    assert (
        client.get(f"/api/projects/{pid}/envelope?start=0&end=4&index=2").status_code
        == 200
    )
    assert calls[-1][2]["params"]["index"] == 2
    assert (
        client.get(f"/api/projects/{pid}/envelope?start=0&end=4&index=99").status_code
        == 409
    )


def test_delete_reviewed_cue_rejects_stale_content(client):
    from app.core import Cue

    pid = local_project()
    with SessionLocal() as db:
        db.get(Project, pid).state = "ready"
        db.add(
            Cue(
                id="delete-test",
                project_id=pid,
                position=0,
                start=1,
                end=2,
                original="Texto actual",
                translated="",
            )
        )
        db.commit()
    route = f"/api/projects/{pid}/cues/delete-test"
    headers = {"X-Studio-Local": "1"}
    stale = {"start": 1, "end": 2, "original": "Texto antiguo", "translated": ""}
    assert (
        client.request(
            "DELETE", route, headers=headers, json={"expected": stale}
        ).status_code
        == 409
    )
    with SessionLocal() as db:
        assert db.get(Cue, "delete-test").original == "Texto actual"

    stale["original"] = "Texto actual"
    deleted = client.request("DELETE", route, headers=headers, json={"expected": stale})
    assert deleted.status_code == 200
    assert (
        client.post(
            f"/api/projects/{pid}/comparisons/{deleted.json()['undo_id']}/undo",
            headers=headers,
        ).status_code
        == 200
    )
    with SessionLocal() as db:
        assert db.get(Cue, "delete-test").original == "Texto actual"


def test_new_improvement_does_not_overwrite_pending_proposals(client, monkeypatch):
    from app.core import Cue, CueReview
    pid=local_project()
    with SessionLocal() as db:
        db.get(Project,pid).state='ready'
        db.add(Cue(id='c',project_id=pid,position=0,start=0,end=1,original='hello',translated=''))
        db.add(CueReview(cue_id='c',proposal='Hello.',proposal_source='hello'))
        db.commit()
    monkeypatch.setattr(main,'queue',lambda:SimpleNamespace(enqueue=lambda *a,**kw:None))
    assert client.post(f'/api/projects/{pid}/improve').status_code == 409
    with SessionLocal() as db:
        assert db.get(CueReview,'c').proposal == 'Hello.'


def test_translation_comparison_range_is_aligned_and_does_not_modify_cues(
    client, monkeypatch
):
    from app.core import Cue

    pid = local_project()
    with SessionLocal() as db:
        db.get(Project, pid).state = "ready"
        db.add_all(
            [
                Cue(
                    id="r1",
                    project_id=pid,
                    position=0,
                    start=0,
                    end=1,
                    original="Hello",
                    translated="Hola",
                ),
                Cue(
                    id="r2",
                    project_id=pid,
                    position=1,
                    start=1,
                    end=2,
                    original="World",
                    translated="",
                ),
            ]
        )
        db.commit()

    def native(method, url, **kwargs):
        assert url == "/compare-translations-range"
        assert kwargs["json"]["texts"] == ["Hello", "World"]
        return SimpleNamespace(
            json=lambda: {
                "results": [
                    {"model": "a", "texts": ["Hola", "Mundo"]},
                    {"model": "b", "texts": ["Buenas", "Mundo"]},
                ]
            }
        )

    monkeypatch.setattr(main, "native_request", native)
    response = client.post(
        f"/api/projects/{pid}/compare-translations",
        headers={"X-Studio-Local": "1"},
        json={
            "cue_ids": ["r1", "r2"],
            "direction": "forward",
            "target_language": "Spanish",
            "models": ["a", "b"],
        },
    )
    assert response.status_code == 200
    assert [row["cue_id"] for row in response.json()["cues"]] == ["r1", "r2"]
    assert response.json()["results"][0]["texts"] == ["Hola", "Mundo"]
    with SessionLocal() as db:
        assert db.get(Cue, "r1").translated == "Hola"
        assert db.get(Cue, "r2").translated == ""


def test_apply_comparison_is_atomic_and_rejects_stale_cues(client):
    from app.core import Cue

    pid = local_project()
    with SessionLocal() as db:
        db.get(Project, pid).state = "ready"
        db.add_all(
            [
                Cue(
                    id="a",
                    project_id=pid,
                    position=0,
                    start=0,
                    end=1,
                    original="Hello",
                    translated="",
                ),
                Cue(
                    id="b",
                    project_id=pid,
                    position=1,
                    start=1,
                    end=2,
                    original="World",
                    translated="",
                ),
            ]
        )
        db.commit()
    headers = {"X-Studio-Local": "1"}
    changes = [
        {
            "cue_id": "a",
            "field": "translated",
            "value": "Hola",
            "expected": {"start": 0, "end": 1, "original": "Hello", "translated": ""},
        },
        {
            "cue_id": "b",
            "field": "translated",
            "value": "Mundo",
            "expected": {"start": 1, "end": 2, "original": "old", "translated": ""},
        },
    ]
    route = f"/api/projects/{pid}/apply-comparison"
    assert (
        client.post(route, headers=headers, json={"changes": changes}).status_code
        == 409
    )
    with SessionLocal() as db:
        assert db.get(Cue, "a").translated == ""
    changes[1]["expected"]["original"] = "World"
    assert (
        client.post(route, headers=headers, json={"changes": changes}).status_code
        == 200
    )
    with SessionLocal() as db:
        assert db.get(Cue, "a").translated == "Hola"
        assert db.get(Cue, "b").translated == "Mundo"


def test_comparison_undo_recovers_deleted_cue_and_review(client):
    from app.core import Cue, CueReview

    pid = local_project()
    with SessionLocal() as db:
        db.get(Project, pid).state = "ready"
        db.add(
            Cue(
                id="deleted",
                project_id=pid,
                position=0,
                start=1,
                end=2,
                original="Oops",
                translated="Texto",
            )
        )
        db.add(CueReview(cue_id="deleted", flag="silence", flag_resolved=0))
        db.commit()
    headers = {"X-Studio-Local": "1"}
    change = {
        "cue_id": "deleted",
        "field": "original",
        "value": "",
        "expected": {"start": 1, "end": 2, "original": "Oops", "translated": "Texto"},
    }
    applied = client.post(
        f"/api/projects/{pid}/apply-comparison",
        headers=headers,
        json={"changes": [change]},
    ).json()
    with SessionLocal() as db:
        assert db.get(Cue, "deleted") is None
    result = client.post(
        f"/api/projects/{pid}/comparisons/{applied['undo_id']}/undo", headers=headers
    )
    assert result.status_code == 200
    with SessionLocal() as db:
        assert db.get(Cue, "deleted").translated == "Texto"
        assert db.get(CueReview, "deleted").flag == "silence"


def test_comparison_undo_does_not_overwrite_later_edits(client):
    from app.core import Cue

    pid = local_project()
    with SessionLocal() as db:
        db.get(Project, pid).state = "ready"
        db.add(
            Cue(
                id="edited",
                project_id=pid,
                position=0,
                start=1,
                end=2,
                original="Hi",
                translated="",
            )
        )
        db.commit()
    headers = {"X-Studio-Local": "1"}
    change = {
        "cue_id": "edited",
        "field": "translated",
        "value": "Hola",
        "expected": {"start": 1, "end": 2, "original": "Hi", "translated": ""},
    }
    snapshot = client.post(
        f"/api/projects/{pid}/apply-comparison",
        headers=headers,
        json={"changes": [change]},
    ).json()["undo_id"]
    with SessionLocal() as db:
        db.get(Cue, "edited").translated = "Otro cambio"
        db.commit()
    assert (
        client.post(
            f"/api/projects/{pid}/comparisons/{snapshot}/undo", headers=headers
        ).status_code
        == 409
    )
    with SessionLocal() as db:
        assert db.get(Cue, "edited").translated == "Otro cambio"


def test_retranscribe_creates_new_draft_without_touching_original(client):
    from app.core import Cue

    pid = local_project()
    with SessionLocal() as db:
        project = db.get(Project, pid)
        project.state = "ready"
        db.add(
            Cue(
                id=str(uuid.uuid4()),
                project_id=pid,
                position=0,
                start=0,
                end=1,
                original="Revisado",
                translated="Edited",
            )
        )
        db.commit()
    path = Path(main.DATA) / pid / "source.json"
    info = json.loads(path.read_text())
    info.update(asr_language="Romanian", asr_model="whisper", timing_warnings=[0])
    path.write_text(json.dumps(info))
    before = client.get(f"/api/projects/{pid}").json()
    assert client.post(f"/api/projects/{pid}/retranscribe").status_code == 403
    response = client.post(
        f"/api/projects/{pid}/retranscribe", headers={"X-Studio-Local": "1"}
    )
    assert response.status_code == 200
    new_id = response.json()["id"]
    new = client.get(f"/api/projects/{new_id}").json()
    assert new_id != pid and new["project"]["state"] == "draft"
    assert new["project"]["prefer_asr"] is True and new["cues"] == []
    assert new["project"]["asr_language"] == "Romanian"
    assert new["project"]["asr_model"] == "whisper"
    assert new["project"]["timing_warnings"] == []
    assert new["project"]["name"].count("nueva transcripción") == 1
    assert client.get(f"/api/projects/{pid}").json() == before
    assert (
        json.loads((Path(main.DATA) / new_id / "source.json").read_text())["path"]
        == "/selected/original.mp4"
    )


def test_retranscribe_rejects_active_and_hidden_projects(client):
    pid = local_project()
    with SessionLocal() as db:
        db.get(Project, pid).state = "transcribing"
        db.commit()
    headers = {"X-Studio-Local": "1"}
    assert (
        client.post(f"/api/projects/{pid}/retranscribe", headers=headers).status_code
        == 409
    )
    with SessionLocal() as db:
        db.get(Project, pid).state = "ready"
        db.commit()
    assert client.delete(f"/api/projects/{pid}").status_code == 200
    assert (
        client.post(f"/api/projects/{pid}/retranscribe", headers=headers).status_code
        == 409
    )


def test_single_cue_translation_proposes_without_overwriting_while_transcribing(
    client, monkeypatch
):
    from app.core import Cue

    pid = local_project()
    with SessionLocal() as db:
        db.get(Project, pid).state = "transcribing"
        db.add(
            Cue(
                id="single",
                project_id=pid,
                position=0,
                start=1,
                end=2,
                original="Bună",
                translated="",
            )
        )
        db.commit()
    seen = []

    def native(method, path, **kwargs):
        seen.append(kwargs["json"])
        return SimpleNamespace(json=lambda: {"texts": ["Hola"]})

    monkeypatch.setattr(main, "native_request", native)
    response = client.post(
        f"/api/projects/{pid}/cues/single/translate",
        json={"direction": "forward", "target_language": "Spanish"},
        headers={"X-Studio-Local": "1"},
    )
    assert response.status_code == 200 and response.json()["text"] == "Hola"
    assert seen[0]["texts"] == ["Bună"] and seen[0]["target_language"] == "Spanish"
    assert client.get(f"/api/projects/{pid}").json()["cues"][0]["translated"] == ""
    expected = {"start": 1, "end": 2, "original": "Bună", "translated": ""}
    response = client.put(
        f"/api/projects/{pid}/cues/single",
        json={**expected, "translated": "Hola", "expected": expected},
    )
    assert response.status_code == 200


def test_compare_translations_reads_cue_without_mutating_it(client, monkeypatch):
    from app.core import Cue

    pid = local_project()
    with SessionLocal() as db:
        db.get(Project, pid).state = "ready"
        db.add(
            Cue(
                id="compare",
                project_id=pid,
                position=0,
                start=1,
                end=2,
                original="Bună",
                translated="",
            )
        )
        db.commit()
    seen = []

    def native(method, path, **kwargs):
        seen.append((path, kwargs.get("json")))
        return SimpleNamespace(
            json=lambda: {"results": [{"model": "a", "text": "Hola"}]}
        )

    monkeypatch.setattr(main, "native_request", native)
    response = client.post(
        f"/api/projects/{pid}/cues/compare/compare-translations",
        headers={"X-Studio-Local": "1"},
        json={
            "direction": "forward",
            "target_language": "Spanish",
            "models": ["a", "b"],
        },
    )
    assert response.status_code == 200
    assert seen[0][1]["text"] == "Bună"
    assert client.get(f"/api/projects/{pid}").json()["cues"][0]["translated"] == ""


def test_improvement_rejects_uninstalled_model_without_changing_project(
    client, monkeypatch
):
    from app.core import Cue

    pid = local_project()
    with SessionLocal() as db:
        db.get(Project, pid).state = "ready"
        db.add(
            Cue(
                id="protected",
                project_id=pid,
                position=0,
                start=1,
                end=2,
                original="Texto",
                translated="Traducción",
            )
        )
        db.commit()
    monkeypatch.setattr(
        main,
        "native_request",
        lambda *a, **kw: SimpleNamespace(json=lambda: [{"name": "installed"}]),
    )
    before = client.get(f"/api/projects/{pid}").json()
    response = client.post(f"/api/projects/{pid}/improve", json={"model": "missing"})
    assert response.status_code == 400
    assert client.get(f"/api/projects/{pid}").json() == before
    assert list((Path(main.DATA) / pid).glob("improvement-*.json")) == []


def test_improvement_proposals_are_explicit_and_reject_stale_changes(
    client, monkeypatch
):
    from app.core import Cue, CueReview
    from app import worker
    from types import SimpleNamespace

    pid = local_project()
    with SessionLocal() as db:
        db.get(Project, pid).state = "ready"
        db.add(
            Cue(
                id="proposal",
                project_id=pid,
                position=0,
                start=0,
                end=1,
                original="hello",
                translated="hola",
            )
        )
        db.commit()
    monkeypatch.setattr(
        main, "queue", lambda: SimpleNamespace(enqueue=lambda *a, **kw: None)
    )
    response = client.post(f"/api/projects/{pid}/improve")
    monkeypatch.setattr(worker, "mac_post", lambda *a, **kw: {"texts": ["Hello."]})
    worker.improve_project(pid, response.json()["backup"])
    detail = client.get(f"/api/projects/{pid}").json()
    assert detail["cues"][0]["original"] == "hello"
    assert detail["cues"][0]["proposal"] == "Hello."
    headers = {"X-Studio-Local": "1"}
    assert (
        client.post(
            f"/api/projects/{pid}/cues/proposal/proposal/accept", headers=headers
        ).status_code
        == 200
    )
    with SessionLocal() as db:
        assert db.get(Cue, "proposal").original == "Hello."
        assert db.get(Cue, "proposal").translated == "hola"
        review = db.get(CueReview, "proposal")
        review.proposal = "Stale"
        review.proposal_source = "hello"
        db.commit()
    assert (
        client.post(
            f"/api/projects/{pid}/cues/proposal/proposal/accept", headers=headers
        ).status_code
        == 409
    )


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
        json={
            "source": "asr",
            "action": "edit",
            "asr_language": "Romanian",
            "asr_model": "whisper",
        },
    )
    assert response.status_code == 200
    assert reference(pid)["asr_language"] == "Romanian"
    assert reference(pid)["asr_model"] == "whisper"


def test_model_deletion_rejects_active_projects_and_requires_local_header(
    client, monkeypatch
):
    pid = local_project()
    with SessionLocal() as db:
        db.get(Project, pid).state = "transcribing"
        db.commit()
    monkeypatch.setattr(
        main,
        "native_request",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not delete")),
    )
    assert client.delete("/api/models/qwen").status_code == 403
    assert (
        client.delete("/api/models/qwen", headers={"X-Studio-Local": "1"}).status_code
        == 409
    )


def test_model_comparison_does_not_modify_project(client, monkeypatch):
    pid = local_project()
    calls = []

    def native(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return SimpleNamespace(
            json=lambda: {
                "results": {"qwen": {"srt": "uno"}, "whisper": {"srt": "dos"}}
            }
        )

    monkeypatch.setattr(main, "native_request", native)
    before = client.get(f"/api/projects/{pid}").json()
    result = client.post(
        f"/api/projects/{pid}/compare-models",
        headers={"X-Studio-Local": "1"},
        json={"segment_start": 30, "language": "Romanian"},
    )
    assert result.status_code == 200
    assert calls[0][1] == "/compare-models"
    assert calls[0][2]["json"]["segment_start"] == 30
    assert client.get(f"/api/projects/{pid}").json() == before


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
