"""Read explicitly selected local media and discover associated subtitle sources."""

import json
import asyncio
import anyio
import subprocess
import uuid
import re
import math
from functools import lru_cache
from pathlib import Path

MEDIA_EXTENSIONS = {".mp4", ".mov", ".mkv", ".mp3", ".wav", ".m4a", ".webm", ".flac"}
TEXT_CODECS = {"subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text"}


def collect_media_sources(paths, limit=100):
    """Expand explicitly chosen folders without following symlinks or copying files."""
    result = []
    seen = set()
    for selected in paths:
        selected = Path(selected)
        if selected.is_symlink():
            continue
        if selected.is_dir():
            root = selected.resolve()
            candidates = selected.rglob("*")
        else:
            root = None
            candidates = [selected]
        for candidate in candidates:
            if (
                candidate.is_symlink()
                or not candidate.is_file()
                or candidate.suffix.lower() not in MEDIA_EXTENSIONS
            ):
                continue
            path = candidate.resolve()
            if root is not None and not path.is_relative_to(root):
                continue
            if path not in seen:
                seen.add(path)
                result.append(path)
                if len(result) > limit:
                    raise ValueError(
                        f"Selecciona como máximo {limit} archivos multimedia"
                    )
    return sorted(result, key=lambda path: str(path).casefold())


def choose_local_paths():
    script = """try
set choice to button returned of (display dialog "¿Qué quieres abrir?" buttons {"Cancelar", "Carpeta", "Archivos"} default button "Archivos" cancel button "Cancelar")
if choice is "Carpeta" then
    set picked to {choose folder with prompt "Elige la carpeta de vídeos o audios"}
else
    set picked to choose file with prompt "Elige vídeos o audios originales (sin copiar)" with multiple selections allowed
end if
set output to ""
repeat with itemPath in picked
    set output to output & (POSIX path of itemPath) & (ASCII character 0)
end repeat
return output
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
    paths = [Path(path) for path in result.stdout.rstrip("\n").split("\0") if path]
    return collect_media_sources(paths)


def audio_envelope(source, index, start, end, buckets):
    stat = source.stat()
    return list(
        _cached_envelope(
            str(source), stat.st_size, stat.st_mtime_ns, index, start, end, buckets
        )
    )


def media_duration(source):
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(source),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    duration = float(json.loads(result.stdout)["format"]["duration"])
    if not math.isfinite(duration) or not 0 < duration <= 43200:
        raise ValueError("Duración no disponible")
    return duration


@lru_cache(maxsize=64)
def _cached_envelope(path, size, modified, index, start, end, buckets):
    samples = max(1, math.ceil((end - start) * 8000 / buckets))
    result = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-nostats",
            "-v",
            "info",
            "-ss",
            str(start),
            "-i",
            path,
            "-t",
            str(end - start),
            "-map",
            f"0:{index}",
            "-vn",
            "-af",
            f"aresample=8000,asetnsamples=n={samples}:p=0,astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=True,
    )
    matches = re.findall(
        r"lavfi\.astats\.Overall\.RMS_level=(-inf|[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)", result.stderr
    )
    values = [
        0.0 if value == "-inf" else min(1.0, 10 ** (float(value) / 20))
        for value in matches
    ]
    return tuple((values + [0.0] * buckets)[:buckets])


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
                "match": True,
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
                    "match": True,
                    "language": tags.get("language", ""),
                    "reason": ""
                    if supported
                    else "Subtítulo de imagen o formato no compatible: necesita OCR/conversión.",
                }
            )
    except (OSError, ValueError, subprocess.SubprocessError):
        warnings.append(
            "No se pudieron inspeccionar las pistas incrustadas con FFprobe."
        )
    episode_pattern = re.compile(
        r"(?i)(?:s(\d{1,2})e(\d{1,3})|(?<!\d)(\d{1,2})x(\d{1,3}))"
    )

    def episode(name):
        match = episode_pattern.search(name)
        return (
            (
                int(match.group(1) or match.group(3)),
                int(match.group(2) or match.group(4)),
            )
            if match
            else None
        )

    target = episode(source.name)
    audio_language = (
        next(
            (
                s.get("tags", {}).get("language", "").lower()
                for s in info.get("streams", [])
                if s.get("codec_type") == "audio"
            ),
            "",
        )
        if "info" in locals()
        else ""
    )
    aliases = {
        "en": "eng",
        "english": "eng",
        "es": "spa",
        "spanish": "spa",
        "ro": "ron",
        "rum": "ron",
        "romanian": "ron",
        "pt": "por",
        "portuguese": "por",
    }
    audio_language = aliases.get(audio_language, audio_language)
    for candidate in candidates:
        if candidate["kind"] == "file":
            marker = episode(candidate["label"])
            if target:
                candidate["match"] = marker == target
            else:
                candidate["match"] = marker is None
            words = re.split(r"[^a-z]+", candidate["label"].lower())
            candidate["language"] = next(
                (
                    aliases.get(word, word)
                    for word in words
                    if word in aliases
                    or word in {"eng", "spa", "ron", "por", "fra", "deu", "ita"}
                ),
                "",
            )
    eligible = [c for c in candidates if c["match"] and c["supported"]]
    if eligible:

        def rank(c):
            language = c.get("language", "").lower()
            language = aliases.get(language, language)
            language_rank = (
                0
                if audio_language and language == audio_language
                else 1
                if language == "eng"
                else 2
            )
            origin_rank = (
                2 if c["kind"] == "embedded" else 1 if "/" in c["label"] else 0
            )
            return language_rank, origin_rank

        min(eligible, key=rank)["recommended"] = True
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


def decode_audio_chunk(source, index, start, duration=30):
    args = [
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-ss",
        str(start),
        "-i",
        str(source),
        "-map",
        f"0:{int(index)}" if index is not None else "0:a:0",
        "-t",
        str(duration),
        "-f",
        "s16le",
        "-ac",
        "1",
        "-ar",
        "16000",
        "pipe:1",
    ]
    return subprocess.run(args, capture_output=True, check=True).stdout


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
