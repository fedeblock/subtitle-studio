import uuid
import time
import pathlib
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text, update
from app.core import initialize, SessionLocal, Project, Cue, queue, DATA
from app.subtitles import export

MAX_BYTES = 2 * 1024 * 1024 * 1024
ALLOWED = {".mp4", ".mov", ".mkv", ".mp3", ".wav", ".m4a", ".webm", ".flac"}


@asynccontextmanager
async def lifespan(app):
    pathlib.Path(DATA).mkdir(exist_ok=True, parents=True)
    initialize()
    yield


app = FastAPI(title="Subtitle Studio API", lifespan=lifespan)


def as_project(p):
    return {
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


@app.get("/api/projects/{pid}/media")
def media(pid: str):
    with SessionLocal() as db:
        p = db.get(Project, pid)
        if not p:
            raise HTTPException(404)
        path = pathlib.Path(DATA) / pid / p.filename
        if not path.exists():
            raise HTTPException(404)
        return FileResponse(path, filename=None)


class CueUpdate(BaseModel):
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)
    original: str = Field(max_length=10000)
    translated: str = Field(max_length=10000)


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
        for field in ["start", "end", "original", "translated"]:
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
