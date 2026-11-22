import os
import json
import pathlib
import urllib.request
import asyncio
import signal
import secrets
import time
import subprocess
import sys
import tempfile
import anyio
from contextlib import asynccontextmanager, suppress
from model_runtime import ASRRuntime, MLXSession, WhisperSession, clear_metal
from model_catalog import catalog, model_entries, deletion_strategies, is_hub_repo
from idle_lifecycle import IdleTracker, TrackActivity
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, FileResponse, Response, StreamingResponse
from uuid import UUID, uuid4
from typing import Literal
from threading import Lock
from local_files import (
    choose_local_file,
    choose_local_paths,
    discover_subtitles,
    discover_audio,
    audio_preview,
    audio_envelope,
    media_duration,
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
IDLE_SECONDS = int(os.environ.get("STUDIO_IDLE_SECONDS", "600"))
activity = IdleTracker(IDLE_SECONDS)


@asynccontextmanager
async def lifespan(app):
    app.state.asr = ASRRuntime(
        lambda: MLXSession(ASR_MODEL, ALIGNER_MODEL),
        clear_metal,
        idle_seconds=IDLE_SECONDS,
        whisper_factory=WhisperSession,
    )

    async def sweep():
        while True:
            await asyncio.sleep(1)
            await asyncio.to_thread(app.state.asr.expire)
            if os.environ.get("STUDIO_LAUNCHD_SOCKET") == "1" and activity.expired():
                os.kill(os.getpid(), signal.SIGTERM)
                return

    task = asyncio.create_task(sweep())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await asyncio.to_thread(app.state.asr.close)


app = FastAPI(title="Subtitle Studio Mac inference gateway", lifespan=lifespan)
app.add_middleware(TrackActivity, tracker=activity)


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


class ChunkTranscribeRequest(AudioTranscribeRequest):
    segment_start: int = Field(ge=0)
    language: str | None = Field(default=None, min_length=1, max_length=64)
    model: Literal["qwen", "whisper"] = "qwen"


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


def write_source_reference(pid, source):
    if not source.is_file() or source.suffix.lower() not in MEDIA_EXTENSIONS:
        raise ValueError("Selecciona un vídeo o audio compatible")
    folder = project_folder(pid)
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
    return {"id": str(pid), "name": source.name, "filename": "source.json"}


@app.post("/files/select-many")
def select_many_files():
    if not picker_lock.acquire(blocking=False):
        raise HTTPException(409, "Ya hay un selector abierto en macOS")
    try:
        sources = choose_local_paths()
        if not sources:
            return Response(status_code=204)
        entries, errors = [], []
        for source in sources:
            try:
                entries.append(write_source_reference(uuid4(), source))
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                errors.append({"name": source.name, "error": str(exc)[-300:]})
        if not entries:
            raise HTTPException(
                409, "No se pudo abrir ninguno de los archivos seleccionados"
            )
        return {"projects": entries, "errors": errors}
    except subprocess.SubprocessError as exc:
        raise HTTPException(
            409, "El selector de macOS no respondió; vuelve a intentarlo"
        ) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        picker_lock.release()


@app.post("/files/select")
def select_file(req: TranscribeRequest):
    if not picker_lock.acquire(blocking=False):
        raise HTTPException(409, "Ya hay un selector abierto en macOS")
    try:
        source = choose_local_file()
        if source is None:
            return Response(status_code=204)
        entry = write_source_reference(req.project_id, source)
        return {"name": entry["name"], "filename": entry["filename"]}
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


@app.get("/files/{pid}/envelope")
def envelope(
    pid: UUID,
    index: int = Query(ge=0),
    start: float = Query(ge=0, allow_inf_nan=False),
    end: float = Query(gt=0, le=43200, allow_inf_nan=False),
    buckets: int = Query(ge=1, le=400),
):
    source = resolve_source(pid)
    reference = load_reference(project_folder(pid))
    if index not in [item["index"] for item in reference.get("audio_tracks", [])]:
        raise HTTPException(400, "Pista de audio no autorizada o inexistente")
    if end <= start:
        raise HTTPException(422, "El final debe ser posterior al inicio")
    try:
        return {"amplitudes": audio_envelope(source, index, start, end, buckets)}
    except (OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(409, "No se pudo analizar el audio") from exc


@app.get("/files/{pid}/envelope/overview")
def envelope_overview(pid: UUID, index: int = Query(ge=0)):
    source = resolve_source(pid)
    try:
        duration = media_duration(source)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        raise HTTPException(409, "No se pudo determinar la duración del audio") from exc
    return {**envelope(pid, index, 0, duration, 400), "duration": duration}


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


class SyncSubtitlesRequest(AudioTranscribeRequest):
    srt: str = Field(min_length=1, max_length=5_000_000)


@app.post("/files/sync-subtitles")
def sync_subtitles(req: SyncSubtitlesRequest):
    source = resolve_source(req.project_id)
    reference = load_reference(project_folder(req.project_id))
    tracks = reference.get("audio_tracks", [])
    if req.audio_index is None or req.audio_index not in [t["index"] for t in tracks]:
        raise HTTPException(400, "Elige una pista de audio disponible")
    audio_ordinal = next(i for i, track in enumerate(tracks) if track["index"] == req.audio_index)
    executable = pathlib.Path(sys.executable).parent / "ffsubsync"
    try:
        with tempfile.TemporaryDirectory(prefix="subtitle-studio-sync-") as tmp:
            input_path = pathlib.Path(tmp) / "input.srt"
            output_path = pathlib.Path(tmp) / "output.srt"
            input_path.write_text(req.srt, encoding="utf-8")
            result = subprocess.run(
                [str(executable), str(source), "-i", str(input_path), "-o", str(output_path),
                 "--reference-stream", f"0:a:{audio_ordinal}"],
                capture_output=True, text=True, timeout=1800, check=False,
            )
            if result.returncode or not output_path.is_file():
                raise HTTPException(422, "No se pudo sincronizar el subtítulo con esta pista de audio")
            return {"srt": output_path.read_text(encoding="utf-8-sig")}
    except FileNotFoundError as exc:
        raise HTTPException(503, "ffsubsync no está instalado; ejecuta scripts/setup.sh") from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(504, "La sincronización tardó demasiado") from exc


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
    language: Literal[
        "es",
        "ro",
        "en",
        "pt",
        "fr",
        "it",
        "de",
        "nl",
        "ja",
        "zh",
        "original",
        "bilingual",
    ]
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


@app.post("/transcribe-chunk")
def transcribe_chunk(req: ChunkTranscribeRequest):
    source = resolve_source(req.project_id)
    if req.audio_index is not None:
        reference = load_reference(project_folder(req.project_id))
        if req.audio_index not in [
            item["index"] for item in reference.get("audio_tracks", [])
        ]:
            raise HTTPException(400, "Pista de audio no autorizada o inexistente")
    try:
        return app.state.asr.transcribe_chunk(
            source,
            req.segment_start,
            audio_index=req.audio_index,
            language=req.language,
            model=req.model,
        )
    except Exception as exc:
        raise HTTPException(502, f"Transcription error: {str(exc)[-2000:]}") from exc


@app.get("/models")
def list_models():
    from huggingface_hub import scan_cache_dir
    from huggingface_hub.errors import CacheNotFound
    from types import SimpleNamespace

    try:
        cache = scan_cache_dir()
    except CacheNotFound:
        cache = SimpleNamespace(repos=[])
    return model_entries(cache, ASR_MODEL, ALIGNER_MODEL)


@app.post("/models/{model}/download")
def download_model(model: Literal["qwen", "whisper"]):
    from huggingface_hub import snapshot_download

    def download():
        for repo in catalog(ASR_MODEL, ALIGNER_MODEL)[model]["repos"]:
            if not is_hub_repo(repo):
                raise ValueError("La configuración contiene una ruta local")
            snapshot_download(repo_id=repo)

    try:
        app.state.asr.remove_model(download)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            502, f"No se pudo descargar el modelo: {str(exc)[-500:]}"
        ) from exc
    return {"ok": True}


@app.delete("/models/{model}")
def delete_model(model: Literal["qwen", "whisper"]):
    from huggingface_hub import scan_cache_dir
    from huggingface_hub.errors import CacheNotFound

    def remove():
        try:
            cache = scan_cache_dir()
        except CacheNotFound:
            return 0
        strategies = deletion_strategies(cache, model, ASR_MODEL, ALIGNER_MODEL)
        freed = sum(strategy.expected_freed_size for strategy in strategies)
        for strategy in strategies:
            strategy.execute()
        return freed

    try:
        freed = app.state.asr.remove_model(remove)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"freed_bytes": freed}


@app.post("/compare-models")
def compare_models(req: ChunkTranscribeRequest):
    source = resolve_source(req.project_id)
    if req.audio_index is not None:
        reference = load_reference(project_folder(req.project_id))
        if req.audio_index not in [
            item["index"] for item in reference.get("audio_tracks", [])
        ]:
            raise HTTPException(400, "Pista de audio no autorizada o inexistente")
    try:
        results = app.state.asr.compare_chunk(
            source,
            req.segment_start,
            audio_index=req.audio_index,
            language=req.language,
        )
        return {"start": req.segment_start, "results": results}
    except Exception as exc:
        raise HTTPException(502, f"No se pudo comparar: {str(exc)[-500:]}") from exc


class TranslateRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=6)
    context: str = ""
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
    ] = "Spanish"


def model_subtitles(texts, context, instruction, model=None):
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
        "model": model or MODEL,
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


def translation_instruction(target_language):
    languages = {
        "Spanish": "español de España",
        "Romanian": "rumano",
        "English": "inglés",
        "Portuguese": "portugués",
        "French": "francés",
        "Italian": "italiano",
        "German": "alemán",
        "Dutch": "neerlandés",
        "Japanese": "japonés",
        "Chinese": "chino",
    }
    return (
        f"Traduce subtítulos audiovisuales al {languages[target_language]} con naturalidad y precisión. "
        "No resumas, no añadas información."
    )


def ollama_models():
    with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=10) as response:
        data = json.load(response)
    return [
        {"name": item["name"], "size": item.get("size", 0)}
        for item in data.get("models", [])
        if isinstance(item.get("name"), str)
    ]


@app.get("/ollama/models")
def list_ollama_models():
    try:
        return ollama_models()
    except Exception as exc:
        raise HTTPException(
            503, "No se pueden consultar los modelos de Ollama"
        ) from exc


class CompareTranslationRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
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
    models: list[str] = Field(min_length=2, max_length=2)


class CompareTranslationRangeRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=8)
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
    models: list[str] = Field(min_length=2, max_length=2)


@app.post("/compare-translations-range")
def compare_translations_range(req: CompareTranslationRangeRequest):
    if any(not text.strip() or len(text) > 10000 for text in req.texts):
        raise HTTPException(422, "El rango contiene texto vacío o demasiado largo")
    try:
        installed = {item["name"] for item in ollama_models()}
    except Exception as exc:
        raise HTTPException(
            503, "No se pueden consultar los modelos de Ollama"
        ) from exc
    if len(set(req.models)) != 2 or not set(req.models).issubset(installed):
        raise HTTPException(400, "Elige dos modelos diferentes ya instalados en Ollama")
    results = []
    for model in req.models:
        started = time.monotonic()
        try:
            values = model_subtitles(
                req.texts, "", translation_instruction(req.target_language), model=model
            )
            if len(values) != len(req.texts) or not all(
                isinstance(value, str) and value.strip() for value in values
            ):
                raise ValueError("El modelo no devolvió una traducción por segmento")
            results.append(
                {
                    "model": model,
                    "texts": values,
                    "seconds": round(time.monotonic() - started, 2),
                }
            )
        except Exception as exc:
            results.append(
                {
                    "model": model,
                    "error": str(exc)[:300],
                    "seconds": round(time.monotonic() - started, 2),
                }
            )
    return {"results": results}


@app.post("/compare-translations")
def compare_translations(req: CompareTranslationRequest):
    try:
        installed = {item["name"] for item in ollama_models()}
    except Exception as exc:
        raise HTTPException(
            503, "No se pueden consultar los modelos de Ollama"
        ) from exc
    if len(set(req.models)) != 2 or not set(req.models).issubset(installed):
        raise HTTPException(400, "Elige dos modelos diferentes ya instalados en Ollama")
    results = []
    for model in req.models:
        started = time.monotonic()
        try:
            text = model_subtitles(
                [req.text],
                "",
                translation_instruction(req.target_language),
                model=model,
            )[0]
            if not text.strip():
                raise ValueError("La traducción está vacía")
            results.append(
                {
                    "model": model,
                    "text": text,
                    "seconds": round(time.monotonic() - started, 2),
                }
            )
        except Exception as exc:
            results.append(
                {
                    "model": model,
                    "error": str(exc)[:300],
                    "seconds": round(time.monotonic() - started, 2),
                }
            )
    return {"results": results}


@app.post("/translate")
def translate(req: TranslateRequest):
    instruction = translation_instruction(req.target_language)

    def generate(texts):
        if req.model:
            return model_subtitles(texts, req.context, instruction, model=req.model)
        return model_subtitles(texts, req.context, instruction)

    try:
        try:
            values = generate(req.texts)
        except ValueError:
            if len(req.texts) == 1:
                raise
            values = [generate([text])[0] for text in req.texts]
        for index, value in enumerate(values):
            if not value.strip():
                single = generate([req.texts[index]])[0]
                if not single.strip():
                    raise ValueError(
                        f"Traducción vacía en entrada {index + 1}, incluso individualmente"
                    )
                values[index] = single
        return {"texts": values}
    except Exception as e:
        raise HTTPException(502, f"Translation error: {e}") from e


class ImprovementRequest(TranslateRequest):
    model: str | None = Field(default=None, min_length=1, max_length=200)


@app.post("/improve")
def improve(req: ImprovementRequest):
    if req.model:
        try:
            installed = {item["name"] for item in ollama_models()}
        except Exception as exc:
            raise HTTPException(
                503, "No se pueden consultar los modelos de Ollama"
            ) from exc
        if req.model not in installed:
            raise HTTPException(
                400, "El modelo seleccionado no está instalado en Ollama"
            )
    instruction = (
        "Corrige solo puntuación, mayúsculas y errores evidentes de transcripción en el idioma original. "
        "Conserva exactamente el sentido y las palabras cuando sean comprensibles; "
        "no traduzcas, resumas, agregues ni elimines información."
    )

    def run(texts):
        if req.model:
            return model_subtitles(texts, req.context, instruction, model=req.model)
        return model_subtitles(texts, req.context, instruction)

    try:
        try:
            values = run(req.texts)
        except ValueError:
            if len(req.texts) == 1:
                raise
            values = [run([text])[0] for text in req.texts]
        for index, value in enumerate(values):
            if not value.strip():
                single = run([req.texts[index]])[0]
                if not single.strip():
                    raise ValueError(f"Mejora vacía en entrada {index + 1}")
                values[index] = single
        return {"texts": values}
    except Exception as exc:
        raise HTTPException(502, f"Error al mejorar texto: {exc}") from exc
