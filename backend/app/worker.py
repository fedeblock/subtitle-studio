import os
import uuid
import requests
import socket
import json
import time
import logging
import re
from pathlib import Path
from sqlalchemy import select, update
from redis import Redis
from rq import Worker, Queue
from app.core import (
    initialize,
    SessionLocal,
    Project,
    Cue,
    TranscriptionProgress,
    CueReview,
    Batch,
    BatchItem,
    engine,
)
from app.subtitles import parse_srt, export
from app.project_sources import reference, record_estimated_timing
from app import improvement
from app.core import DATA

MAC_URL = os.environ.get("MAC_URL", "http://host.docker.internal:8765")
TOKEN = os.environ.get("MAC_TOKEN", "")
log = logging.getLogger(__name__)
RETRY_DELAYS = (2, 4, 8)
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


def repeated_text(previous, current):
    def normalize(value):
        return re.findall(r"\w+", value.casefold(), flags=re.UNICODE)

    words = normalize(current)
    if words and words == normalize(previous):
        return True
    return any(
        words[i : i + size] == words[i + size : i + 2 * size]
        for size in range(3, min(12, len(words) // 2) + 1)
        for i in range(len(words) - 2 * size + 1)
    )


class TaskStopped(Exception):
    """A requested pause or cancellation reached a safe boundary."""


def task_boundary(pid):
    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.id == pid).with_for_update())
        if project and project.state in ("pausing", "cancelling"):
            project.state = "paused" if project.state == "pausing" else "cancelled"
            db.commit()
            raise TaskStopped()


def set_status(pid, state, progress=0, error=""):
    with SessionLocal() as db:
        db.execute(
            update(Project)
            .where(
                Project.id == pid,
                Project.state.not_in(("pausing", "cancelling", "paused", "cancelled")),
            )
            .values(state=state, progress=progress, error=error[:3000])
        )
        db.commit()


def mac_post(path, json, timeout=14400, should_stop=None):
    for attempt in range(len(RETRY_DELAYS) + 1):
        if should_stop:
            should_stop()
        try:
            response = requests.post(
                MAC_URL + path,
                json=json,
                headers={"X-Worker-Token": TOKEN},
                timeout=timeout,
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            detail = str(exc)
        else:
            if response.ok:
                return response.json()
            try:
                detail = response.json().get("detail", response.reason)
            except ValueError:
                detail = response.reason
            retryable = response.status_code in RETRYABLE_STATUS
            response.close()
            if not retryable:
                raise RuntimeError(f"Gateway {path}: {detail}")
        if attempt == len(RETRY_DELAYS):
            raise RuntimeError(f"Gateway {path}: {detail} (tras 3 reintentos)")
        if should_stop:
            should_stop()
        delay = RETRY_DELAYS[attempt]
        log.warning(
            "Gateway %s: fallo temporal; reintento %s/3 en %ss",
            path,
            attempt + 1,
            delay,
        )
        time.sleep(delay)


def process_project(pid):
    initialize()
    # Atomically claim queued work. Duplicate deliveries must not overwrite edits.
    with SessionLocal() as db:
        claimed = db.execute(
            update(Project)
            .where(Project.id == pid, Project.state == "queued")
            .values(state="transcribing", progress=10, error="")
        )
        db.commit()
        if claimed.rowcount != 1:
            return
    try:
        task_boundary(pid)
        with SessionLocal() as db:
            existing = db.scalars(
                select(Cue).where(Cue.project_id == pid).order_by(Cue.position)
            ).all()
            cues = [{"original": c.original} for c in existing]
        info = reference(pid)
        with SessionLocal() as db:
            checkpoint = db.get(TranscriptionProgress, pid)
            incremental = bool(checkpoint) or (
                not cues and info.get("selected_source") == "asr"
            )
            if incremental and not checkpoint:
                db.add(TranscriptionProgress(project_id=pid, next_start=0, completed=0))
                db.commit()
        if incremental:
            transcribe_incrementally(pid, info)
            with SessionLocal() as db:
                cues = [
                    {"original": c.original}
                    for c in db.scalars(
                        select(Cue).where(Cue.project_id == pid).order_by(Cue.position)
                    ).all()
                ]
            if not cues:
                raise ValueError("No se detectaron subtítulos válidos")
        elif not cues:
            request = {"project_id": pid}
            audio_index = reference(pid).get("audio_index")
            if audio_index is not None:
                request["audio_index"] = audio_index
            result = mac_post(
                "/transcribe", request, should_stop=lambda: task_boundary(pid)
            )
            cues = parse_srt(result["srt"])
            if not cues:
                raise ValueError("No se detectaron subtítulos válidos")
            with SessionLocal() as db:
                for index, c in enumerate(cues):
                    db.add(
                        Cue(id=str(uuid.uuid4()), project_id=pid, position=index, **c)
                    )
                db.get(Project, pid).language = result.get("language", "auto")
                db.commit()
        if reference(pid).get("action") in ("edit", "view"):
            task_boundary(pid)
            set_status(pid, "ready", 100)
            task_boundary(pid)
            return
        task_boundary(pid)
        set_status(pid, "translating", 55)
        with SessionLocal() as db:
            records = db.scalars(
                select(Cue).where(Cue.project_id == pid).order_by(Cue.position)
            ).all()
            originals = [c.original for c in records]
            pending = [
                (i, c.id, c.original)
                for i, c in enumerate(records)
                if (c.original or "").strip() and not (c.translated or "").strip()
            ]
        completed = len(records) - len(pending)
        for k in range(0, len(pending), 6):
            task_boundary(pid)
            batch = pending[k : k + 6]
            part = [entry[2] for entry in batch]
            first = batch[0][0]
            context = " ".join(originals[max(0, first - 3) : first])
            payload = {"texts": part, "context": context}
            if info.get("target_language"):
                payload["target_language"] = info["target_language"]
            if info.get("translation_model"):
                payload["model"] = info["translation_model"]
            answer = mac_post(
                "/translate",
                payload,
                timeout=(10, 900),
                should_stop=lambda: task_boundary(pid),
            )["texts"]
            if (
                not isinstance(answer, list)
                or len(answer) != len(part)
                or not all(isinstance(t, str) and t.strip() for t in answer)
            ):
                raise ValueError("La traducción devolvió líneas inválidas")
            with SessionLocal() as db:
                for entry, translated in zip(batch, answer):
                    db.get(Cue, entry[1]).translated = translated
                db.commit()
            completed += len(batch)
            set_status(pid, "translating", 55 + int(40 * completed / len(cues)))
            task_boundary(pid)
        task_boundary(pid)
        set_status(pid, "ready", 100)
        task_boundary(pid)
    except TaskStopped:
        return
    except Exception as exc:
        try:
            task_boundary(pid)
        except TaskStopped:
            return
        set_status(pid, "failed", 0, str(exc))
        try:
            task_boundary(pid)
        except TaskStopped:
            return
        raise


def transcribe_incrementally(pid, info):
    while True:
        task_boundary(pid)
        with SessionLocal() as db:
            checkpoint = db.get(TranscriptionProgress, pid)
            if checkpoint.completed:
                return
            start = checkpoint.next_start
        request = {"project_id": pid, "segment_start": start}
        if info.get("asr_model", "qwen") != "qwen":
            request["model"] = info["asr_model"]
        if info.get("audio_index") is not None:
            request["audio_index"] = info["audio_index"]
        if info.get("asr_language"):
            request["language"] = info["asr_language"]
        result = mac_post(
            "/transcribe-chunk",
            request,
            timeout=(10, 900),
            should_stop=lambda: task_boundary(pid),
        )
        srt = result.get("srt")
        if not isinstance(srt, str):
            raise ValueError("El gateway devolvió un subtítulo inválido")
        new_cues = parse_srt(srt)
        if srt.strip() and not new_cues:
            raise ValueError("El gateway devolvió marcas de tiempo inválidas")
        if not isinstance(result.get("end_of_audio"), bool):
            raise ValueError("El gateway no indicó el final del audio")
        native_flags = result.get("flags", [None] * len(new_cues))
        if (
            not isinstance(native_flags, list)
            or len(native_flags) != len(new_cues)
            or any(
                flag not in (None, "silence", "low_confidence", "out_of_chunk")
                for flag in native_flags
            )
        ):
            raise ValueError("El gateway devolvió indicadores de revisión inválidos")
        if result.get("estimated_timing") is True:
            record_estimated_timing(pid, start)
        with SessionLocal() as db:
            checkpoint = db.get(TranscriptionProgress, pid)
            if checkpoint.next_start != start or checkpoint.completed:
                raise ValueError("La transcripción cambió durante el procesamiento")
            existing = db.scalars(
                select(Cue).where(Cue.project_id == pid).order_by(Cue.position)
            ).all()
            previous = existing[-1].original if existing else ""
            for offset, cue in enumerate(new_cues):
                i = len(existing) + offset
                if cue["start"] < start or cue["end"] > start + 30.001:
                    raise ValueError(
                        "La transcripción devolvió tiempos fuera del tramo"
                    )
                cue_id = str(uuid.uuid4())
                db.add(Cue(id=cue_id, project_id=pid, position=i, **cue))
                flag = native_flags[offset] or (
                    "repeat" if repeated_text(previous, cue["original"]) else None
                )
                if flag and info.get("flag_suspicious", True):
                    db.add(CueReview(cue_id=cue_id, flag=flag))
                previous = cue["original"]
            checkpoint.next_start = start + 30
            checkpoint.completed = int(result["end_of_audio"])
            if result.get("language"):
                db.get(Project, pid).language = result["language"]
            db.commit()
        task_boundary(pid)


def batch_write_workflow(pid, **changes):
    path = Path(DATA) / pid / "source.json"
    info = reference(pid)
    if not info.get("path"):
        raise ValueError("La referencia al vídeo no está disponible")
    info.update(changes)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(info, ensure_ascii=False))
    temp.replace(path)


def batch_transition(item_id, stage, status="running", error=""):
    with SessionLocal() as db:
        item = db.get(BatchItem, item_id)
        item.stage = stage
        if item.status == "cancelling" and status != "done":
            item.status = "cancelled"
            project = db.get(Project, item.project_id)
            if project.state == "batch_queued":
                project.state = "draft"
            elif project.state in ("queued", "paused", "improve_queued"):
                project.state = "cancelled"
        else:
            item.status, item.error = status, error
        db.commit()


def process_batch_item(item_id):
    """Run one durable batch item up to a manual review boundary."""
    initialize()
    with SessionLocal() as db:
        item = db.scalar(
            select(BatchItem).where(BatchItem.id == item_id).with_for_update()
        )
        if not item or item.status != "queued":
            return
        batch = db.scalar(
            select(Batch).where(Batch.id == item.batch_id).with_for_update()
        )
        if batch.paused:
            item.status = "paused"
            db.commit()
            return
        item.status, item.error = "running", ""
        pid, config = item.project_id, json.loads(batch.recipe)
        db.commit()
    try:
        while True:
            with SessionLocal() as db:
                item = db.get(BatchItem, item_id)
                batch = db.get(Batch, item.batch_id)
                project = db.get(Project, pid)
                if item.status == "cancelled":
                    return
                if item.status == "cancelling":
                    item.status = "cancelled"
                    if project.state == "batch_queued":
                        project.state = "draft"
                    elif project.state in ("queued", "paused", "improve_queued"):
                        project.state = "cancelled"
                    db.commit()
                    return
                if batch.paused:
                    item.status = "paused"
                    db.commit()
                    return
                stage = item.stage
                project_state = project.state
            if stage == "source":
                info = reference(pid)
                choices = [
                    entry
                    for entry in info.get("subtitles", [])
                    if entry.get("supported") and entry.get("match") is not False
                ]
                preference = config.get("source_pref", "recommended")
                if preference == "asr":
                    source = "asr"
                else:
                    preferred = next(
                        (
                            entry
                            for entry in choices
                            if preference == "english"
                            and entry.get("language") in ("en", "eng")
                        ),
                        None,
                    )
                    preferred = preferred or next(
                        (entry for entry in choices if entry.get("recommended")), None
                    )
                    preferred = preferred or (choices[0] if choices else None)
                    source = preferred["id"] if preferred else "asr"
                imported = []
                if source != "asr":
                    response = mac_post(
                        "/files/subtitle", {"project_id": pid, "subtitle_id": source}
                    )
                    imported = parse_srt(response["srt"])
                    if not imported:
                        raise ValueError(
                            "La fuente seleccionada no contiene subtítulos válidos"
                        )
                tracks = info.get("audio_tracks", [])
                audio_index = tracks[0]["index"] if tracks else None
                with SessionLocal() as db:
                    project = db.scalar(
                        select(Project).where(Project.id == pid).with_for_update()
                    )
                    item = db.get(BatchItem, item_id)
                    if (
                        project.state not in ("draft", "batch_queued")
                        or item.stage != "source"
                    ):
                        raise ValueError("El proyecto cambió antes de elegir la fuente")
                    batch_write_workflow(
                        pid,
                        selected_source=source,
                        action="edit",
                        audio_index=audio_index,
                        asr_language=config.get("asr_language"),
                        asr_model=config.get("asr_model", "qwen"),
                        target_language=config.get("target_language", "Spanish"),
                        translation_model=config.get("translation_model"),
                        flag_suspicious=config.get("flag_suspicious", True),
                    )
                    for position, cue in enumerate(imported):
                        db.add(
                            Cue(
                                id=str(uuid.uuid4()),
                                project_id=pid,
                                position=position,
                                **cue,
                            )
                        )
                    project.state = "ready" if imported else "queued"
                    project.progress = 100 if imported else 0
                    item.stage = (
                        "improve"
                        if imported and config.get("improve_before_translate")
                        else "review"
                        if imported
                        else "process"
                    )
                    db.commit()
            elif stage == "process":
                if project_state == "queued":
                    process_project(pid)
                with SessionLocal() as db:
                    project = db.get(Project, pid)
                    if project.state == "paused":
                        batch_transition(item_id, stage, "paused")
                        return
                    if project.state != "ready":
                        raise ValueError(
                            project.error or "La transcripción no ha terminado"
                        )
                batch_transition(
                    item_id,
                    "improve" if config.get("improve_before_translate") else "review",
                )
            elif stage == "improve":
                with SessionLocal() as db:
                    item = db.get(BatchItem, item_id)
                    project = db.scalar(
                        select(Project).where(Project.id == pid).with_for_update()
                    )
                    if not item.improvement_id:
                        cues = db.scalars(
                            select(Cue)
                            .where(Cue.project_id == pid)
                            .order_by(Cue.position)
                        ).all()
                        backup_id = str(uuid.uuid4())
                        improvement.write(
                            Path(DATA) / pid / f"improvement-{backup_id}.json",
                            {
                                "restored": False,
                                "previous_state": "ready",
                                "previous_error": "",
                                "previous_progress": 100,
                                "proposal_mode": True,
                                "model": config["translation_model"],
                                "cues": [
                                    {"id": c.id, "before": c.original, "after": None}
                                    for c in cues
                                ],
                            },
                        )
                        item.improvement_id = backup_id
                        project.state, project.progress, project.error = (
                            "improve_queued",
                            0,
                            "",
                        )
                        db.commit()
                    backup_id = item.improvement_id
                improve_project(pid, backup_id)
                with SessionLocal() as db:
                    project = db.get(Project, pid)
                    if project.state == "paused":
                        batch_transition(item_id, stage, "paused")
                        return
                    if project.state != "ready":
                        raise ValueError(project.error or "La mejora no ha terminado")
                batch_transition(item_id, "review")
            elif stage == "review":
                with SessionLocal() as db:
                    reviews = db.scalars(
                        select(CueReview)
                        .join(Cue, CueReview.cue_id == Cue.id)
                        .where(Cue.project_id == pid)
                    ).all()
                    if any(
                        (review.flag and not review.flag_resolved)
                        or review.proposal is not None
                        for review in reviews
                    ):
                        batch_transition(item_id, stage, "review")
                        return
                batch_transition(item_id, "translate")
            elif stage == "translate":
                with SessionLocal() as db:
                    project = db.scalar(
                        select(Project).where(Project.id == pid).with_for_update()
                    )
                    if project.state in ("ready", "failed", "cancelled"):
                        batch_write_workflow(pid, action="translate")
                        project.state, project.progress, project.error = "queued", 0, ""
                        db.commit()
                    elif project.state != "queued":
                        raise ValueError("El proyecto no está disponible para traducir")
                process_project(pid)
                with SessionLocal() as db:
                    project = db.get(Project, pid)
                    if project.state == "paused":
                        batch_transition(item_id, stage, "paused")
                        return
                    if project.state != "ready":
                        raise ValueError(
                            project.error or "La traducción no ha terminado"
                        )
                batch_transition(item_id, "export")
            elif stage == "export":
                if config.get("export_when_clean"):
                    with SessionLocal() as db:
                        cues = db.scalars(
                            select(Cue)
                            .where(Cue.project_id == pid)
                            .order_by(Cue.position)
                        ).all()
                        if not cues or any(
                            not (cue.translated or "").strip() for cue in cues
                        ):
                            raise ValueError("Faltan traducciones para exportar")
                        content = export(cues, "es", False)
                    languages = {
                        "Spanish": "es",
                        "Romanian": "ro",
                        "English": "en",
                        "Portuguese": "pt",
                        "French": "fr",
                        "Italian": "it",
                        "German": "de",
                        "Dutch": "nl",
                        "Japanese": "ja",
                        "Chinese": "zh",
                    }
                    mac_post(
                        "/files/export",
                        {
                            "project_id": pid,
                            "content": content,
                            "language": languages[
                                config.get("target_language", "Spanish")
                            ],
                            "format": "srt",
                        },
                    )
                batch_transition(item_id, "done", "done")
                return
            else:
                raise ValueError("Etapa de lote desconocida")
    except Exception as exc:
        with SessionLocal() as db:
            item = db.get(BatchItem, item_id)
            project = db.get(Project, pid)
            cancelled = bool(item and item.status == "cancelling")
            if item:
                item.status, item.error = ("cancelled", "") if cancelled else ("failed", str(exc)[:3000])
            if project and project.state in (
                "batch_queued",
                "queued",
                "transcribing",
                "translating",
                "improve_queued",
                "improving",
            ):
                project.state, project.error = ("cancelled", "") if cancelled else ("failed", str(exc)[:3000])
            db.commit()
        log.exception("Batch item %s failed", item_id)


def improve_project(pid, backup_id):
    path = Path(DATA) / pid / f"improvement-{uuid.UUID(backup_id)}.json"
    latest, _ = improvement.latest(pid)
    if latest != path:
        return
    with SessionLocal() as db:
        claimed = db.execute(
            update(Project)
            .where(Project.id == pid, Project.state == "improve_queued")
            .values(state="improving")
        )
        db.commit()
        if claimed.rowcount != 1:
            return
    try:
        task_boundary(pid)
        backup = json.loads(path.read_text())
        items = backup["cues"]
        proposal_mode = backup.get("proposal_mode", False)
        for start in range(0, len(items), 6):
            task_boundary(pid)
            with SessionLocal() as db:
                batch = []
                for item in items[start : start + 6]:
                    cue = db.get(Cue, item["id"])
                    if not cue or cue.project_id != pid:
                        raise ValueError("El segmento ya no está disponible")
                    if proposal_mode:
                        review = db.get(CueReview, cue.id)
                        if (
                            item.get("after") is not None
                            and review
                            and review.proposal == item["after"]
                            and review.proposal_source == item["before"]
                        ):
                            continue
                    elif (
                        item.get("after") is not None and cue.original == item["after"]
                    ):
                        continue
                    if cue.original != item["before"]:
                        raise ValueError("El texto cambió durante la mejora")
                    batch.append(item)
            if not batch:
                continue
            texts = [item["before"] for item in batch]
            context = " ".join(
                item["before"] for item in items[max(0, start - 3) : start]
            )
            request = {"texts": texts, "context": context}
            if backup.get("model"):
                request["model"] = backup["model"]
            corrected = mac_post(
                "/improve",
                request,
                timeout=(10, 900),
                should_stop=lambda: task_boundary(pid),
            )["texts"]
            if len(corrected) != len(batch) or not all(
                isinstance(x, str) and x.strip() for x in corrected
            ):
                raise ValueError("La mejora devolvió líneas inválidas")
            # Write ahead: recovery can distinguish unchanged and corrected values after interruption.
            for item, value in zip(batch, corrected):
                item["after"] = value
            improvement.write(path, backup)
            with SessionLocal() as db:
                for item in batch:
                    cue = db.get(Cue, item["id"])
                    if (
                        not cue
                        or cue.project_id != pid
                        or cue.original != item["before"]
                    ):
                        raise ValueError("El texto cambió durante la mejora")
                    if proposal_mode:
                        review = db.get(CueReview, cue.id)
                        if not review:
                            review = CueReview(cue_id=cue.id)
                            db.add(review)
                        review.proposal = item["after"]
                        review.proposal_source = item["before"]
                    else:
                        cue.original = item["after"]
                db.commit()
            set_status(
                pid,
                "improving",
                int(100 * min(start + 6, len(items)) / len(items)),
            )
            task_boundary(pid)
        task_boundary(pid)
        set_status(
            pid,
            backup.get("previous_state", "ready"),
            100,
            backup.get("previous_error", ""),
        )
        task_boundary(pid)
    except TaskStopped:
        return
    except Exception as exc:
        try:
            task_boundary(pid)
        except TaskStopped:
            return
        set_status(pid, "failed", 0, f"Mejora incompleta: {exc}. Puedes revertirla.")
        try:
            task_boundary(pid)
        except TaskStopped:
            return
        raise


class ForkSafeWorker(Worker):
    def main_work_horse(self, job, queue):
        # RQ forks once per job; never use the parent's pooled PostgreSQL sockets.
        engine.dispose(close=False)
        return super().main_work_horse(job, queue)


if __name__ == "__main__":
    initialize()
    redis = Redis.from_url(os.environ["REDIS_URL"])
    ForkSafeWorker(
        [Queue("subtitles", connection=redis)],
        connection=redis,
        name=socket.gethostname(),
    ).work()
