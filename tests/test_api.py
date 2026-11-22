from pathlib import Path
from types import SimpleNamespace
import pytest
from app import main
from app.core import SessionLocal, Project, Cue, CueReview


@pytest.fixture
def queued(monkeypatch):
    monkeypatch.setattr(
        main, "queue", lambda: SimpleNamespace(enqueue=lambda *a, **kw: None)
    )


def upload(client):
    return client.post(
        "/api/projects", files={"file": ("clip.wav", b"audio", "audio/wav")}
    )


def test_queue_failure_preserves_source_and_records_failure(client, monkeypatch):
    def unavailable():
        raise ConnectionError("queue offline")

    monkeypatch.setattr(main, "queue", unavailable)
    response = upload(client)
    assert response.status_code == 503
    projects = client.get("/api/projects").json()
    assert projects[0]["state"] == "failed"
    pid = projects[0]["id"]
    assert (Path(main.DATA) / pid / "source.wav").read_bytes() == b"audio"


def test_empty_upload_rejected(client, queued):
    response = client.post(
        "/api/projects", files={"file": ("empty.wav", b"", "audio/wav")}
    )
    assert response.status_code == 400
    assert client.get("/api/projects").json() == []


def test_upload_detail_media_and_export(client, queued):
    response = upload(client)
    assert response.status_code == 200
    pid = response.json()["id"]
    assert client.get(f"/api/projects/{pid}/media").content == b"audio"
    with SessionLocal() as db:
        db.get(Project, pid).state = "ready"
        db.add(
            Cue(
                id="cue",
                project_id=pid,
                position=0,
                start=1,
                end=2,
                original="Hello",
                translated="Hola",
            )
        )
        db.commit()
    assert (
        "00:00:01,000 --> 00:00:02,000\nHola"
        in client.get(f"/api/projects/{pid}/export").text
    )
    vtt = client.get(f"/api/projects/{pid}/export?language=original&format=vtt").text
    assert vtt.startswith("WEBVTT\n\n") and "Hello" in vtt


def test_bilingual_export_preserves_both_languages(client, queued):
    pid = upload(client).json()["id"]
    with SessionLocal() as db:
        db.get(Project, pid).state = "ready"
        db.add(
            Cue(
                id="bilingual",
                project_id=pid,
                position=0,
                start=1,
                end=2,
                original="Hello",
                translated="Hola",
            )
        )
        db.commit()
    r = client.get(f"/api/projects/{pid}/export?language=bilingual&format=srt")
    assert r.status_code == 200
    assert "Hello\nHola" in r.text


def test_export_uses_target_language_text_for_non_spanish_subtitles(client, queued):
    pid=upload(client).json()['id']
    with SessionLocal() as db:
        db.get(Project,pid).state='ready'
        db.add(Cue(id='ro-cue',project_id=pid,position=0,start=1,end=2,original='Hello',translated='Bună'))
        db.commit()
    result=client.get(f'/api/projects/{pid}/export?language=ro&format=srt')
    assert result.status_code == 200
    assert 'Bună' in result.text and 'Hello' not in result.text


def test_library_metadata_and_review_counts(client, queued):
    pid = upload(client).json()["id"]
    with SessionLocal() as db:
        project = db.get(Project, pid)
        project.name = "Una.Serie.S02E03.mkv"
        db.add(
            Cue(
                id="review-cue",
                project_id=pid,
                position=0,
                start=0,
                end=1,
                original="hola",
                translated="",
            )
        )
        db.add(
            CueReview(
                cue_id="review-cue", flag="repeat", flag_resolved=0, proposal="Hola."
            )
        )
        db.commit()
    project = client.get("/api/projects").json()[0]
    assert (project["serie"], project["season"], project["episode"]) == (
        "Una Serie",
        2,
        3,
    )
    assert project["counts"] == {
        "cues": 1,
        "untranslated": 1,
        "flagged_open": 1,
        "proposals": 1,
    }


def test_recipes_are_persisted_and_require_local_action(client):
    recipe = {
        "name": "Series inglés → español",
        "source_pref": "recommended",
        "asr_model": "whisper",
        "asr_language": "English",
        "target_language": "Spanish",
        "translation_model": "qwen3:14b-q8_0",
        "improve_before_translate": False,
        "flag_suspicious": True,
        "export_when_clean": False,
    }
    assert client.post("/api/recipes", json=recipe).status_code == 403
    created = client.post("/api/recipes", json=recipe, headers={"X-Studio-Local": "1"})
    assert created.status_code == 200
    stored = client.get("/api/recipes").json()
    assert len(stored) == 1
    assert stored[0]["id"] == created.json()["id"]
    assert stored[0]["asr_model"] == "whisper"
    assert stored[0]["translation_model"] == "qwen3:14b-q8_0"


def test_batch_uses_existing_local_drafts_and_enqueues_each_once(client, monkeypatch):
    jobs = []
    monkeypatch.setattr(
        main,
        "queue",
        lambda: SimpleNamespace(
            enqueue=lambda *args, **kwargs: jobs.append((args, kwargs))
        ),
    )
    recipe = {"name": "Prueba", "translation_model": "local-model"}
    rid = client.post(
        "/api/recipes", json=recipe, headers={"X-Studio-Local": "1"}
    ).json()["id"]
    with SessionLocal() as db:
        db.add_all(
            [
                Project(
                    id="p1",
                    name="ep1.mkv",
                    filename="source.json",
                    state="draft",
                    created=1,
                ),
                Project(
                    id="p2",
                    name="ep2.mkv",
                    filename="source.json",
                    state="draft",
                    created=2,
                ),
            ]
        )
        db.commit()
    result = client.post(
        "/api/batches",
        json={"project_ids": ["p1", "p2"], "recipe_id": rid},
        headers={"X-Studio-Local": "1"},
    )
    assert result.status_code == 200
    batch = client.get("/api/batches/" + result.json()["id"]).json()
    assert [item["project"]["id"] for item in batch["items"]] == ["p1", "p2"]
    assert len(jobs) == 2 and all(
        job[0][0] == "app.worker.process_batch_item" for job in jobs
    )
    assert (
        client.post(
            "/api/batches",
            json={"project_ids": ["p1"], "recipe_id": rid},
            headers={"X-Studio-Local": "1"},
        ).status_code
        == 409
    )


def test_batch_pause_and_resume_preserves_queued_project(client, monkeypatch):
    jobs = []
    monkeypatch.setattr(
        main, "queue", lambda: SimpleNamespace(enqueue=lambda *a, **kw: jobs.append(a))
    )
    headers = {"X-Studio-Local": "1"}
    rid = client.post(
        "/api/recipes",
        json={"name": "Prueba", "translation_model": "model"},
        headers=headers,
    ).json()["id"]
    with SessionLocal() as db:
        db.add(
            Project(
                id="p", name="ep.mkv", filename="source.json", state="draft", created=0
            )
        )
        db.commit()
    bid = client.post(
        "/api/batches", json={"project_ids": ["p"], "recipe_id": rid}, headers=headers
    ).json()["id"]
    assert client.post(f"/api/batches/{bid}/pause", headers=headers).status_code == 200
    paused = client.get(f"/api/batches/{bid}").json()
    assert paused["paused"] and paused["items"][0]["status"] == "paused"
    assert paused["items"][0]["project"]["state"] == "batch_queued"
    assert client.post(f"/api/batches/{bid}/resume", headers=headers).status_code == 200
    assert client.get(f"/api/batches/{bid}").json()["items"][0]["status"] == "queued"
    assert len(jobs) == 2


def test_cancel_queued_batch_item_returns_project_to_draft(client, monkeypatch):
    monkeypatch.setattr(main,'queue',lambda:SimpleNamespace(enqueue=lambda *a,**kw:None))
    headers={'X-Studio-Local':'1'}
    rid=client.post('/api/recipes',json={'name':'Prueba','translation_model':'model'},headers=headers).json()['id']
    with SessionLocal() as db:
        db.add(Project(id='p',name='ep.mkv',filename='source.json',state='draft',created=0))
        db.commit()
    bid=client.post('/api/batches',json={'project_ids':['p'],'recipe_id':rid},headers=headers).json()['id']
    item=client.get(f'/api/batches/{bid}').json()['items'][0]
    assert client.post(f"/api/batches/{bid}/items/{item['id']}/cancel",headers=headers).status_code==200
    result=client.get(f'/api/batches/{bid}').json()['items'][0]
    assert result['status']=='cancelled'
    assert result['project']['state']=='draft'


def test_batch_review_must_resume_through_queue_not_direct_translation(client, monkeypatch):
    from app.core import BatchItem
    monkeypatch.setattr(main,'queue',lambda:SimpleNamespace(enqueue=lambda *a,**kw:None))
    headers={'X-Studio-Local':'1'}
    rid=client.post('/api/recipes',json={'name':'Prueba','translation_model':'model'},headers=headers).json()['id']
    with SessionLocal() as db:
        db.add(Project(id='p',name='ep.mkv',filename='source.json',state='draft',created=0))
        db.commit()
    bid=client.post('/api/batches',json={'project_ids':['p'],'recipe_id':rid},headers=headers).json()['id']
    item=client.get(f'/api/batches/{bid}').json()['items'][0]
    with SessionLocal() as db:
        db.get(Project,'p').state='ready'
        current=db.get(BatchItem,item['id'])
        current.status='review'
        current.stage='review'
        db.add(Cue(id='c',project_id='p',position=0,start=0,end=1,original='Hi',translated=''))
        db.commit()
    assert client.post('/api/projects/p/translate').status_code == 409


@pytest.mark.parametrize("state", ["queued", "transcribing", "translating"])
def test_edits_cannot_race_worker(client, queued, state):
    pid = upload(client).json()["id"]
    with SessionLocal() as db:
        db.get(Project, pid).state = state
        db.add(
            Cue(id="cue", project_id=pid, position=0, start=1, end=2, original="Hello")
        )
        db.commit()
    response = client.put(
        f"/api/projects/{pid}/cues/cue",
        json={"start": 1, "end": 2, "original": "Edited", "translated": "Hola"},
    )
    assert response.status_code == 409


def test_non_finite_timestamp_rejected():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        main.CueUpdate(start=1, end=float("inf"), original="text", translated="texto")


def test_health_reports_queue_outage(client, monkeypatch):
    def unavailable():
        raise ConnectionError("private connection details")

    monkeypatch.setattr(main, "queue", unavailable)
    response = client.get("/api/health")
    assert response.status_code == 503
    assert "private connection details" not in response.text


def test_transcription_progress_comes_from_saved_checkpoint(client, queued):
    from app.core import TranscriptionProgress

    pid = upload(client).json()["id"]
    with SessionLocal() as db:
        db.get(Project, pid).state = "transcribing"
        db.add(TranscriptionProgress(project_id=pid, next_start=330, completed=0))
        db.commit()
    project = client.get(f"/api/projects/{pid}").json()["project"]
    assert project["task_progress"]["processed_seconds"] == 330
    assert project["task_progress"]["completed"] is False


def test_translation_progress_counts_saved_cues(client, queued):
    pid = upload(client).json()["id"]
    with SessionLocal() as db:
        db.get(Project, pid).state = "translating"
        db.add_all(
            [
                Cue(
                    id="t1",
                    project_id=pid,
                    position=0,
                    start=0,
                    end=1,
                    original="A",
                    translated="Uno",
                ),
                Cue(
                    id="t2",
                    project_id=pid,
                    position=1,
                    start=1,
                    end=2,
                    original="B",
                    translated="",
                ),
            ]
        )
        db.commit()
    project = client.get(f"/api/projects/{pid}").json()["project"]
    assert project["task_progress"]["done"] == 1
    assert project["task_progress"]["total"] == 2


def test_improvement_progress_reports_persisted_percent_and_activity(client, queued):
    pid = upload(client).json()["id"]
    path = (
        Path(main.DATA) / pid / "improvement-11111111-1111-4111-8111-111111111111.json"
    )
    path.write_text('{"restored": false, "cues": []}')
    with SessionLocal() as db:
        project = db.get(Project, pid)
        project.state = "improving"
        project.progress = 42
        db.commit()
    progress = client.get(f"/api/projects/{pid}").json()["project"]["task_progress"]
    assert progress["percent"] == 42
    assert abs(progress["updated_at"] - path.stat().st_mtime) < 0.001


def test_pause_resume_and_cancel_queued_project(client, queued):
    pid = upload(client).json()["id"]
    headers = {"X-Studio-Local": "1"}
    assert client.post(f"/api/projects/{pid}/pause").status_code == 403
    assert client.post(f"/api/projects/{pid}/pause", headers=headers).status_code == 200
    assert client.get(f"/api/projects/{pid}").json()["project"]["state"] == "paused"
    assert (
        client.post(f"/api/projects/{pid}/resume", headers=headers).status_code == 200
    )
    assert client.get(f"/api/projects/{pid}").json()["project"]["state"] == "queued"
    assert (
        client.post(f"/api/projects/{pid}/cancel", headers=headers).status_code == 200
    )
    assert client.get(f"/api/projects/{pid}").json()["project"]["state"] == "cancelled"


def test_retry_failed_project_and_reject_duplicate(client, queued):
    pid = upload(client).json()["id"]
    with SessionLocal() as db:
        db.get(Project, pid).state = "failed"
        db.commit()
    assert client.post(f"/api/projects/{pid}/retry").status_code == 200
    assert client.get(f"/api/projects/{pid}").json()["project"]["state"] == "queued"
    assert client.post(f"/api/projects/{pid}/retry").status_code == 409


def test_retry_queue_failure_is_visible_and_keeps_media(client, queued, monkeypatch):
    pid = upload(client).json()["id"]
    with SessionLocal() as db:
        db.get(Project, pid).state = "failed"
        db.commit()

    def unavailable():
        raise ConnectionError("offline")

    monkeypatch.setattr(main, "queue", unavailable)
    assert client.post(f"/api/projects/{pid}/retry").status_code == 503
    assert client.get(f"/api/projects/{pid}").json()["project"]["state"] == "failed"
    assert client.get(f"/api/projects/{pid}/media").content == b"audio"


def test_stale_editor_does_not_overwrite_other_changes(client, queued):
    pid = upload(client).json()["id"]
    with SessionLocal() as db:
        db.get(Project, pid).state = "ready"
        db.add(
            Cue(
                id="cue",
                project_id=pid,
                position=0,
                start=1,
                end=2,
                original="New original",
                translated="",
            )
        )
        db.commit()
    old = {"start": 1, "end": 2, "original": "Old original", "translated": ""}
    change = {**old, "translated": "Hola", "expected": old}
    response = client.put(f"/api/projects/{pid}/cues/cue", json=change)
    assert response.status_code == 409
    assert (
        client.get(f"/api/projects/{pid}").json()["cues"][0]["original"]
        == "New original"
    )


def test_trash_and_restore_keep_project_data_and_original(client, queued):
    pid = upload(client).json()["id"]
    with SessionLocal() as db:
        db.get(Project, pid).state = "ready"
        db.add(
            Cue(
                id="trash-cue",
                project_id=pid,
                position=0,
                start=0,
                end=1,
                original="Hello",
                translated="Hola",
            )
        )
        db.commit()
    path = Path(main.DATA) / pid / "source.wav"
    assert client.delete(f"/api/projects/{pid}").status_code == 200
    assert client.get("/api/projects").json() == []
    assert path.read_bytes() == b"audio"
    assert client.get(f"/api/projects/{pid}").json()["cues"][0]["original"] == "Hello"
    assert client.post(f"/api/projects/{pid}/restore").status_code == 200
    assert client.get("/api/projects").json()[0]["id"] == pid


def test_running_project_cannot_be_removed(client, queued):
    pid = upload(client).json()["id"]
    assert client.delete(f"/api/projects/{pid}").status_code == 409
    assert client.get("/api/projects").json()[0]["id"] == pid


def test_library_bulk_mutation_requires_same_origin_header(client, queued):
    assert client.post("/api/library/clear").status_code == 403
    assert client.post("/api/library/restore").status_code == 403
    assert (
        client.post("/api/library/clear", headers={"X-Studio-Local": "1"}).status_code
        == 200
    )
    assert (
        client.post("/api/library/restore", headers={"X-Studio-Local": "1"}).status_code
        == 200
    )


def test_hidden_project_cannot_be_requeued(client, queued):
    pid = upload(client).json()["id"]
    with SessionLocal() as db:
        db.get(Project, pid).state = "failed"
        db.add(
            Cue(
                id="hidden-cue",
                project_id=pid,
                position=0,
                start=0,
                end=1,
                original="Hello",
                translated="",
            )
        )
        db.commit()
    assert client.delete(f"/api/projects/{pid}").status_code == 200
    assert client.post(f"/api/projects/{pid}/retry").status_code == 409
    assert client.post(f"/api/projects/{pid}/translate").status_code == 409
    assert client.post(f"/api/projects/{pid}/improve").status_code == 409


def test_sync_preview_and_apply_are_explicit_and_detect_concurrent_changes(client, queued, monkeypatch):
    pid = upload(client).json()['id']
    with SessionLocal() as db:
        db.get(Project, pid).state = 'ready'
        db.add(Cue(id='sync-cue', project_id=pid, position=0, start=1, end=2, original='Hola', translated='Hello'))
        db.commit()
    monkeypatch.setattr(main, 'native_request', lambda method, path, **kwargs: SimpleNamespace(json=lambda: {'srt': '1\n00:00:03,000 --> 00:00:04,000\nHola\n'}))
    headers = {'X-Studio-Local': '1'}
    response = client.post(f'/api/projects/{pid}/sync-preview', headers=headers, json={'audio_index': 0})
    assert response.status_code == 200
    proposal = response.json()['cues']
    assert proposal == [{'id': 'sync-cue', 'start': 1.0, 'end': 2.0, 'new_start': 3.0, 'new_end': 4.0}]
    with SessionLocal() as db:
        assert db.get(Cue, 'sync-cue').start == 1
    result = client.post(f'/api/projects/{pid}/sync-apply', headers=headers, json={'cues': proposal})
    assert result.status_code == 200
    with SessionLocal() as db:
        cue = db.get(Cue, 'sync-cue')
        assert (cue.start, cue.end, cue.original, cue.translated) == (3, 4, 'Hola', 'Hello')
    assert client.post(f'/api/projects/{pid}/sync-apply', headers=headers, json={'cues': proposal}).status_code == 409


def test_sync_rejects_output_that_loses_subtitles(client, queued, monkeypatch):
    pid = upload(client).json()['id']
    with SessionLocal() as db:
        db.get(Project, pid).state = 'ready'
        db.add(Cue(id='a', project_id=pid, position=0, start=1, end=2, original='Primero', translated=''))
        db.add(Cue(id='b', project_id=pid, position=1, start=3, end=4, original='Segundo', translated=''))
        db.commit()
    monkeypatch.setattr(main, 'native_request', lambda *args, **kwargs: SimpleNamespace(json=lambda: {'srt': '1\n00:00:03,000 --> 00:00:04,000\nSegundo\n'}))
    response = client.post(f'/api/projects/{pid}/sync-preview', headers={'X-Studio-Local': '1'}, json={'audio_index': 0})
    assert response.status_code == 422
    with SessionLocal() as db:
        assert [(c.start, c.original) for c in db.query(Cue).order_by(Cue.position).all()] == [(1, 'Primero'), (3, 'Segundo')]


def test_insert_after_and_undo_restores_existing_cues(client, queued):
    pid = upload(client).json()['id']
    with SessionLocal() as db:
        db.get(Project, pid).state = 'ready'
        db.add(Cue(id='a', project_id=pid, position=0, start=0, end=1, original='A', translated=''))
        db.add(Cue(id='b', project_id=pid, position=1, start=3, end=4, original='B', translated=''))
        db.commit()
    headers = {'X-Studio-Local':'1'}
    response = client.post(f'/api/projects/{pid}/cues/a/insert-after', headers=headers)
    assert response.status_code == 200
    data = response.json()
    with SessionLocal() as db:
        rows = db.query(Cue).order_by(Cue.position).all()
        assert [c.id for c in rows] == ['a', data['cue']['id'], 'b']
        assert rows[1].start == 1 and rows[1].end == 3
    response = client.post(f"/api/projects/{pid}/comparisons/{data['undo_id']}/undo", headers=headers)
    assert response.status_code == 200
    with SessionLocal() as db:
        assert [(c.id,c.position) for c in db.query(Cue).order_by(Cue.position).all()] == [('a',0),('b',1)]


def test_undo_insert_refuses_to_delete_an_entry_edited_after_creation(client, queued):
    pid = upload(client).json()['id']
    with SessionLocal() as db:
        db.get(Project, pid).state = 'ready'
        db.add(Cue(id='a', project_id=pid, position=0, start=0, end=1, original='A', translated=''))
        db.commit()
    headers={'X-Studio-Local':'1'}
    response=client.post(f'/api/projects/{pid}/cues/a/insert-after', headers=headers).json()
    with SessionLocal() as db:
        db.get(Cue, response['cue']['id']).original='Nuevo texto'
        db.commit()
    result=client.post(f"/api/projects/{pid}/comparisons/{response['undo_id']}/undo", headers=headers)
    assert result.status_code == 409
    with SessionLocal() as db:
        assert db.get(Cue, response['cue']['id']).original == 'Nuevo texto'


def test_translation_settings_are_saved_for_uploaded_projects(client, queued, monkeypatch):
    pid = upload(client).json()['id']
    with SessionLocal() as db:
        db.get(Project, pid).state = 'ready'
        db.add(Cue(id='c', project_id=pid, position=0, start=1, end=2, original='Hello', translated=''))
        db.commit()
    monkeypatch.setattr(main, 'native_request', lambda *args, **kwargs: SimpleNamespace(json=lambda: [{'name':'model:one'}]))
    result = client.post(f'/api/projects/{pid}/translate', json={'target_language':'Romanian','model':'model:one'})
    assert result.status_code == 200
    assert main.reference(pid)['target_language'] == 'Romanian'
    assert main.reference(pid)['translation_model'] == 'model:one'
    assert (Path(main.DATA)/pid/'source.wav').read_bytes() == b'audio'
    assert not (Path(main.DATA)/pid/'source.json').exists()


def test_translation_does_not_mix_destination_languages(client, queued, monkeypatch):
    pid = upload(client).json()['id']
    with SessionLocal() as db:
        db.get(Project, pid).state = 'ready'
        db.add(Cue(id='a', project_id=pid, position=0, start=1, end=2, original='Hello', translated='Hola'))
        db.add(Cue(id='b', project_id=pid, position=1, start=3, end=4, original='Bye', translated=''))
        db.commit()
    monkeypatch.setattr(main, 'native_request', lambda *args, **kwargs: SimpleNamespace(json=lambda: [{'name':'model:one'}]))
    main.save_workflow(pid, 'asr', 'edit', target_language='Spanish')
    result = client.post(f'/api/projects/{pid}/translate', json={'target_language':'Romanian','model':'model:one'})
    assert result.status_code == 409
    with SessionLocal() as db:
        assert db.get(Project,pid).state == 'ready'
        assert db.get(Cue,'a').translated == 'Hola'


def test_translation_does_not_enqueue_empty_originals(client, queued):
    pid=upload(client).json()['id']
    with SessionLocal() as db:
        db.get(Project,pid).state='ready'
        db.add(Cue(id='blank',project_id=pid,position=0,start=1,end=2,original='',translated=''))
        db.commit()
    assert client.post(f'/api/projects/{pid}/translate').status_code == 409


def test_single_translation_records_its_language_and_model_for_later_work(client, queued, monkeypatch):
    pid=upload(client).json()['id']
    with SessionLocal() as db:
        db.get(Project,pid).state='ready'
        db.add(Cue(id='c',project_id=pid,position=0,start=1,end=2,original='Hello',translated=''))
        db.commit()
    monkeypatch.setattr(main,'native_request',lambda *a, **k: SimpleNamespace(json=lambda:{'texts':['Bună']}))
    result=client.post(f'/api/projects/{pid}/cues/c/translate',headers={'X-Studio-Local':'1'},json={'direction':'forward','target_language':'Romanian'})
    assert result.status_code == 200
    assert main.reference(pid)['target_language'] == 'Romanian'


def test_unknown_existing_translation_language_can_be_explicitly_identified(client, queued, monkeypatch):
    pid=upload(client).json()['id']
    with SessionLocal() as db:
        db.get(Project,pid).state='ready'
        db.add(Cue(id='a',project_id=pid,position=0,start=1,end=2,original='Hello',translated='Bună'))
        db.add(Cue(id='b',project_id=pid,position=1,start=3,end=4,original='Bye',translated=''))
        db.commit()
    monkeypatch.setattr(main,'native_request',lambda *a,**k: SimpleNamespace(json=lambda:[{'name':'model:one'}]))
    result=client.post(f'/api/projects/{pid}/translate',json={'target_language':'Romanian','model':'model:one'})
    assert result.status_code == 200
    assert main.reference(pid)['target_language'] == 'Romanian'


def test_single_translation_uses_chosen_installed_model(client, queued, monkeypatch):
    pid=upload(client).json()['id']
    with SessionLocal() as db:
        db.get(Project,pid).state='ready'
        db.add(Cue(id='c',project_id=pid,position=0,start=1,end=2,original='Hello',translated=''))
        db.commit()
    sent=[]
    def gateway(method,path,**kwargs):
        if path=='/ollama/models':
            return SimpleNamespace(json=lambda:[{'name':'chosen'}])
        sent.append(kwargs['json'])
        return SimpleNamespace(json=lambda:{'texts':['Hola']})
    monkeypatch.setattr(main,'native_request',gateway)
    result=client.post(f'/api/projects/{pid}/cues/c/translate',headers={'X-Studio-Local':'1'},json={'direction':'forward','target_language':'Spanish','model':'chosen'})
    assert result.status_code==200
    assert sent[0]['model']=='chosen'
    assert main.reference(pid)['translation_model']=='chosen'


def test_confirm_language_of_existing_translation_without_starting_work(client, queued):
    pid=upload(client).json()['id']
    with SessionLocal() as db:
        db.get(Project,pid).state='ready'
        db.add(Cue(id='a',project_id=pid,position=0,start=1,end=2,original='Hello',translated='Bună'))
        db.commit()
    result=client.post(f'/api/projects/{pid}/translation-language',json={'target_language':'Romanian'})
    assert result.status_code == 200
    assert main.reference(pid)['target_language']=='Romanian'
    with SessionLocal() as db:
        assert db.get(Project,pid).state=='ready'
        assert db.get(Cue,'a').translated=='Bună'


def test_identify_translation_language_while_transcribing(client, queued):
    pid = upload(client).json()['id']
    with SessionLocal() as db:
        db.get(Project, pid).state = 'transcribing'
        db.add(Cue(id='a', project_id=pid, position=0, start=1, end=2, original='Hello', translated='Hola'))
        db.commit()
    result = client.post(f'/api/projects/{pid}/translation-language', json={'target_language': 'Spanish'})
    assert result.status_code == 200
    assert main.reference(pid)['target_language'] == 'Spanish'
