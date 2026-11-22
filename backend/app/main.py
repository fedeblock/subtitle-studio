import uuid
import time
import pathlib
import json
import re
import anyio
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Request
from fastapi.responses import (
    FileResponse,
    PlainTextResponse,
    StreamingResponse,
    Response,
)
from starlette.background import BackgroundTask
from typing import Literal
from app.native import native_request, MAC_URL, TOKEN
from app.project_sources import reference, save_workflow
from app import improvement
from pydantic import BaseModel, Field
from sqlalchemy import select, text, update
from app.core import (
    initialize,
    SessionLocal,
    Project,
    Cue,
    HiddenProject,
    TranscriptionProgress,
    TaskControl,
    CueReview,
    ComparisonSnapshot,
    Recipe,
    Batch,
    BatchItem,
    queue,
    DATA,
)
from app.subtitles import export, parse_srt

MAX_BYTES = 2 * 1024 * 1024 * 1024
ALLOWED = {".mp4", ".mov", ".mkv", ".mp3", ".wav", ".m4a", ".webm", ".flac"}


@asynccontextmanager
async def lifespan(app):
    pathlib.Path(DATA).mkdir(exist_ok=True, parents=True)
    initialize()
    yield


app = FastAPI(title="Subtitle Studio API", lifespan=lifespan)


def as_project(p, db=None):
    result = {
        k: getattr(p, k)
        for k in [
            "id",
            "name",
            "filename",
            "state",
            "progress",
            "error",
            "language",
            "created",
        ]
    }
    info = reference(p.id) if p.filename == "source.json" else {}
    name = pathlib.Path(p.name).stem
    episode = re.search(
        r"(?i)(?:\b|[._ -])s(\d{1,2})e(\d{1,3})\b|(?:\b|[._ -])(\d{1,2})x(\d{1,3})\b",
        name,
    )
    year = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", name)
    serie = (
        re.sub(r"[._]+", " ", name[: episode.start()]).strip(" -") if episode else None
    )
    counts = {"cues": 0, "untranslated": 0, "flagged_open": 0, "proposals": 0}
    if db:
        rows = db.execute(
            select(Cue, CueReview)
            .outerjoin(CueReview, CueReview.cue_id == Cue.id)
            .where(Cue.project_id == p.id)
        ).all()
        counts = {
            "cues": len(rows),
            "untranslated": sum(not (cue.translated or "").strip() for cue, _ in rows),
            "flagged_open": sum(
                bool(review and review.flag and not review.flag_resolved)
                for _, review in rows
            ),
            "proposals": sum(bool(review and review.proposal) for _, review in rows),
        }
    backup_path, _ = improvement.latest(p.id)
    progress = None
    if db and p.state == "transcribing":
        checkpoint = db.get(TranscriptionProgress, p.id)
        if checkpoint:
            progress = {
                "processed_seconds": checkpoint.next_start,
                "processed_until": checkpoint.next_start,
                "chunk": checkpoint.next_start // 30
                + (0 if checkpoint.completed else 1),
                "chunks_total": None,
                "eta_seconds": None,
                "completed": bool(checkpoint.completed),
            }
    elif db and p.state == "translating":
        cues = db.scalars(select(Cue).where(Cue.project_id == p.id)).all()
        progress = {
            "done": sum(bool((cue.translated or "").strip()) for cue in cues),
            "total": len(cues),
        }
    elif p.state == "improving":
        progress = {"percent": max(0, min(100, p.progress or 0))}
        if backup_path and (p.progress or 0) > 0:
            try:
                progress["updated_at"] = backup_path.stat().st_mtime
            except OSError:
                pass
    result.update(
        serie=serie,
        season=int(episode.group(1) or episode.group(3)) if episode else None,
        episode=int(episode.group(2) or episode.group(4)) if episode else None,
        year=int(year.group(1)) if year and not episode else None,
        counts=counts,
        source_kind="reference" if p.filename == "source.json" else "copy",
        subtitle_options=[
            {
                k: v
                for k, v in c.items()
                if k
                in (
                    "id",
                    "kind",
                    "label",
                    "supported",
                    "reason",
                    "match",
                    "recommended",
                    "language",
                )
            }
            for c in info.get("subtitles", [])
        ],
        audio_tracks=info.get("audio_tracks", []),
        audio_index=info.get("audio_index"),
        source_warnings=info.get("warnings", []),
        action=info.get("action", "translate"),
        prefer_asr=info.get("prefer_asr", False),
        asr_language=info.get("asr_language"),
        asr_model=info.get("asr_model", "qwen"),
        target_language=info.get("target_language", "Spanish"),
        translation_language_known=bool(info.get("target_language")),
        translation_model=info.get("translation_model"),
        timing_warnings=info.get("timing_warnings", []),
        can_undo_improvement=backup_path is not None,
        task_progress=progress,
    )
    if db:
        item = db.scalar(
            select(BatchItem)
            .where(
                BatchItem.project_id == p.id,
                BatchItem.status.not_in(("done", "cancelled")),
            )
            .limit(1)
        )
        result["batch"] = (
            {
                "id": item.batch_id,
                "item_id": item.id,
                "status": item.status,
                "stage": item.stage,
            }
            if item
            else None
        )
    return result


def as_cue(c, review=None):
    result = {
        k: getattr(c, k)
        for k in ["id", "position", "start", "end", "original", "translated"]
    }
    result.update(
        flag=review.flag if review else None,
        flag_resolved=bool(review.flag_resolved) if review else False,
        proposal=review.proposal if review else None,
    )
    return result


@app.get("/api/health")
def health():
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        queue().connection.ping()
    except Exception as exc:
        raise HTTPException(503, "Base de datos o cola no disponible") from exc
    return {"ok": True}


@app.get("/api/projects")
def projects(hidden: bool = False):
    with SessionLocal() as db:
        hidden_ids = select(HiddenProject.project_id)
        statement = (
            select(Project)
            .where(
                Project.id.in_(hidden_ids) if hidden else Project.id.not_in(hidden_ids)
            )
            .order_by(Project.created.desc())
        )
        return [as_project(x, db) for x in db.scalars(statement).all()]


def require_local_action(request: Request):
    if request.headers.get("X-Studio-Local") != "1":
        raise HTTPException(403, "Acción local requerida")


class RecipeConfig(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    source_pref: Literal["recommended", "english", "asr"] = "recommended"
    asr_model: Literal["qwen", "whisper"] = "qwen"
    asr_language: str | None = Field(default=None, max_length=64)
    target_language: Literal[
        "Spanish",
        "Romanian",
        "English",
        "Portuguese",
        "French",
        "Italian",
        "German",
        "Dutch",
        "Japanese",
        "Chinese",
    ] = "Spanish"
    translation_model: str = Field(min_length=1, max_length=200)
    improve_before_translate: bool = False
    flag_suspicious: bool = True
    export_when_clean: bool = False


@app.get("/api/recipes")
def list_recipes():
    with SessionLocal() as db:
        return [
            {"id": item.id, **json.loads(item.config)}
            for item in db.scalars(select(Recipe).order_by(Recipe.created)).all()
        ]


@app.post("/api/recipes")
def create_recipe(body: RecipeConfig, request: Request):
    require_local_action(request)
    recipe_id = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(Recipe(id=recipe_id, config=body.model_dump_json(), created=time.time()))
        db.commit()
    return {"id": recipe_id, **body.model_dump()}


class CreateBatch(BaseModel):
    project_ids: list[str] = Field(min_length=1, max_length=100)
    recipe_id: str = Field(min_length=1, max_length=64)


@app.post("/api/batches")
def create_batch(body: CreateBatch, request: Request):
    require_local_action(request)
    if len(set(body.project_ids)) != len(body.project_ids):
        raise HTTPException(422, "Hay proyectos repetidos en el lote")
    batch_id = str(uuid.uuid4())
    item_ids = []
    with SessionLocal() as db:
        recipe = db.get(Recipe, body.recipe_id)
        if not recipe:
            raise HTTPException(404, "No se encontró la receta")
        for pid in sorted(body.project_ids):
            project = db.scalar(
                select(Project).where(Project.id == pid).with_for_update()
            )
            if not project:
                raise HTTPException(404, "No se encontró un proyecto del lote")
            require_visible(db, pid)
            if project.state != "draft" or project.filename != "source.json":
                raise HTTPException(
                    409, "El lote solo admite proyectos locales sin iniciar"
                )
            existing = db.scalar(
                select(BatchItem.id)
                .where(
                    BatchItem.project_id == pid,
                    BatchItem.status.not_in(("done", "cancelled")),
                )
                .limit(1)
            )
            if existing:
                raise HTTPException(409, "Un proyecto ya pertenece a otro lote activo")
        db.add(
            Batch(
                id=batch_id,
                recipe_id=recipe.id,
                recipe=recipe.config,
                paused=0,
                created=time.time(),
            )
        )
        db.flush()
        for position, pid in enumerate(body.project_ids):
            item_id = str(uuid.uuid4())
            item_ids.append(item_id)
            db.add(
                BatchItem(
                    id=item_id,
                    batch_id=batch_id,
                    project_id=pid,
                    position=position,
                    status="queued",
                    stage="source",
                    error="",
                )
            )
            db.get(Project, pid).state = "batch_queued"
        db.commit()
    failed = []
    for item_id in item_ids:
        try:
            queue().enqueue("app.worker.process_batch_item", item_id, job_timeout=14400)
        except Exception:
            failed.append(item_id)
    if failed:
        with SessionLocal() as db:
            for item_id in failed:
                item = db.get(BatchItem, item_id)
                if item and item.status == "queued":
                    item.status, item.error = (
                        "failed",
                        "No se pudo confirmar el envío a la cola.",
                    )
            db.commit()
    return {"id": batch_id, "enqueue_failed": len(failed)}


@app.get("/api/batches/{batch_id}")
def get_batch(batch_id: str):
    with SessionLocal() as db:
        batch = db.get(Batch, batch_id)
        if not batch:
            raise HTTPException(404, "No se encontró el lote")
        items = db.scalars(
            select(BatchItem)
            .where(BatchItem.batch_id == batch_id)
            .order_by(BatchItem.position)
        ).all()
        return {
            "id": batch.id,
            "paused": bool(batch.paused),
            "recipe": json.loads(batch.recipe),
            "items": [
                {
                    "id": item.id,
                    "status": item.status,
                    "stage": item.stage,
                    "error": item.error,
                    "project": as_project(db.get(Project, item.project_id), db),
                }
                for item in items
            ],
        }


def enqueue_batch_items(item_ids):
    failed = []
    for item_id in item_ids:
        try:
            queue().enqueue("app.worker.process_batch_item", item_id, job_timeout=14400)
        except Exception:
            failed.append(item_id)
    if failed:
        with SessionLocal() as db:
            for item_id in failed:
                item = db.get(BatchItem, item_id)
                if item and item.status == "queued":
                    item.status, item.error = (
                        "failed",
                        "No se pudo confirmar el envío a la cola.",
                    )
            db.commit()
    return len(failed)


@app.post("/api/batches/{batch_id}/pause")
def pause_batch(batch_id: str, request: Request):
    require_local_action(request)
    running = []
    with SessionLocal() as db:
        batch = db.scalar(select(Batch).where(Batch.id == batch_id).with_for_update())
        if not batch:
            raise HTTPException(404, "No se encontró el lote")
        batch.paused = 1
        items = db.scalars(
            select(BatchItem).where(BatchItem.batch_id == batch_id)
        ).all()
        for item in items:
            if item.status == "queued":
                item.status = "paused"
            elif item.status == "running":
                running.append(item.project_id)
        db.commit()
    for pid in running:
        try:
            request_task_stop(pid, "pause", request)
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
    return {"paused": True}


@app.post("/api/batches/{batch_id}/resume")
def resume_batch(batch_id: str, request: Request):
    require_local_action(request)
    ready = []
    with SessionLocal() as db:
        batch = db.scalar(select(Batch).where(Batch.id == batch_id).with_for_update())
        if not batch:
            raise HTTPException(404, "No se encontró el lote")
        items = db.scalars(
            select(BatchItem).where(BatchItem.batch_id == batch_id)
        ).all()
        if any(
            item.status == "running"
            and db.get(Project, item.project_id).state == "pausing"
            for item in items
        ):
            raise HTTPException(409, "Espera a que termine de pausarse el tramo actual")
        batch.paused = 0
        for item in items:
            if item.status != "paused":
                continue
            project = db.get(Project, item.project_id)
            if project.state == "paused":
                project.state = (
                    "improve_queued" if item.stage == "improve" else "queued"
                )
                project.error = ""
            item.status = "queued"
            ready.append(item.id)
        db.commit()
    return {"paused": False, "enqueue_failed": enqueue_batch_items(ready)}


@app.post("/api/batches/{batch_id}/items/{item_id}/continue")
def continue_batch_item(batch_id: str, item_id: str, request: Request):
    require_local_action(request)
    with SessionLocal() as db:
        batch = db.scalar(select(Batch).where(Batch.id == batch_id).with_for_update())
        item = db.scalar(
            select(BatchItem)
            .where(BatchItem.id == item_id, BatchItem.batch_id == batch_id)
            .with_for_update()
        )
        if not batch or not item:
            raise HTTPException(404, "No se encontró el episodio del lote")
        if batch.paused or item.status != "review":
            raise HTTPException(
                409, "El episodio no está esperando revisión o la cola está pausada"
            )
        require_visible(db, item.project_id)
        reviews = db.scalars(
            select(CueReview)
            .join(Cue, CueReview.cue_id == Cue.id)
            .where(Cue.project_id == item.project_id)
        ).all()
        if any(
            (review.flag and not review.flag_resolved) or review.proposal is not None
            for review in reviews
        ):
            raise HTTPException(
                409, "Aún quedan segmentos o propuestas pendientes de revisar"
            )
        item.status, item.error = "queued", ""
        db.commit()
    return {"enqueue_failed": enqueue_batch_items([item_id])}


@app.post("/api/batches/{batch_id}/items/{item_id}/retry")
def retry_batch_item(batch_id: str, item_id: str, request: Request):
    require_local_action(request)
    with SessionLocal() as db:
        batch = db.scalar(select(Batch).where(Batch.id == batch_id).with_for_update())
        item = db.scalar(
            select(BatchItem)
            .where(BatchItem.id == item_id, BatchItem.batch_id == batch_id)
            .with_for_update()
        )
        if not batch or not item:
            raise HTTPException(404, "No se encontró el episodio del lote")
        if batch.paused or item.status != "failed":
            raise HTTPException(
                409, "El episodio no se puede reintentar en este momento"
            )
        require_visible(db, item.project_id)
        project = db.scalar(
            select(Project).where(Project.id == item.project_id).with_for_update()
        )
        if project.state not in ("failed", "batch_queued", "queued", "ready"):
            raise HTTPException(409, "El proyecto está ocupado")
        if item.stage == "source":
            project.state = "batch_queued"
        elif item.stage in ("process", "translate"):
            project.state = "queued"
        elif item.stage == "improve":
            project.state = "improve_queued" if item.improvement_id else "ready"
        else:
            project.state = "ready"
        project.error = ""
        item.status, item.error = "queued", ""
        db.commit()
    return {"enqueue_failed": enqueue_batch_items([item_id])}


@app.post("/api/batches/{batch_id}/items/{item_id}/cancel")
def cancel_batch_item(batch_id: str, item_id: str, request: Request):
    require_local_action(request)
    running = False
    with SessionLocal() as db:
        item = db.scalar(select(BatchItem).where(BatchItem.id == item_id, BatchItem.batch_id == batch_id).with_for_update())
        if not item:
            raise HTTPException(404, "No se encontró el episodio del lote")
        if item.status in ("done", "cancelled"):
            raise HTTPException(409, "El episodio ya ha terminado")
        project = db.scalar(select(Project).where(Project.id == item.project_id).with_for_update())
        if item.status == "running":
            item.status = "cancelling"
            running = True
        else:
            item.status = "cancelled"
            if item.stage == "source" and project.state in ("batch_queued", "failed"):
                project.state, project.error = "draft", ""
            elif project.state in ("queued", "paused", "improve_queued"):
                project.state = "cancelled"
        pid = project.id
        db.commit()
    if running:
        try:
            request_task_stop(pid, "cancel", request)
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
    return {"state": "cancelling" if running else "cancelled"}


def require_visible(db, pid):
    if db.get(HiddenProject, pid):
        raise HTTPException(
            409, "Restaura el proyecto de la papelera antes de procesarlo"
        )


ACTIVE_STATES = {
    "batch_queued",
    "queued",
    "transcribing",
    "translating",
    "improve_queued",
    "improving",
    "pausing",
    "cancelling",
}


def request_task_stop(pid, action, request):
    require_local_action(request)
    with SessionLocal() as db:
        p = db.scalar(select(Project).where(Project.id == pid).with_for_update())
        if not p:
            raise HTTPException(404)
        require_visible(db, pid)
        if action == "cancel" and p.state == "paused":
            p.state = "cancelled"
        else:
            allowed = {
                "queued",
                "transcribing",
                "translating",
                "improve_queued",
                "improving",
            }
            if action == "cancel":
                allowed.add("pausing")
            if p.state not in allowed:
                raise HTTPException(409, "No hay una tarea que se pueda detener")
            if p.state != "pausing":
                kind = (
                    "improve"
                    if p.state in ("improve_queued", "improving")
                    else "process"
                )
                backup_id = None
                if kind == "improve":
                    path, _ = improvement.latest(pid)
                    if not path:
                        raise HTTPException(
                            409, "No se encuentra la copia de recuperación"
                        )
                    backup_id = path.stem.removeprefix("improvement-")
                control = db.get(TaskControl, pid)
                if not control:
                    control = TaskControl(
                        project_id=pid, kind=kind, backup_id=backup_id
                    )
                    db.add(control)
                else:
                    control.kind, control.backup_id = kind, backup_id
            immediate = p.state in ("queued", "improve_queued")
            p.state = (
                ("paused" if action == "pause" else "cancelled")
                if immediate
                else ("pausing" if action == "pause" else "cancelling")
            )
        db.commit()
        return {"state": p.state}


@app.post("/api/projects/{pid}/pause")
def pause_task(pid: str, request: Request):
    return request_task_stop(pid, "pause", request)


@app.post("/api/projects/{pid}/cancel")
def cancel_task(pid: str, request: Request):
    return request_task_stop(pid, "cancel", request)


@app.post("/api/projects/{pid}/resume")
def resume_task(pid: str, request: Request):
    require_local_action(request)
    with SessionLocal() as db:
        p = db.scalar(select(Project).where(Project.id == pid).with_for_update())
        if not p:
            raise HTTPException(404)
        require_visible(db, pid)
        control = db.get(TaskControl, pid)
        if p.state != "paused" or not control:
            raise HTTPException(409, "No hay una tarea pausada para reanudar")
        kind, backup_id = control.kind, control.backup_id
        if kind == "improve" and not backup_id:
            raise HTTPException(409, "Falta la copia de recuperación de la mejora")
        p.state = "improve_queued" if kind == "improve" else "queued"
        p.error = ""
        db.commit()
    try:
        if kind == "improve":
            queue().enqueue(
                "app.worker.improve_project", pid, backup_id, job_timeout=14400
            )
        else:
            queue().enqueue("app.worker.process_project", pid, job_timeout=14400)
    except Exception as exc:
        with SessionLocal() as db:
            p = db.scalar(select(Project).where(Project.id == pid).with_for_update())
            if p and p.state in ("queued", "improve_queued"):
                p.state = "paused"
                db.commit()
        raise HTTPException(
            503, "No se pudo reanudar; se conserva el trabajo pausado"
        ) from exc
    return {"id": pid}


@app.delete("/api/projects/{pid}")
def hide_project(pid: str):
    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.id == pid).with_for_update())
        if not project:
            raise HTTPException(404)
        if project.state in ACTIVE_STATES:
            raise HTTPException(
                409, "Espera a que termine el procesamiento antes de quitar el proyecto"
            )
        if not db.get(HiddenProject, pid):
            db.add(HiddenProject(project_id=pid))
            db.commit()
    return {"ok": True}


@app.post("/api/projects/{pid}/restore")
def restore_project(pid: str):
    with SessionLocal() as db:
        hidden = db.get(HiddenProject, pid)
        if not hidden:
            raise HTTPException(404, "El proyecto no está en la papelera")
        db.delete(hidden)
        db.commit()
    return {"ok": True}


@app.post("/api/library/clear")
def clear_library(request: Request):
    require_local_action(request)
    with SessionLocal() as db:
        hidden_ids = select(HiddenProject.project_id)
        projects = db.scalars(
            select(Project).where(Project.id.not_in(hidden_ids)).with_for_update()
        ).all()
        skipped = 0
        removed = 0
        for project in projects:
            # The project lock can have waited for another request that hid it.
            if db.get(HiddenProject, project.id):
                continue
            if project.state in ACTIVE_STATES:
                skipped += 1
            else:
                db.add(HiddenProject(project_id=project.id))
                removed += 1
        db.commit()
    return {"removed": removed, "active": skipped}


@app.post("/api/library/restore")
def restore_library(request: Request):
    require_local_action(request)
    with SessionLocal() as db:
        hidden = db.scalars(select(HiddenProject)).all()
        for entry in hidden:
            db.delete(entry)
        db.commit()
    return {"restored": len(hidden)}


def enqueue_project(pid):
    try:
        queue().enqueue("app.worker.process_project", pid, job_timeout=14400)
    except Exception as exc:
        with SessionLocal() as db:
            # Enqueue can have succeeded before the connection failed.
            db.execute(
                update(Project)
                .where(Project.id == pid, Project.state == "queued")
                .values(
                    state="failed",
                    error="No se pudo confirmar el envío a la cola; archivo conservado.",
                )
            )
            db.commit()
        raise HTTPException(
            503, f"Cola no disponible. Proyecto conservado: {pid}"
        ) from exc


@app.post("/api/projects")
async def upload(file: UploadFile = File(...)):
    name = pathlib.Path(file.filename or "").name
    ext = pathlib.Path(name).suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(400, "Formato no admitido")
    pid = str(uuid.uuid4())
    folder = pathlib.Path(DATA) / pid
    folder.mkdir(parents=True)
    dest = folder / ("source" + ext)
    n = 0
    persisted = False
    try:
        with dest.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                n += len(chunk)
                if n > MAX_BYTES:
                    raise HTTPException(413, "Archivo demasiado grande (2 GB máximo)")
                out.write(chunk)
        if n == 0:
            raise HTTPException(400, "Archivo vacío")
        with SessionLocal() as db:
            db.add(
                Project(
                    id=pid,
                    name=name,
                    filename=dest.name,
                    state="queued",
                    created=time.time(),
                )
            )
            db.commit()
        persisted = True
        enqueue_project(pid)
        return {"id": pid}
    except Exception:
        if not persisted and dest.exists():
            dest.unlink()
            folder.rmdir()
        raise
    finally:
        await file.close()


@app.post("/api/projects/local")
def open_local(request: Request):
    # A custom header prevents cross-origin pages from opening native dialogs.
    if request.headers.get("X-Studio-Local") != "1":
        raise HTTPException(403, "Acción local requerida")
    pid = str(uuid.uuid4())
    response = native_request(
        "POST", "/files/select", json={"project_id": pid}, timeout=(5, 330)
    )
    if response.status_code == 204:
        return Response(status_code=204)
    selected = response.json()
    with SessionLocal() as db:
        db.add(
            Project(
                id=pid,
                name=selected["name"],
                filename="source.json",
                state="draft",
                created=time.time(),
            )
        )
        db.commit()
    return {"id": pid}


@app.post("/api/projects/local-many")
def open_local_many(request: Request):
    require_local_action(request)
    response = native_request("POST", "/files/select-many", timeout=(5, 330))
    if response.status_code == 204:
        return Response(status_code=204)
    result = response.json()
    entries = result.get("projects")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
        raise HTTPException(502, "El selector devolvió una lista inválida")
    try:
        clean = [
            {"id": str(uuid.UUID(item["id"])), "name": pathlib.Path(item["name"]).name}
            for item in entries
            if item["filename"] == "source.json"
        ]
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(502, "El selector devolvió referencias inválidas") from exc
    if (
        len(clean) != len(entries)
        or len({item["id"] for item in clean}) != len(clean)
        or any(not item["name"] for item in clean)
    ):
        raise HTTPException(502, "El selector devolvió referencias inválidas")
    with SessionLocal() as db:
        for item in clean:
            db.add(
                Project(
                    id=item["id"],
                    name=item["name"],
                    filename="source.json",
                    state="draft",
                    created=time.time(),
                )
            )
        db.commit()
    return {"projects": clean, "errors": result.get("errors", [])}


class StartRequest(BaseModel):
    source: str = Field(min_length=1, max_length=64)
    action: Literal["translate", "edit"] = "translate"
    audio_index: int | None = Field(default=None, ge=0)
    asr_language: str | None = Field(default=None, min_length=1, max_length=64)
    asr_model: Literal["qwen", "whisper"] = "qwen"


@app.post("/api/projects/{pid}/retranscribe")
def retranscribe_project(pid: str, request: Request):
    require_local_action(request)
    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.id == pid).with_for_update())
        if not project:
            raise HTTPException(404)
        require_visible(db, pid)
        if project.state not in ("ready", "failed", "cancelled"):
            raise HTTPException(409, "Espera a que termine el procesamiento")
        if project.filename != "source.json":
            raise HTTPException(
                400, "Este proyecto no conserva una referencia al archivo original"
            )
        info = reference(pid)
        if not info.get("path"):
            raise HTTPException(400, "No se encontró la referencia al archivo original")
        new_id = str(uuid.uuid4())
        folder = pathlib.Path(DATA) / new_id
        folder.mkdir(parents=True)
        info.update(prefer_asr=True, timing_warnings=[])
        (folder / "source.json").write_text(json.dumps(info, ensure_ascii=False))
        db.add(
            Project(
                id=new_id,
                name=f"{project.name.split(' · nueva transcripción')[0]} · nueva transcripción",
                filename="source.json",
                state="draft",
                created=time.time(),
            )
        )
        db.commit()
    return {"id": new_id}


class CompareRequest(BaseModel):
    segment_start: int = Field(ge=0)
    audio_index: int | None = Field(default=None, ge=0)
    language: str | None = Field(default=None, min_length=1, max_length=64)


def require_idle_projects(db):
    if db.scalar(select(Project.id).where(Project.state.in_(ACTIVE_STATES)).limit(1)):
        raise HTTPException(409, "Espera a que terminen los trabajos activos")


@app.get("/api/models")
def models():
    response = native_request("GET", "/models")
    return response.json()


@app.post("/api/models/{model}/download")
def download_model(model: Literal["qwen", "whisper"], request: Request):
    require_local_action(request)
    with SessionLocal() as db:
        require_idle_projects(db)
    return native_request("POST", f"/models/{model}/download", timeout=(5, 7200)).json()


@app.delete("/api/models/{model}")
def delete_model(model: Literal["qwen", "whisper"], request: Request):
    require_local_action(request)
    with SessionLocal() as db:
        require_idle_projects(db)
    return native_request("DELETE", f"/models/{model}", timeout=(5, 120)).json()


@app.post("/api/projects/{pid}/compare-models")
def compare_models(pid: str, body: CompareRequest, request: Request):
    require_local_action(request)
    with SessionLocal() as db:
        project = db.get(Project, pid)
        if not project:
            raise HTTPException(404)
        require_visible(db, pid)
        require_idle_projects(db)
        if body.audio_index is not None and body.audio_index not in [
            track["index"] for track in reference(pid).get("audio_tracks", [])
        ]:
            raise HTTPException(400, "Pista de audio no encontrada")
    payload = {"project_id": pid, **body.model_dump()}
    return native_request(
        "POST", "/compare-models", json=payload, timeout=(5, 7200)
    ).json()


@app.get("/api/projects/{pid}/subtitle-preview")
def subtitle_preview(pid: str, subtitle_id: str = Query(min_length=1, max_length=64)):
    with SessionLocal() as db:
        project = db.get(Project, pid)
        if not project:
            raise HTTPException(404)
        require_visible(db, pid)
        if project.state != "draft":
            raise HTTPException(
                409, "La vista previa de pistas está disponible antes de comenzar"
            )
    result = native_request(
        "POST", "/files/subtitle", json={"project_id": pid, "subtitle_id": subtitle_id}
    ).json()
    try:
        cues = parse_srt(result["srt"])
    except (ValueError, IndexError) as exc:
        raise HTTPException(
            422, "El subtítulo tiene marcas de tiempo inválidas"
        ) from exc
    return {"cues": cues}


class SyncPreviewRequest(BaseModel):
    audio_index: int = Field(ge=0)


class SyncCue(BaseModel):
    id: str
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)
    new_start: float = Field(ge=0, allow_inf_nan=False)
    new_end: float = Field(gt=0, allow_inf_nan=False)


class SyncApplyRequest(BaseModel):
    cues: list[SyncCue] = Field(min_length=1, max_length=100000)


@app.post("/api/projects/{pid}/sync-preview")
def sync_preview(pid: str, body: SyncPreviewRequest, request: Request):
    require_local_action(request)
    with SessionLocal() as db:
        project = db.get(Project, pid)
        if not project:
            raise HTTPException(404)
        require_visible(db, pid)
        if project.state not in ("ready", "failed", "cancelled"):
            raise HTTPException(409, "Espera a que termine el procesamiento")
        rows = db.scalars(select(Cue).where(Cue.project_id == pid).order_by(Cue.position)).all()
        if not rows:
            raise HTTPException(422, "No hay subtítulos para sincronizar")
        baseline = [{"id": c.id, "start": c.start, "end": c.end, "original": c.original} for c in rows]
        srt = export(rows, "original", False)
    result = native_request("POST", "/files/sync-subtitles", json={"project_id": pid, "audio_index": body.audio_index, "srt": srt}, timeout=(5, 1860)).json()
    try:
        aligned = parse_srt(result["srt"])
    except (KeyError, ValueError, IndexError) as exc:
        raise HTTPException(502, "La sincronización devolvió un resultado inválido") from exc
    if len(aligned) != len(baseline) or any(a["original"].strip() != b["original"].strip() for a, b in zip(aligned, baseline)):
        raise HTTPException(422, "La sincronización cambió los segmentos; no se aplicará automáticamente")
    return {"cues": [{"id": b["id"], "start": b["start"], "end": b["end"], "new_start": a["start"], "new_end": a["end"]} for a, b in zip(aligned, baseline)]}


@app.post("/api/projects/{pid}/sync-apply")
def sync_apply(pid: str, body: SyncApplyRequest, request: Request):
    require_local_action(request)
    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.id == pid).with_for_update())
        if not project:
            raise HTTPException(404)
        require_visible(db, pid)
        if project.state not in ("ready", "failed", "cancelled"):
            raise HTTPException(409, "Espera a que termine el procesamiento")
        rows = db.scalars(select(Cue).where(Cue.project_id == pid).order_by(Cue.position)).all()
        if len(rows) != len(body.cues) or any(c.id != p.id or c.start != p.start or c.end != p.end for c, p in zip(rows, body.cues)):
            raise HTTPException(409, "Los segmentos cambiaron; genera una nueva propuesta")
        if any(p.new_end <= p.new_start for p in body.cues):
            raise HTTPException(422, "La propuesta contiene tiempos inválidos")
        for cue, proposal in zip(rows, body.cues):
            cue.start, cue.end = proposal.new_start, proposal.new_end
        db.commit()
    return {"ok": True}


@app.get("/api/projects/{pid}/audio-preview")
def preview_audio(
    pid: str,
    index: int = Query(ge=0),
    start: float = Query(default=0, ge=0, allow_inf_nan=False),
):
    with SessionLocal() as db:
        project = db.get(Project, pid)
        if not project:
            raise HTTPException(404)
        require_visible(db, pid)
        if project.filename != "source.json":
            raise HTTPException(409, "Este proyecto no tiene pistas inspeccionadas")
        if index not in [
            item["index"] for item in reference(pid).get("audio_tracks", [])
        ]:
            raise HTTPException(400, "Pista de audio no encontrada")
    result = native_request(
        "GET", f"/files/{pid}/audio-preview", params={"index": index, "start": start}
    )
    return Response(
        content=result.content,
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-store"},
    )


def project_audio_index(pid, requested=None):
    with SessionLocal() as db:
        project = db.get(Project, pid)
        if not project:
            raise HTTPException(404)
        require_visible(db, pid)
        if project.filename != "source.json":
            raise HTTPException(409, "Este proyecto no tiene pistas inspeccionadas")
        info = reference(pid)
        tracks = info.get("audio_tracks", [])
        selected = requested if requested is not None else info.get("audio_index")
        if selected is None and tracks:
            selected = tracks[0]["index"]
        if selected not in [track["index"] for track in tracks]:
            raise HTTPException(409, "No hay una pista de audio disponible")
        return selected


@app.get("/api/projects/{pid}/envelope")
def project_envelope(
    pid: str,
    start: float = Query(ge=0, allow_inf_nan=False),
    end: float = Query(gt=0, le=43200, allow_inf_nan=False),
    buckets: int = Query(default=220, ge=1, le=400),
    index: int | None = Query(default=None, ge=0),
):
    if end <= start:
        raise HTTPException(422, "El final debe ser posterior al inicio")
    return native_request(
        "GET",
        f"/files/{pid}/envelope",
        params={
            "index": project_audio_index(pid, index),
            "start": start,
            "end": end,
            "buckets": buckets,
        },
        timeout=(5, 310),
    ).json()


@app.get("/api/projects/{pid}/envelope/overview")
def project_envelope_overview(pid: str, index: int | None = Query(default=None, ge=0)):
    return native_request(
        "GET",
        f"/files/{pid}/envelope/overview",
        params={"index": project_audio_index(pid, index)},
        timeout=(5, 310),
    ).json()


def audio_client():
    return httpx.AsyncClient(timeout=httpx.Timeout(120, connect=5))


@app.get("/api/projects/{pid}/audio-stream")
async def audio_stream(
    pid: str,
    index: int = Query(ge=0),
    start: float = Query(default=0, ge=0, allow_inf_nan=False),
):
    with SessionLocal() as db:
        p = db.get(Project, pid)
        if not p:
            raise HTTPException(404)
        require_visible(db, pid)
        if p.filename != "source.json" or index not in [
            item["index"] for item in reference(pid).get("audio_tracks", [])
        ]:
            raise HTTPException(400, "Pista de audio no encontrada")
    client = audio_client()
    try:
        request = client.build_request(
            "GET",
            MAC_URL + f"/files/{pid}/audio-stream",
            params={"index": index, "start": start},
            headers={"X-Worker-Token": TOKEN},
        )
        response = await client.send(request, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        raise HTTPException(503, "Gateway nativo no disponible") from exc
    if response.status_code >= 400:
        await response.aclose()
        await client.aclose()
        raise HTTPException(response.status_code, "No se pudo abrir la pista de audio")

    async def chunks():
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            with anyio.CancelScope(shield=True):
                await response.aclose()
                await client.aclose()

    class AudioResponse(StreamingResponse):
        async def stream_response(self, send):
            try:
                await super().stream_response(send)
            finally:
                with anyio.CancelScope(shield=True):
                    await self.body_iterator.aclose()

    return AudioResponse(
        chunks(),
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/projects/{pid}/start")
def start_project(pid: str, body: StartRequest):
    with SessionLocal() as db:
        p = db.get(Project, pid)
        if not p:
            raise HTTPException(404)
        require_visible(db, pid)
        if p.state != "draft":
            raise HTTPException(409, "El proyecto ya se ha iniciado")
    if body.source == "asr" and body.audio_index is not None:
        if body.audio_index not in [
            item["index"] for item in reference(pid).get("audio_tracks", [])
        ]:
            raise HTTPException(400, "Pista de audio no encontrada")
    cues = []
    if body.source != "asr":
        result = native_request(
            "POST",
            "/files/subtitle",
            json={"project_id": pid, "subtitle_id": body.source},
        ).json()
        try:
            cues = parse_srt(result["srt"])
        except (ValueError, IndexError) as exc:
            raise HTTPException(
                422, "El subtítulo tiene marcas de tiempo inválidas"
            ) from exc
        if not cues:
            raise HTTPException(422, "El subtítulo no contiene segmentos válidos")
    with SessionLocal() as db:
        p = db.scalar(select(Project).where(Project.id == pid).with_for_update())
        require_visible(db, pid)
        if p.state != "draft":
            raise HTTPException(409, "El proyecto ya se ha iniciado")
        save_workflow(
            pid,
            body.source,
            body.action,
            body.audio_index,
            body.asr_language if body.source == "asr" else None,
            body.asr_model if body.source == "asr" else None,
        )
        for position, cue in enumerate(cues):
            db.add(Cue(id=str(uuid.uuid4()), project_id=pid, position=position, **cue))
        p.state = "ready" if cues and body.action == "edit" else "queued"
        p.progress = 100 if p.state == "ready" else 0
        should_enqueue = p.state == "queued"
        db.commit()
    if should_enqueue:
        enqueue_project(pid)
    return {"id": pid}


class TranslationLanguageRequest(BaseModel):
    target_language: Literal["Spanish", "Romanian", "English", "Portuguese", "French", "Italian", "German", "Dutch", "Japanese", "Chinese"]


class ProjectTranslationRequest(TranslationLanguageRequest):
    model: str = Field(min_length=1, max_length=200)


@app.post("/api/projects/{pid}/translation-language")
def identify_translation_language(pid: str, body: TranslationLanguageRequest):
    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.id == pid).with_for_update())
        if not project:
            raise HTTPException(404)
        require_visible(db, pid)
        if project.state not in ("ready", "failed", "cancelled", "transcribing"):
            raise HTTPException(409, "Espera a que termine el procesamiento")
        info = reference(pid)
        existing = db.scalars(select(Cue.translated).where(Cue.project_id == pid)).all()
        if not any((value or "").strip() for value in existing):
            raise HTTPException(409, "No hay traducciones existentes que identificar")
        if info.get("target_language") and info["target_language"] != body.target_language:
            raise HTTPException(409, "El proyecto ya tiene un idioma de traducción registrado")
        save_workflow(pid, info.get("selected_source", "asr"), info.get("action", "edit"), info.get("audio_index"), target_language=body.target_language)
    return {"target_language": body.target_language}


@app.post("/api/projects/{pid}/translate")
def translate_pending(pid: str, body: ProjectTranslationRequest | None = None):
    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.id == pid).with_for_update())
        if not project:
            raise HTTPException(404)
        require_visible(db, pid)
        if project.state not in ("ready", "failed", "cancelled"):
            raise HTTPException(409, "Espera a que termine el procesamiento")
        batch_item = db.scalar(select(BatchItem).where(BatchItem.project_id == pid, BatchItem.status.not_in(("done", "cancelled"))).limit(1))
        if batch_item:
            raise HTTPException(409, "Este proyecto pertenece a un lote activo; continúa desde la cola")
        cues = db.scalars(select(Cue).where(Cue.project_id == pid)).all()
        if not cues or not any((c.original or "").strip() and not (c.translated or "").strip() for c in cues):
            raise HTTPException(409, "No hay segmentos pendientes de traducir")
        info = reference(pid)
        if body:
            previous_language = info.get("target_language")
            if previous_language and any((cue.translated or "").strip() for cue in cues) and body.target_language != previous_language:
                raise HTTPException(409, "Ya hay traducciones en otro idioma. Conserva este idioma para no mezclar resultados.")
            available = native_request("GET", "/ollama/models", timeout=(5, 15)).json()
            if body.model not in {item.get("name") for item in available}:
                raise HTTPException(400, "El modelo seleccionado no está instalado en Ollama")
        save_workflow(
            pid,
            info.get("selected_source", "asr"),
            "translate",
            info.get("audio_index"),
            target_language=body.target_language if body else None,
            translation_model=body.model if body else None,
        )
        project.state, project.progress, project.error = "queued", 0, ""
        db.commit()
    enqueue_project(pid)
    return {"id": pid}


class ImprovementRequest(BaseModel):
    model: str = Field(min_length=1, max_length=200)


@app.post("/api/projects/{pid}/improve")
def improve_transcript(pid: str, body: ImprovementRequest | None = None):
    if body:
        available = native_request("GET", "/ollama/models", timeout=(5, 15)).json()
        if body.model not in {item.get("name") for item in available}:
            raise HTTPException(
                400, "El modelo seleccionado no está instalado en Ollama"
            )
    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.id == pid).with_for_update())
        if not project:
            raise HTTPException(404)
        require_visible(db, pid)
        if project.state not in ("ready", "failed", "cancelled"):
            raise HTTPException(409, "Espera a que termine el procesamiento")
        pending = db.scalar(select(CueReview.cue_id).join(Cue, CueReview.cue_id == Cue.id).where(Cue.project_id == pid, CueReview.proposal.is_not(None)).limit(1))
        if pending:
            raise HTTPException(409, "Acepta o descarta las propuestas pendientes antes de iniciar otra mejora")
        cues = db.scalars(
            select(Cue).where(Cue.project_id == pid).order_by(Cue.position)
        ).all()
        if not cues:
            raise HTTPException(422, "No hay texto para mejorar")
        backup_id = str(uuid.uuid4())
        path = pathlib.Path(DATA) / pid / f"improvement-{backup_id}.json"
        snapshot = {
            "restored": False,
            "previous_state": project.state,
            "previous_error": project.error,
            "previous_progress": project.progress,
            "proposal_mode": True,
            "cues": [{"id": c.id, "before": c.original, "after": None} for c in cues],
        }
        if body:
            snapshot["model"] = body.model
        improvement.write(path, snapshot)
        project.state, project.progress, project.error = "improve_queued", 0, ""
        db.commit()
    try:
        queue().enqueue("app.worker.improve_project", pid, backup_id, job_timeout=14400)
    except Exception as exc:
        with SessionLocal() as db:
            project = db.scalar(
                select(Project).where(Project.id == pid).with_for_update()
            )
            if project and project.state == "improve_queued":
                project.state, project.error = (
                    snapshot["previous_state"],
                    snapshot["previous_error"],
                )
                db.commit()
        raise HTTPException(
            503, "No se pudo iniciar la mejora; se conserva el texto"
        ) from exc
    return {"backup": backup_id}


@app.post("/api/projects/{pid}/improve/undo")
def undo_improvement(pid: str):
    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.id == pid).with_for_update())
        if not project:
            raise HTTPException(404)
        require_visible(db, pid)
        if project.state not in ("ready", "failed", "cancelled"):
            raise HTTPException(409, "Espera a que termine el procesamiento")
        path, backup = improvement.latest(pid)
        if not backup:
            raise HTTPException(404, "No hay una mejora que revertir")
        for entry in backup["cues"]:
            cue = db.get(Cue, entry["id"])
            if (
                not cue
                or cue.project_id != pid
                or cue.original not in (entry["before"], entry["after"])
            ):
                raise HTTPException(
                    409,
                    "El texto se ha editado después de la mejora; no se sobrescribirán cambios posteriores",
                )
        for entry in backup["cues"]:
            db.get(Cue, entry["id"]).original = entry["before"]
            if backup.get("proposal_mode"):
                review = db.get(CueReview, entry["id"])
                if (
                    review
                    and review.proposal_source == entry["before"]
                    and review.proposal == entry["after"]
                ):
                    review.proposal = None
                    review.proposal_source = None
        control = db.get(TaskControl, pid)
        if (
            project.state == "failed" and project.error.startswith("Mejora incompleta:")
        ) or (project.state == "cancelled" and control and control.kind == "improve"):
            project.state = backup.get("previous_state", "ready")
            project.error = backup.get("previous_error", "")
            project.progress = backup.get("previous_progress", 100)
        db.commit()
        backup["restored"] = True
        improvement.write(path, backup)
    return {"ok": True}


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    with SessionLocal() as db:
        p = db.get(Project, pid)
        if not p:
            raise HTTPException(404)
        cues = db.scalars(
            select(Cue).where(Cue.project_id == pid).order_by(Cue.position)
        ).all()
        reviews = (
            {
                r.cue_id: r
                for r in db.scalars(
                    select(CueReview).where(CueReview.cue_id.in_([c.id for c in cues]))
                ).all()
            }
            if cues
            else {}
        )
        return {
            "project": as_project(p, db),
            "cues": [as_cue(c, reviews.get(c.id)) for c in cues],
        }


@app.post("/api/projects/{pid}/retry")
def retry_project(pid: str):
    with SessionLocal() as db:
        p = db.scalar(select(Project).where(Project.id == pid).with_for_update())
        if not p:
            raise HTTPException(404)
        require_visible(db, pid)
        if p.state != "failed":
            raise HTTPException(409, "Solo se pueden reintentar proyectos fallidos")
        path = pathlib.Path(DATA) / pid / p.filename
        if not path.is_file():
            raise HTTPException(409, "Falta el archivo original")
        p.state = "queued"
        p.error = ""
        p.progress = 0
        db.commit()
    enqueue_project(pid)
    return {"id": pid}


@app.api_route("/api/projects/{pid}/media", methods=["GET", "HEAD"])
def media(pid: str, request: Request):
    with SessionLocal() as db:
        p = db.get(Project, pid)
        if not p:
            raise HTTPException(404)
        if p.filename != "source.json":
            path = pathlib.Path(DATA) / pid / p.filename
            if not path.exists():
                raise HTTPException(404)
            return FileResponse(path, filename=None)
    forwarded = {
        k: request.headers[k] for k in ("Range", "If-Range") if k in request.headers
    }
    response = native_request(
        request.method, f"/files/{pid}/media", headers=forwarded, stream=True
    )
    headers = {
        k: v
        for k, v in response.headers.items()
        if k.lower()
        in (
            "content-type",
            "content-length",
            "content-range",
            "accept-ranges",
            "etag",
            "last-modified",
        )
    }
    if request.method == "HEAD":
        response.close()
        return Response(status_code=response.status_code, headers=headers)

    def chunks():
        try:
            yield from response.iter_content(chunk_size=256 * 1024)
        finally:
            response.close()

    return StreamingResponse(
        chunks(),
        status_code=response.status_code,
        headers=headers,
        background=BackgroundTask(response.close),
    )


class CueFields(BaseModel):
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)
    original: str = Field(max_length=10000)
    translated: str = Field(max_length=10000)


class CueUpdate(CueFields):
    expected: CueFields | None = None
    flag_resolved: bool | None = None


class CueDelete(BaseModel):
    expected: CueFields


class ComparisonChange(BaseModel):
    cue_id: str
    field: Literal["original", "translated"]
    value: str = Field(max_length=10000)
    expected: CueFields


class ApplyComparison(BaseModel):
    changes: list[ComparisonChange] = Field(min_length=1, max_length=8)


def comparison_state(db, cue):
    if not cue:
        return None
    review = db.get(CueReview, cue.id)
    return {
        "cue": {
            field: getattr(cue, field)
            for field in (
                "id",
                "project_id",
                "position",
                "start",
                "end",
                "original",
                "translated",
            )
        },
        "review": {
            field: getattr(review, field)
            for field in ("flag", "flag_resolved", "proposal", "proposal_source")
        }
        if review
        else None,
    }


@app.post("/api/projects/{pid}/apply-comparison")
def apply_comparison(pid: str, body: ApplyComparison, request: Request):
    require_local_action(request)
    if len({change.cue_id for change in body.changes}) != len(body.changes):
        raise HTTPException(422, "El rango contiene segmentos repetidos")
    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.id == pid).with_for_update())
        if not project:
            raise HTTPException(404)
        require_visible(db, pid)
        if project.state not in ("ready", "failed", "cancelled"):
            raise HTTPException(409, "Espera a que termine esta operación")
        pairs = [(change, db.get(Cue, change.cue_id)) for change in body.changes]
        for change, cue in pairs:
            if not cue or cue.project_id != pid:
                raise HTTPException(404, "No se encontró un segmento del rango")
            if any(
                getattr(cue, field) != getattr(change.expected, field)
                for field in ("start", "end", "original", "translated")
            ):
                raise HTTPException(
                    409, "Un segmento cambió; compara de nuevo antes de aplicar"
                )
        snapshots = []
        for change, cue in pairs:
            before = comparison_state(db, cue)
            if change.value.strip():
                setattr(cue, change.field, change.value)
                after = comparison_state(db, cue)
            else:
                review = db.get(CueReview, cue.id)
                if review:
                    db.delete(review)
                    db.flush()
                db.delete(cue)
                after = None
            snapshots.append({"before": before, "after": after})
        backup_id = str(uuid.uuid4())
        db.add(
            ComparisonSnapshot(
                id=backup_id,
                project_id=pid,
                changes=json.dumps(snapshots, ensure_ascii=False),
                created=time.time(),
            )
        )
        db.commit()
        return {"applied": len(snapshots), "undo_id": backup_id}


@app.post("/api/projects/{pid}/comparisons/{snapshot_id}/undo")
def undo_comparison(pid: str, snapshot_id: str, request: Request):
    require_local_action(request)
    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.id == pid).with_for_update())
        if not project:
            raise HTTPException(404)
        require_visible(db, pid)
        if project.state not in ("ready", "failed", "cancelled"):
            raise HTTPException(409, "Espera a que termine esta operación")
        snapshot = db.get(ComparisonSnapshot, snapshot_id)
        if not snapshot or snapshot.project_id != pid or snapshot.restored:
            raise HTTPException(404, "No hay comparación para deshacer")
        changes = json.loads(snapshot.changes)
        for change in changes:
            state = change["before"] or change["after"]
            cue = db.get(Cue, state["cue"]["id"])
            if comparison_state(db, cue) != change["after"]:
                raise HTTPException(
                    409,
                    "Un segmento cambió después de comparar; no se sobrescribirán cambios",
                )
        for change in changes:
            before = change["before"]
            if before is None:
                cue = db.get(Cue, change["after"]["cue"]["id"])
                if cue:
                    db.delete(cue)
                continue
            values = before["cue"]
            cue = db.get(Cue, values["id"])
            if cue is None:
                cue = Cue(**values)
                db.add(cue)
                db.flush()
            else:
                for field, value in values.items():
                    setattr(cue, field, value)
            review = db.get(CueReview, cue.id)
            if before["review"] is not None:
                if not review:
                    review = CueReview(cue_id=cue.id)
                    db.add(review)
                for field, value in before["review"].items():
                    setattr(review, field, value)
            elif review:
                db.delete(review)
        snapshot.restored = 1
        db.commit()
        return {"restored": len(changes)}


def proposal_action(pid, cid, action, request):
    require_local_action(request)
    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.id == pid).with_for_update())
        if not project:
            raise HTTPException(404)
        require_visible(db, pid)
        if project.state not in ("ready", "failed", "cancelled"):
            raise HTTPException(409, "Espera a que termine el procesamiento")
        cue = db.get(Cue, cid)
        review = db.get(CueReview, cid)
        if not cue or cue.project_id != pid or not review or review.proposal is None:
            raise HTTPException(404, "No hay una propuesta para este segmento")
        if action == "accept":
            if cue.original != review.proposal_source:
                raise HTTPException(
                    409, "El original cambió; revisa la propuesta antes de aplicarla"
                )
            cue.original = review.proposal
        review.proposal = None
        review.proposal_source = None
        db.commit()
        return as_cue(cue, review)


@app.post("/api/projects/{pid}/cues/{cid}/proposal/accept")
def accept_proposal(pid: str, cid: str, request: Request):
    return proposal_action(pid, cid, "accept", request)


@app.post("/api/projects/{pid}/cues/{cid}/proposal/reject")
def reject_proposal(pid: str, cid: str, request: Request):
    return proposal_action(pid, cid, "reject", request)


@app.post("/api/projects/{pid}/proposals/accept-all")
def accept_all_proposals(pid: str, request: Request):
    require_local_action(request)
    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.id == pid).with_for_update())
        if not project:
            raise HTTPException(404)
        require_visible(db, pid)
        if project.state not in ("ready", "failed", "cancelled"):
            raise HTTPException(409, "Espera a que termine el procesamiento")
        pairs = db.execute(
            select(Cue, CueReview)
            .join(CueReview, Cue.id == CueReview.cue_id)
            .where(Cue.project_id == pid, CueReview.proposal.is_not(None))
        ).all()
        if any(cue.original != review.proposal_source for cue, review in pairs):
            raise HTTPException(
                409, "Un original cambió; revisa las propuestas antes de aplicarlas"
            )
        for cue, review in pairs:
            cue.original = review.proposal
            review.proposal = None
            review.proposal_source = None
        db.commit()
        return {"accepted": len(pairs)}


class CueTranslation(BaseModel):
    direction: Literal["forward", "backward"]
    model: str | None = Field(default=None, min_length=1, max_length=200)
    target_language: Literal[
        "Spanish",
        "Romanian",
        "English",
        "Portuguese",
        "French",
        "Italian",
        "German",
        "Dutch",
        "Japanese",
        "Chinese",
    ]


class CueTranslationComparison(CueTranslation):
    models: list[str] = Field(min_length=2, max_length=2)


class TranslationRangeComparison(CueTranslationComparison):
    cue_ids: list[str] = Field(min_length=1, max_length=8)


@app.post("/api/projects/{pid}/compare-translations")
def compare_translation_range(
    pid: str, body: TranslationRangeComparison, request: Request
):
    require_local_action(request)
    if len(set(body.cue_ids)) != len(body.cue_ids):
        raise HTTPException(422, "El rango contiene segmentos repetidos")
    with SessionLocal() as db:
        project = db.get(Project, pid)
        if not project:
            raise HTTPException(404)
        require_visible(db, pid)
        if project.state not in ("ready", "failed", "cancelled", "transcribing"):
            raise HTTPException(409, "Espera a que termine esta operación")
        cues = [db.get(Cue, cid) for cid in body.cue_ids]
        if any(not cue or cue.project_id != pid for cue in cues):
            raise HTTPException(404, "No se encontró un segmento del rango")
        field = "original" if body.direction == "forward" else "translated"
        texts = [getattr(cue, field) for cue in cues]
        if any(not text.strip() for text in texts):
            raise HTTPException(400, "Hay un texto de origen vacío")
        metadata = [
            {
                "cue_id": cue.id,
                "start": cue.start,
                "end": cue.end,
                "source": text,
                "current": cue.translated
                if body.direction == "forward"
                else cue.original,
            }
            for cue, text in zip(cues, texts)
        ]
    result = native_request(
        "POST",
        "/compare-translations-range",
        json={
            "texts": texts,
            "models": body.models,
            "target_language": body.target_language,
        },
        timeout=(5, 1850),
    ).json()
    return {"cues": metadata, **result}


@app.get("/api/ollama/models")
def available_ollama_models():
    return native_request("GET", "/ollama/models", timeout=(5, 15)).json()


@app.post("/api/projects/{pid}/cues/{cid}/compare-translations")
def compare_cue_translations(
    pid: str, cid: str, body: CueTranslationComparison, request: Request
):
    require_local_action(request)
    with SessionLocal() as db:
        project = db.get(Project, pid)
        if not project:
            raise HTTPException(404)
        require_visible(db, pid)
        if project.state not in ("ready", "failed", "cancelled", "transcribing"):
            raise HTTPException(409, "Espera a que termine esta operación")
        cue = db.get(Cue, cid)
        if not cue or cue.project_id != pid:
            raise HTTPException(404)
        text = cue.original if body.direction == "forward" else cue.translated
        if not text.strip():
            raise HTTPException(400, "El texto de origen está vacío")
    result = native_request(
        "POST",
        "/compare-translations",
        json={
            "text": text,
            "models": body.models,
            "target_language": body.target_language,
        },
        timeout=(5, 1850),
    ).json()
    return {**result, "source": text}


@app.post("/api/projects/{pid}/cues/{cid}/translate")
def translate_cue(pid: str, cid: str, body: CueTranslation, request: Request):
    require_local_action(request)
    with SessionLocal() as db:
        project = db.get(Project, pid)
        if not project:
            raise HTTPException(404)
        require_visible(db, pid)
        if project.state not in ("ready", "failed", "cancelled", "transcribing"):
            raise HTTPException(409, "Espera a que termine esta operación")
        cue = db.get(Cue, cid)
        if not cue or cue.project_id != pid:
            raise HTTPException(404)
        text = cue.original if body.direction == "forward" else cue.translated
        if not text.strip():
            raise HTTPException(400, "El texto de origen está vacío")
        info = reference(pid)
        if body.direction == "forward":
            translated = db.scalars(select(Cue.translated).where(Cue.project_id == pid)).all()
            if info.get("target_language") and any((value or "").strip() for value in translated) and body.target_language != info["target_language"]:
                raise HTTPException(409, "Ya hay traducciones en otro idioma; no se mezclarán idiomas en esta columna")
        payload = {"texts": [text], "target_language": body.target_language}
        if body.model:
            available = native_request("GET", "/ollama/models", timeout=(5, 15)).json()
            if body.model not in {item.get("name") for item in available}:
                raise HTTPException(400, "El modelo seleccionado no está instalado en Ollama")
        model = body.model or info.get("translation_model")
        if model:
            payload["model"] = model
    response = native_request(
        "POST",
        "/translate",
        json=payload,
        timeout=(5, 900),
    ).json()
    values = response.get("texts")
    if (
        not isinstance(values, list)
        or len(values) != 1
        or not isinstance(values[0], str)
        or not values[0].strip()
    ):
        raise HTTPException(502, "El modelo no devolvió una traducción válida")
    if body.direction == "forward":
        with SessionLocal() as db:
            project = db.scalar(select(Project).where(Project.id == pid).with_for_update())
            if not project:
                raise HTTPException(404)
            info = reference(pid)
            translated = db.scalars(select(Cue.translated).where(Cue.project_id == pid)).all()
            if info.get("target_language") and any((value or "").strip() for value in translated) and body.target_language != info["target_language"]:
                raise HTTPException(409, "El idioma de destino cambió; vuelve a traducir")
            save_workflow(pid, info.get("selected_source", "asr"), info.get("action", "translate"), info.get("audio_index"), target_language=body.target_language, translation_model=body.model)
    return {"text": values[0], "source": text}


@app.put("/api/projects/{pid}/cues/{cid}")
def update_cue(pid: str, cid: str, body: CueUpdate):
    if body.end <= body.start:
        raise HTTPException(422, "Fin debe ser posterior al inicio")
    with SessionLocal() as db:
        p = db.scalar(select(Project).where(Project.id == pid).with_for_update())
        if not p:
            raise HTTPException(404)
        if p.state not in ("ready", "failed", "cancelled", "transcribing"):
            raise HTTPException(
                409, "Espera a que termine el procesamiento para editar"
            )
        c = db.get(Cue, cid)
        if not c or c.project_id != pid:
            raise HTTPException(404)
        fields = ["start", "end", "original", "translated"]
        if p.state == "transcribing" and (
            body.expected is None or body.start != c.start or body.end != c.end
        ):
            raise HTTPException(
                409,
                "Durante la transcripción solo se puede actualizar el texto con control de cambios",
            )
        if body.expected and any(
            getattr(c, field) != getattr(body.expected, field) for field in fields
        ):
            raise HTTPException(
                409,
                "Este segmento cambió en otra pestaña. Copia tu cambio y recarga el proyecto para revisarlo.",
            )
        for field in fields:
            setattr(c, field, getattr(body, field))
        review = db.get(CueReview, cid)
        if body.flag_resolved is not None:
            if not review:
                review = CueReview(cue_id=cid)
                db.add(review)
            review.flag_resolved = int(body.flag_resolved)
        db.commit()
        return as_cue(c, review)


@app.delete("/api/projects/{pid}/cues/{cid}")
def delete_cue(pid: str, cid: str, body: CueDelete, request: Request):
    require_local_action(request)
    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.id == pid).with_for_update())
        if not project:
            raise HTTPException(404)
        require_visible(db, pid)
        if project.state not in ("ready", "failed", "cancelled"):
            raise HTTPException(409, "Espera a que termine el procesamiento")
        cue = db.get(Cue, cid)
        if not cue or cue.project_id != pid:
            raise HTTPException(404)
        if any(
            getattr(cue, field) != getattr(body.expected, field)
            for field in ("start", "end", "original", "translated")
        ):
            raise HTTPException(
                409, "El segmento cambió; recarga y revísalo antes de borrarlo"
            )
        snapshot_id = str(uuid.uuid4())
        db.add(
            ComparisonSnapshot(
                id=snapshot_id,
                project_id=pid,
                changes=json.dumps(
                    [{"before": comparison_state(db, cue), "after": None}],
                    ensure_ascii=False,
                ),
                created=time.time(),
            )
        )
        review = db.get(CueReview, cid)
        if review:
            db.delete(review)
        db.delete(cue)
        db.commit()
    return {"ok": True, "undo_id": snapshot_id}


@app.post("/api/projects/{pid}/cues/{cid}/insert-after")
def insert_cue_after(pid: str, cid: str, request: Request):
    require_local_action(request)
    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.id == pid).with_for_update())
        if not project:
            raise HTTPException(404)
        require_visible(db, pid)
        if project.state not in ("ready", "failed", "cancelled"):
            raise HTTPException(409, "Espera a que termine el procesamiento")
        rows = db.scalars(select(Cue).where(Cue.project_id == pid).order_by(Cue.position)).all()
        index = next((i for i, item in enumerate(rows) if item.id == cid), None)
        if index is None:
            raise HTTPException(404, "No se encontró la entrada")
        if len({item.position for item in rows}) != len(rows):
            raise HTTPException(409, "Hay posiciones duplicadas; revisa el proyecto antes de insertar")
        selected = rows[index]
        following = rows[index + 1:]
        before = [comparison_state(db, item) for item in following]
        for item in following:
            item.position += 1
        start = selected.end
        end = min(start + 2, following[0].start) if following and following[0].start > start else start + 2
        cue = Cue(id=str(uuid.uuid4()), project_id=pid, position=selected.position + 1, start=start, end=end, original="", translated="")
        db.add(cue)
        db.flush()
        snapshots = [{"before": original, "after": comparison_state(db, item)} for original, item in zip(before, following)]
        snapshots.append({"before": None, "after": comparison_state(db, cue)})
        snapshot_id = str(uuid.uuid4())
        db.add(ComparisonSnapshot(id=snapshot_id, project_id=pid, changes=json.dumps(snapshots, ensure_ascii=False), created=time.time()))
        db.commit()
        return {"cue": as_cue(cue, None), "undo_id": snapshot_id}


class LocalExportRequest(BaseModel):
    language: Literal["es", "ro", "en", "pt", "fr", "it", "de", "nl", "ja", "zh", "original", "bilingual"] = "es"
    format: Literal["srt", "vtt"] = "srt"


@app.post("/api/projects/{pid}/export/local")
def export_local(pid: str, body: LocalExportRequest):
    with SessionLocal() as db:
        project = db.get(Project, pid)
        if not project:
            raise HTTPException(404)
        if project.filename != "source.json":
            raise HTTPException(
                409,
                "Este proyecto antiguo no conserva la ubicación original; usa Descargar",
            )
        cues = db.scalars(
            select(Cue).where(Cue.project_id == pid).order_by(Cue.position)
        ).all()
        content = export(cues, body.language, body.format == "vtt")
    return native_request(
        "POST",
        "/files/export",
        json={
            "project_id": pid,
            "content": content,
            "language": body.language,
            "format": body.format,
        },
    ).json()


@app.get("/api/projects/{pid}/export")
def get_export(
    pid: str,
    language: str = Query("es", pattern="^(es|ro|en|pt|fr|it|de|nl|ja|zh|original|bilingual)$"),
    format: str = Query("srt", pattern="^(srt|vtt)$"),
):
    with SessionLocal() as db:
        p = db.get(Project, pid)
        if not p:
            raise HTTPException(404)
        cues = db.scalars(
            select(Cue).where(Cue.project_id == pid).order_by(Cue.position)
        ).all()
        content = export(cues, language, format == "vtt")
        return PlainTextResponse(
            content,
            media_type="text/vtt" if format == "vtt" else "text/plain",
            headers={
                "Content-Disposition": f'attachment; filename="{pid}.{language}.{format}"'
            },
        )
