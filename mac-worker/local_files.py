"""Read explicitly selected local media and discover associated subtitle sources."""

import json
import asyncio
import anyio
import subprocess
import uuid
from pathlib import Path

MEDIA_EXTENSIONS = {".mp4", ".mov", ".mkv", ".mp3", ".wav", ".m4a", ".webm", ".flac"}
TEXT_CODECS = {"subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text"}


def choose_local_file():
    script = """try
return POSIX path of (choose file with prompt "Abrir vídeo o audio original (sin copiar)")
on error number -128
return ""
end try"""
    result = subprocess.run(
        ["/usr/bin/osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode:
        raise ValueError(
            "No se pudo abrir el selector de macOS: " + result.stderr[-500:]
        )
    path = result.stdout.rstrip("\n")
    return Path(path).resolve() if path else None


def probe_media(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return json.loads(result.stdout)


def discover_subtitles(source, probe=probe_media):
    parent = source.parent.resolve()
    candidates = []
    warnings = []
    files = list(parent.glob("*"))
    for folder in sorted(parent.iterdir()):
        if (
            folder.is_dir()
            and not folder.is_symlink()
            and folder.name.lower() in {"subs", "subtitles"}
        ):
            files.extend(folder.glob("*"))
            for child in folder.iterdir():
                if child.is_dir() and not child.is_symlink():
                    files.extend(child.glob("*"))
    for path in sorted(set(files)):
        if (
            path.suffix.lower() not in {".srt", ".vtt", ".ass", ".ssa"}
            or not path.is_file()
            or path.is_symlink()
        ):
            continue
        if not path.resolve().is_relative_to(parent):
            continue
        candidates.append(
            {
                "id": uuid.uuid4().hex,
                "kind": "file",
                "label": str(path.relative_to(parent)),
                "path": str(path.resolve()),
                "supported": True,
            }
        )
        if len(candidates) >= 200:
            warnings.append("Se muestran los primeros 200 archivos de subtítulos.")
            break
    try:
        info = probe(source)
        for stream in info.get("streams", []):
            if stream.get("codec_type") != "subtitle":
                continue
            codec = stream.get("codec_name", "unknown")
            tags = stream.get("tags", {})
            label = f"Pista {stream['index']} · {tags.get('language', 'sin idioma')} · {tags.get('title', codec)}"
            supported = codec in TEXT_CODECS
            candidates.append(
                {
                    "id": uuid.uuid4().hex,
                    "kind": "embedded",
                    "label": label,
                    "stream_index": stream["index"],
                    "codec": codec,
                    "supported": supported,
                    "reason": ""
                    if supported
                    else "Subtítulo de imagen o formato no compatible: necesita OCR/conversión.",
                }
            )
    except (OSError, ValueError, subprocess.SubprocessError):
        warnings.append(
            "No se pudieron inspeccionar las pistas incrustadas con FFprobe."
        )
    return candidates, warnings


def read_subtitle(source, candidate):
    if not candidate.get("supported"):
        raise ValueError("Esta pista necesita OCR/conversión antes de editarse")
    if candidate["kind"] == "file":
        path = Path(candidate["path"])
        if path.resolve() != path or not path.resolve().is_relative_to(
            source.parent.resolve()
        ):
            raise ValueError("La ruta del subtítulo ha cambiado")
        if not path.is_file():
            raise FileNotFoundError("El subtítulo se movió o ya no está disponible")
        if path.stat().st_size > 20 * 1024 * 1024:
            raise ValueError("Subtítulo demasiado grande (20 MiB máximo)")
        if path.suffix.lower() == ".srt":
            data = path.read_bytes()
            try:
                return data.decode("utf-8-sig")
            except UnicodeDecodeError:
                return data.decode("cp1252")
        args = ["-i", str(path)]
    else:
        args = ["-i", str(source), "-map", f"0:{int(candidate['stream_index'])}"]
    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", *args, "-f", "srt", "pipe:1"],
        capture_output=True,
        timeout=60,
        check=True,
    )
    if len(result.stdout) > 20 * 1024 * 1024:
        raise ValueError("Subtítulo demasiado grande")
    return result.stdout.decode("utf-8-sig")


def discover_audio(source, probe=probe_media):
    streams = probe(source).get("streams", [])
    tracks = []
    for stream in streams:
        if stream.get("codec_type") != "audio":
            continue
        tags = stream.get("tags", {})
        index = int(stream["index"])
        tracks.append(
            {
                "index": index,
                "label": f"Pista {index} · {tags.get('language', 'sin idioma')} · {tags.get('title', stream.get('codec_name', 'audio'))}",
            }
        )
    return tracks


def decode_audio(source, index):
    result = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(source),
            "-map",
            f"0:{int(index)}",
            "-f",
            "s16le",
            "-ac",
            "1",
            "-ar",
            "16000",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    )
    if not result.stdout:
        raise ValueError("La pista de audio está vacía")
    return result.stdout


def audio_preview(source, index, start, duration=30):
    result = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-ss",
            str(start),
            "-i",
            str(source),
            "-map",
            f"0:{int(index)}",
            "-t",
            str(duration),
            "-vn",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "96k",
            "-f",
            "mp3",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
        timeout=60,
    )
    if not result.stdout:
        raise ValueError("No hay audio en esa posición")
    return result.stdout


async def stream_audio(source, index, start):
    """Encode a selected track on demand, without writing media to disk."""
    process = await asyncio.create_subprocess_exec(
        *[
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-ss",
            str(start),
            "-i",
            str(source),
            "-map",
            f"0:{int(index)}",
            "-vn",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "128k",
            "-f",
            "mp3",
            "pipe:1",
        ],
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        while chunk := await process.stdout.read(8192):
            yield chunk
    finally:
        if process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
        with anyio.CancelScope(shield=True):
            try:
                await asyncio.wait_for(process.stdout.read(), timeout=3)
                await asyncio.wait_for(process.wait(), timeout=3)
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(process.wait(), timeout=3)
                except asyncio.TimeoutError:
                    pass
