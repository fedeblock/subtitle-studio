import os
import json
import pathlib
import urllib.request
import asyncio
import secrets
import subprocess
import anyio
from contextlib import asynccontextmanager, suppress
from model_runtime import ASRRuntime, MLXSession, clear_metal
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, FileResponse, Response, StreamingResponse
from uuid import UUID
from typing import Literal
from threading import Lock
from local_files import (
    choose_local_file,
    discover_subtitles,
    discover_audio,
    audio_preview,
    stream_audio,
    read_subtitle,
    MEDIA_EXTENSIONS,
)
from pydantic import BaseModel, Field

ROOT = pathlib.Path(os.environ["STUDIO_DATA"]).resolve()
TOKEN = os.environ["STUDIO_TOKEN"]
if not TOKEN or TOKEN == "CHANGE_MAC_TOKEN":
    raise RuntimeError("Configura un STUDIO_TOKEN no vacío y aleatorio")
OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.environ.get("STUDIO_TRANSLATION_MODEL", "qwen3:14b-q8_0")
ASR_MODEL = os.environ.get("STUDIO_ASR_MODEL", "Qwen/Qwen3-ASR-1.7B")

ALIGNER_MODEL = os.environ.get("STUDIO_ALIGNER_MODEL", "Qwen/Qwen3-ForcedAligner-0.6B")
IDLE_SECONDS = 600


@asynccontextmanager
async def lifespan(app):
    app.state.asr = ASRRuntime(
        lambda: MLXSession(ASR_MODEL, ALIGNER_MODEL),
        clear_metal,
        idle_seconds=IDLE_SECONDS,
    )

    async def sweep():
        while True:
            await asyncio.sleep(1)
            await asyncio.to_thread(app.state.asr.expire)

    task = asyncio.create_task(sweep())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await asyncio.to_thread(app.state.asr.close)


app = FastAPI(title="Subtitle Studio Mac inference gateway", lifespan=lifespan)


class ClosingStreamResponse(StreamingResponse):
    async def stream_response(self, send):
        try:
            await super().stream_response(send)
        finally:
            with anyio.CancelScope(shield=True):
                close = getattr(self.body_iterator, "aclose", None)
                if close:
                    await close()


@app.middleware("http")
async def protect(request, call_next):
    if not secrets.compare_digest(request.headers.get("X-Worker-Token", ""), TOKEN):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)


@app.get("/health")
def health():
    return {
        "ok": True,
        "idle_seconds": IDLE_SECONDS,
        "asr_model": ASR_MODEL,
        "translation_model": MODEL,
    }


class TranscribeRequest(BaseModel):
    project_id: str = Field(
        pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"
    )


class AudioTranscribeRequest(TranscribeRequest):
    audio_index: int | None = Field(default=None, ge=0)


def project_folder(pid):
    try:
        pid = str(UUID(str(pid)))
    except ValueError:
        raise HTTPException(400, "Proyecto inválido")
    folder = (ROOT / pid).resolve()
    if folder.parent != ROOT:
        raise HTTPException(400, "Invalid project")
    return folder


def load_reference(folder):
    reference = folder / "source.json"
    if reference.is_symlink():
        raise HTTPException(400, "Invalid reference")
    try:
        return json.loads(reference.read_text())
    except (OSError, ValueError):
        raise HTTPException(409, "Referencia local no disponible")


def resolve_source(pid):
    folder = project_folder(pid)
    if (folder / "source.json").exists():
        reference = load_reference(folder)
        source = pathlib.Path(reference["path"])
        if not source.is_absolute() or source.resolve() != source:
            raise HTTPException(409, "La ruta del original ha cambiado")
        if not source.is_file():
            raise HTTPException(
                410, "El archivo original se movió o ya no está disponible"
            )
        return source
    files = [f for f in folder.glob("source.*") if f.is_file()]
    if len(files) != 1:
        raise HTTPException(404, "Source missing")
    source = files[0].resolve()
    if source.parent != folder:
        raise HTTPException(400, "Invalid source path")
    return source


picker_lock = Lock()


@app.post("/files/select")
def select_file(req: TranscribeRequest):
    if not picker_lock.acquire(blocking=False):
        raise HTTPException(409, "Ya hay un selector abierto en macOS")
    try:
        source = choose_local_file()
        if source is None:
            return Response(status_code=204)
        if not source.is_file() or source.suffix.lower() not in MEDIA_EXTENSIONS:
            raise HTTPException(400, "Selecciona un vídeo o audio compatible")
        folder = project_folder(req.project_id)
        if folder.exists():
            raise HTTPException(409, "El proyecto ya existe")
        candidates, warnings = discover_subtitles(source)
        try:
            audio_tracks = discover_audio(source)
        except (OSError, ValueError, subprocess.SubprocessError):
            audio_tracks = []
        folder.mkdir(parents=True)
        with (folder / "source.json").open("x") as output:
            json.dump(
                {
                    "version": 1,
                    "path": str(source),
                    "subtitles": candidates,
                    "audio_tracks": audio_tracks,
                    "warnings": warnings,
                },
                output,
                ensure_ascii=False,
            )
        return {"name": source.name, "filename": "source.json"}
    except subprocess.SubprocessError as exc:
        raise HTTPException(
            409, "El selector de macOS no respondió; vuelve a intentarlo"
        ) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        picker_lock.release()


@app.api_route("/files/{pid}/media", methods=["GET", "HEAD"])
def local_media(pid: UUID):
    return FileResponse(resolve_source(pid))


@app.get("/files/{pid}/audio-preview")
def preview_audio(
    pid: UUID,
    index: int = Query(ge=0),
    start: float = Query(default=0, ge=0, allow_inf_nan=False),
):
    source = resolve_source(pid)
    reference = load_reference(project_folder(pid))
    if index not in [item["index"] for item in reference.get("audio_tracks", [])]:
        raise HTTPException(400, "Pista de audio no autorizada o inexistente")
    try:
        data = audio_preview(source, index, start)
        return Response(
            data, media_type="audio/mpeg", headers={"Cache-Control": "no-store"}
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise HTTPException(
            409, "No se pudo reproducir esta pista en esa posición"
        ) from exc


@app.get("/files/{pid}/audio-stream")
def audio_stream(
    pid: UUID,
    index: int = Query(ge=0),
    start: float = Query(default=0, ge=0, allow_inf_nan=False),
):
    source = resolve_source(pid)
    reference = load_reference(project_folder(pid))
    if index not in [item["index"] for item in reference.get("audio_tracks", [])]:
        raise HTTPException(400, "Pista de audio no autorizada o inexistente")
    return ClosingStreamResponse(
        stream_audio(source, index, start),
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-store"},
    )


class SubtitleRequest(TranscribeRequest):
    subtitle_id: str = Field(max_length=64)


@app.post("/files/subtitle")
def import_subtitle(req: SubtitleRequest):
    source = resolve_source(req.project_id)
    reference = load_reference(project_folder(req.project_id))
    candidate = next(
        (x for x in reference.get("subtitles", []) if x["id"] == req.subtitle_id), None
    )
    if not candidate:
        raise HTTPException(404, "Subtítulo no encontrado")
    try:
        return {"srt": read_subtitle(source, candidate)}
    except subprocess.SubprocessError as exc:
        raise HTTPException(
            409,
            "FFmpeg no pudo leer esta pista; revisa el archivo o elige otro subtítulo",
        ) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc


class ExportRequest(TranscribeRequest):
    content: str = Field(max_length=20 * 1024 * 1024)
    language: Literal["es", "original"]
    format: Literal["srt", "vtt"]


@app.post("/files/export")
def export_next_to_source(req: ExportRequest):
    source = resolve_source(req.project_id)
    if not (project_folder(req.project_id) / "source.json").is_file():
        raise HTTPException(
            409,
            "Este proyecto antiguo no conserva la ubicación del vídeo original; usa Descargar",
        )
    base = f"{source.stem}.{req.language}"
    try:
        for index in range(10000):
            suffix = f" ({index})" if index else ""
            dest = source.parent / f"{base}{suffix}.{req.format}"
            try:
                with dest.open("x", encoding="utf-8", newline="") as output:
                    output.write(req.content)
                return {"filename": dest.name, "path": str(dest)}
            except FileExistsError:
                continue
        raise HTTPException(409, "No hay un nombre de exportación disponible")
    except OSError as exc:
        raise HTTPException(
            409, f"No se pudo guardar junto al vídeo: {exc.strerror or exc}"
        ) from exc


@app.post("/transcribe")
def transcribe(req: AudioTranscribeRequest):
    source = resolve_source(req.project_id)
    if req.audio_index is not None:
        reference = load_reference(project_folder(req.project_id))
        if req.audio_index not in [
            item["index"] for item in reference.get("audio_tracks", [])
        ]:
            raise HTTPException(400, "Pista de audio no autorizada o inexistente")
    try:
        if req.audio_index is None:
            return app.state.asr.transcribe(source)
        return app.state.asr.transcribe(source, audio_index=req.audio_index)
    except Exception as exc:
        raise HTTPException(502, f"Transcription error: {str(exc)[-2000:]}") from exc


class TranslateRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=6)
    context: str = ""


def model_subtitles(texts, context, instruction):
    entries = {str(i + 1): line for i, line in enumerate(texts)}
    prompt = (
        instruction
        + " Devuelve únicamente JSON con las mismas claves y un texto no vacío por clave. "
        + "Conserva cada entrada como una frase independiente. Contexto anterior: "
        + context
        + "\nEntradas: "
        + json.dumps(entries, ensure_ascii=False)
    )
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "system": "Eres un especialista profesional en subtítulos audiovisuales.",
        "stream": False,
        "format": "json",
        "think": False,
        "keep_alive": "10m",
        "options": {"temperature": 0, "num_ctx": 8192},
    }
    request = urllib.request.Request(
        OLLAMA + "/api/generate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=900) as response:
        res = json.load(response)
    obj = json.loads(res["response"])
    if not isinstance(obj, dict) or set(obj) != set(entries):
        raise ValueError("Invalid translation keys")
    values = [obj[str(i + 1)] for i in range(len(entries))]
    if not all(isinstance(v, str) for v in values):
        raise ValueError("Invalid subtitle values")
    return values


@app.post("/translate")
def translate(req: TranslateRequest):
    instruction = (
        "Traduce subtítulos audiovisuales al español de España con naturalidad y precisión. "
        "No resumas, no añadas información."
    )
    try:
        try:
            values = model_subtitles(req.texts, req.context, instruction)
        except ValueError:
            if len(req.texts) == 1:
                raise
            values = [
                model_subtitles([text], req.context, instruction)[0]
                for text in req.texts
            ]
        for index, value in enumerate(values):
            if not value.strip():
                single = model_subtitles([req.texts[index]], req.context, instruction)[
                    0
                ]
                if not single.strip():
                    raise ValueError(
                        f"Traducción vacía en entrada {index + 1}, incluso individualmente"
                    )
                values[index] = single
        return {"texts": values}
    except Exception as e:
        raise HTTPException(502, f"Translation error: {e}") from e


@app.post("/improve")
def improve(req: TranslateRequest):
    instruction = (
        "Corrige solo puntuación, mayúsculas y errores evidentes de transcripción en el idioma original. "
        "Conserva exactamente el sentido y las palabras cuando sean comprensibles; "
        "no traduzcas, resumas, agregues ni elimines información."
    )
    try:
        try:
            values = model_subtitles(req.texts, req.context, instruction)
        except ValueError:
            if len(req.texts) == 1:
                raise
            values = [
                model_subtitles([text], req.context, instruction)[0]
                for text in req.texts
            ]
        for index, value in enumerate(values):
            if not value.strip():
                single = model_subtitles([req.texts[index]], req.context, instruction)[
                    0
                ]
                if not single.strip():
                    raise ValueError(f"Mejora vacía en entrada {index + 1}")
                values[index] = single
        return {"texts": values}
    except Exception as exc:
        raise HTTPException(502, f"Error al mejorar texto: {exc}") from exc
