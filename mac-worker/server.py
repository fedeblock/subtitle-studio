import os
import json
import pathlib
import urllib.request
import asyncio
import secrets
from contextlib import asynccontextmanager, suppress
from model_runtime import ASRRuntime, MLXSession, clear_metal
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
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


@app.post("/transcribe")
def transcribe(req: TranscribeRequest):
    folder = (ROOT / req.project_id).resolve()
    if folder.parent != ROOT:
        raise HTTPException(400, "Invalid project")
    files = [f for f in folder.glob("source.*") if f.is_file()]
    if len(files) != 1:
        raise HTTPException(404, "Source missing")
    source = files[0].resolve()
    if source.parent != folder:
        raise HTTPException(400, "Invalid source path")
    try:
        return app.state.asr.transcribe(source)
    except Exception as exc:
        raise HTTPException(502, f"Transcription error: {str(exc)[-2000:]}") from exc


class TranslateRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=6)
    context: str = ""


@app.post("/translate")
def translate(req: TranslateRequest):
    entries = {str(i + 1): line for i, line in enumerate(req.texts)}
    prompt = (
        "Traduce subtítulos audiovisuales al español de España con naturalidad y precisión. "
        "No resumas, no añadas información. Devuelve únicamente JSON con las mismas claves. "
        "Conserva cada entrada como una frase independiente. Contexto anterior: "
        + req.context
        + "\nEntradas: "
        + json.dumps(entries, ensure_ascii=False)
    )
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "system": "Eres un traductor audiovisual profesional.",
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
    try:
        with urllib.request.urlopen(request, timeout=900) as response:
            res = json.load(response)
        obj = json.loads(res["response"])
        if not isinstance(obj, dict) or set(obj) != set(entries):
            raise ValueError("Invalid translation keys")
        values = [obj[str(i + 1)] for i in range(len(entries))]
        if not all(isinstance(v, str) and v.strip() for v in values):
            raise ValueError("Empty translations")
        return {"texts": values}
    except Exception as e:
        raise HTTPException(502, f"Translation error: {e}")
