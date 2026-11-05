import os
import uuid
import requests
import socket
import json
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
    engine,
)
from app.subtitles import parse_srt
from app.project_sources import reference
from app import improvement
from app.core import DATA

MAC_URL = os.environ.get("MAC_URL", "http://host.docker.internal:8765")
TOKEN = os.environ.get("MAC_TOKEN", "")


def set_status(pid, state, progress=0, error=""):
    with SessionLocal() as db:
        p = db.get(Project, pid)
        if p:
            p.state = state
            p.progress = progress
            p.error = error[:3000]
            db.commit()


def mac_post(path, json, timeout=14400):
    r = requests.post(
        MAC_URL + path, json=json, headers={"X-Worker-Token": TOKEN}, timeout=timeout
    )
    if not r.ok:
        try:
            detail = r.json().get("detail", r.reason)
        except ValueError:
            detail = r.reason
        raise RuntimeError(f"Gateway {path}: {detail}")
    return r.json()


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
            result = mac_post("/transcribe", request)
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
            set_status(pid, "ready", 100)
            return
        set_status(pid, "translating", 55)
        with SessionLocal() as db:
            records = db.scalars(
                select(Cue).where(Cue.project_id == pid).order_by(Cue.position)
            ).all()
            originals = [c.original for c in records]
            pending = [
                (i, c.id, c.original)
                for i, c in enumerate(records)
                if not (c.translated or "").strip()
            ]
        completed = len(records) - len(pending)
        for k in range(0, len(pending), 6):
            batch = pending[k : k + 6]
            part = [entry[2] for entry in batch]
            first = batch[0][0]
            context = " ".join(originals[max(0, first - 3) : first])
            answer = mac_post(
                "/translate", {"texts": part, "context": context}, timeout=900
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
        set_status(pid, "ready", 100)
    except Exception as exc:
        set_status(pid, "failed", 0, str(exc))
        raise


def transcribe_incrementally(pid, info):
    while True:
        with SessionLocal() as db:
            checkpoint = db.get(TranscriptionProgress, pid)
            if checkpoint.completed:
                return
            start = checkpoint.next_start
        request = {"project_id": pid, "segment_start": start}
        if info.get("audio_index") is not None:
            request["audio_index"] = info["audio_index"]
        if info.get("asr_language"):
            request["language"] = info["asr_language"]
        result = mac_post("/transcribe-chunk", request)
        srt = result.get("srt")
        if not isinstance(srt, str):
            raise ValueError("El gateway devolvió un subtítulo inválido")
        new_cues = parse_srt(srt)
        if srt.strip() and not new_cues:
            raise ValueError("El gateway devolvió marcas de tiempo inválidas")
        if not isinstance(result.get("end_of_audio"), bool):
            raise ValueError("El gateway no indicó el final del audio")
        with SessionLocal() as db:
            checkpoint = db.get(TranscriptionProgress, pid)
            if checkpoint.next_start != start or checkpoint.completed:
                raise ValueError("La transcripción cambió durante el procesamiento")
            existing = db.scalars(
                select(Cue).where(Cue.project_id == pid).order_by(Cue.position)
            ).all()
            for i, cue in enumerate(new_cues, start=len(existing)):
                if cue["start"] < start or cue["end"] > start + 30.001:
                    raise ValueError(
                        "La transcripción devolvió tiempos fuera del tramo"
                    )
                db.add(Cue(id=str(uuid.uuid4()), project_id=pid, position=i, **cue))
            checkpoint.next_start = start + 30
            checkpoint.completed = int(result["end_of_audio"])
            if result.get("language"):
                db.get(Project, pid).language = result["language"]
            db.commit()


def improve_project(pid, backup_id):
    with SessionLocal() as db:
        claimed = db.execute(
            update(Project)
            .where(Project.id == pid, Project.state == "improve_queued")
            .values(state="improving")
        )
        db.commit()
        if claimed.rowcount != 1:
            return
    path = Path(DATA) / pid / f"improvement-{uuid.UUID(backup_id)}.json"
    try:
        backup = json.loads(path.read_text())
        items = backup["cues"]
        for start in range(0, len(items), 6):
            batch = items[start : start + 6]
            texts = [item["before"] for item in batch]
            context = " ".join(
                item["before"] for item in items[max(0, start - 3) : start]
            )
            corrected = mac_post(
                "/improve", {"texts": texts, "context": context}, timeout=900
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
                    cue.original = item["after"]
                db.commit()
            set_status(
                pid,
                "improving",
                int(100 * min(start + len(batch), len(items)) / len(items)),
            )
        set_status(
            pid,
            backup.get("previous_state", "ready"),
            100,
            backup.get("previous_error", ""),
        )
    except Exception as exc:
        set_status(pid, "failed", 0, f"Mejora incompleta: {exc}. Puedes revertirla.")
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
