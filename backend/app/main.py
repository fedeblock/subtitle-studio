import uuid
import time
import pathlib
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
from app.core import initialize, SessionLocal, Project, Cue, HiddenProject, queue, DATA
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
        audio_tracks=info.get("audio_tracks", []),
        audio_index=info.get("audio_index"),
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
        return [as_project(x) for x in db.scalars(statement).all()]


def require_local_action(request: Request):
    if request.headers.get("X-Studio-Local") != "1":
        raise HTTPException(403, "Acción local requerida")


def require_visible(db, pid):
    if db.get(HiddenProject, pid):
        raise HTTPException(
            409, "Restaura el proyecto de la papelera antes de procesarlo"
        )


ACTIVE_STATES = {"queued", "transcribing", "translating", "improve_queued", "improving"}


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


class StartRequest(BaseModel):
    source: str = Field(min_length=1, max_length=64)
    action: Literal["translate", "edit", "view"] = "translate"
    audio_index: int | None = Field(default=None, ge=0)


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
        save_workflow(pid, body.source, body.action, body.audio_index)
        for position, cue in enumerate(cues):
            db.add(Cue(id=str(uuid.uuid4()), project_id=pid, position=position, **cue))
        p.state = "ready" if cues and body.action in ("edit", "view") else "queued"
        p.progress = 100 if p.state == "ready" else 0
        should_enqueue = p.state == "queued"
        db.commit()
    if should_enqueue:
        enqueue_project(pid)
    return {"id": pid}


@app.post("/api/projects/{pid}/edit-mode")
def edit_mode(pid: str):
    with SessionLocal() as db:
        p = db.scalar(select(Project).where(Project.id == pid).with_for_update())
        if not p:
            raise HTTPException(404)
        require_visible(db, pid)
        if p.state not in ("ready", "failed") or p.filename != "source.json":
            raise HTTPException(409, "No se puede editar este proyecto ahora")
        info = reference(pid)
        if info.get("action") != "view":
            raise HTTPException(409, "El proyecto no está en modo de vista")
        save_workflow(
            pid, info.get("selected_source", "asr"), "edit", info.get("audio_index")
        )
    return {"id": pid}


@app.post("/api/projects/{pid}/translate")
def translate_pending(pid: str):
    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.id == pid).with_for_update())
        if not project:
            raise HTTPException(404)
        require_visible(db, pid)
        if project.state not in ("ready", "failed"):
            raise HTTPException(409, "Espera a que termine el procesamiento")
        cues = db.scalars(select(Cue).where(Cue.project_id == pid)).all()
        if not cues or not any(not (c.translated or "").strip() for c in cues):
            raise HTTPException(409, "No hay segmentos pendientes de traducir")
        if project.filename == "source.json":
            info = reference(pid)
            save_workflow(
                pid,
                info.get("selected_source", "asr"),
                "translate",
                info.get("audio_index"),
            )
        project.state, project.progress, project.error = "queued", 0, ""
        db.commit()
    enqueue_project(pid)
    return {"id": pid}


@app.post("/api/projects/{pid}/improve")
def improve_transcript(pid: str):
    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.id == pid).with_for_update())
        if not project:
            raise HTTPException(404)
        require_visible(db, pid)
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
        require_visible(db, pid)
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


class LocalExportRequest(BaseModel):
    language: Literal["es", "original"] = "es"
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
