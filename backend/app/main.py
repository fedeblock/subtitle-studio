import uuid
import time
import pathlib
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
from app.native import native_request
from app.project_sources import reference, save_workflow
from app import improvement
from pydantic import BaseModel, Field
from sqlalchemy import select, text, update
from app.core import initialize, SessionLocal, Project, Cue, queue, DATA
from app.subtitles import export, parse_srt

MAX_BYTES = 2 * 1024 * 1024 * 1024
ALLOWED = {".mp4", ".mov", ".mkv", ".mp3", ".wav", ".m4a", ".webm", ".flac"}


@asynccontextmanager
async def lifespan(app):
    pathlib.Path(DATA).mkdir(exist_ok=True, parents=True)
    initialize()
    yield


app = FastAPI(title="Subtitle Studio API", lifespan=lifespan)


def as_project(p):
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
    result.update(
        source_kind="reference" if p.filename == "source.json" else "copy",
        subtitle_options=[
            {
                k: v
                for k, v in c.items()
                if k in ("id", "kind", "label", "supported", "reason")
            }
            for c in info.get("subtitles", [])
        ],
        source_warnings=info.get("warnings", []),
        action=info.get("action", "translate"),
        can_undo_improvement=improvement.latest(p.id)[0] is not None,
    )
    return result


def as_cue(c):
    return {
        k: getattr(c, k)
        for k in ["id", "position", "start", "end", "original", "translated"]
    }


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
def projects():
    with SessionLocal() as db:
        return [
            as_project(x)
            for x in db.scalars(select(Project).order_by(Project.created.desc())).all()
        ]


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


class StartRequest(BaseModel):
    source: str = Field(min_length=1, max_length=64)
    action: Literal["translate", "edit"] = "translate"


@app.post("/api/projects/{pid}/start")
def start_project(pid: str, body: StartRequest):
    with SessionLocal() as db:
        p = db.get(Project, pid)
        if not p:
            raise HTTPException(404)
        if p.state != "draft":
            raise HTTPException(409, "El proyecto ya se ha iniciado")
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
        if p.state != "draft":
            raise HTTPException(409, "El proyecto ya se ha iniciado")
        save_workflow(pid, body.source, body.action)
        for position, cue in enumerate(cues):
            db.add(Cue(id=str(uuid.uuid4()), project_id=pid, position=position, **cue))
        p.state = "ready" if cues and body.action == "edit" else "queued"
        p.progress = 100 if p.state == "ready" else 0
        should_enqueue = p.state == "queued"
        db.commit()
    if should_enqueue:
        enqueue_project(pid)
    return {"id": pid}


@app.post("/api/projects/{pid}/improve")
def improve_transcript(pid: str):
    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.id == pid).with_for_update())
        if not project:
            raise HTTPException(404)
        if project.state not in ("ready", "failed"):
            raise HTTPException(409, "Espera a que termine el procesamiento")
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
            "cues": [{"id": c.id, "before": c.original, "after": None} for c in cues],
        }
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
        if project.state not in ("ready", "failed"):
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
        if project.state == "failed" and project.error.startswith("Mejora incompleta:"):
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
        return {"project": as_project(p), "cues": [as_cue(c) for c in cues]}


@app.post("/api/projects/{pid}/retry")
def retry_project(pid: str):
    with SessionLocal() as db:
        p = db.scalar(select(Project).where(Project.id == pid).with_for_update())
        if not p:
            raise HTTPException(404)
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


@app.put("/api/projects/{pid}/cues/{cid}")
def update_cue(pid: str, cid: str, body: CueUpdate):
    if body.end <= body.start:
        raise HTTPException(422, "Fin debe ser posterior al inicio")
    with SessionLocal() as db:
        p = db.scalar(select(Project).where(Project.id == pid).with_for_update())
        if not p:
            raise HTTPException(404)
        if p.state not in ("ready", "failed"):
            raise HTTPException(
                409, "Espera a que termine el procesamiento para editar"
            )
        c = db.get(Cue, cid)
        if not c or c.project_id != pid:
            raise HTTPException(404)
        fields = ["start", "end", "original", "translated"]
        if body.expected and any(
            getattr(c, field) != getattr(body.expected, field) for field in fields
        ):
            raise HTTPException(
                409,
                "Este segmento cambió en otra pestaña. Copia tu cambio y recarga el proyecto para revisarlo.",
            )
        for field in fields:
            setattr(c, field, getattr(body, field))
        db.commit()
        return as_cue(c)


@app.get("/api/projects/{pid}/export")
def get_export(
    pid: str,
    language: str = Query("es", pattern="^(es|original)$"),
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
