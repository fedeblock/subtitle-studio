"""Lazy native MLX ownership. All model work stays on one Metal thread."""

import gc
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock


class ASRRuntime:
    def __init__(
        self,
        factory,
        cleanup,
        *,
        idle_seconds=600,
        clock=time.monotonic,
        whisper_factory=None,
    ):
        self.factory = factory
        self.whisper_factory = whisper_factory
        self.cleanup = cleanup
        self.idle_seconds = idle_seconds
        self.clock = clock
        self.executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="studio-metal"
        )
        self.session = None
        self.model_name = None
        self.last_used = None
        self.operation_lock = Lock()

    def transcribe(self, path, audio_index=None):
        with self.operation_lock:
            return self.executor.submit(self._transcribe, path, audio_index).result()

    def transcribe_chunk(
        self, path, start, audio_index=None, language=None, model="qwen"
    ):
        with self.operation_lock:
            return self.executor.submit(
                self._transcribe_chunk, path, start, audio_index, language, model
            ).result()

    def remove_model(self, callback):
        if not self.operation_lock.acquire(blocking=False):
            raise RuntimeError("Hay una transcripción o comparación en curso")
        try:
            self.executor.submit(self._unload).result()
            return callback()
        finally:
            self.operation_lock.release()

    def compare_chunk(self, path, start, audio_index=None, language=None):
        with self.operation_lock:
            return self.executor.submit(
                self._compare_chunk, path, start, audio_index, language
            ).result()

    def _compare_chunk(self, path, start, audio_index, language):
        results = {}
        for model in ("qwen", "whisper"):
            began = self.clock()
            result = self._transcribe_chunk(path, start, audio_index, language, model)
            results[model] = {
                **result,
                "elapsed_seconds": round(self.clock() - began, 1),
            }
        return results

    def _transcribe_chunk(self, path, start, audio_index, language, model):
        try:
            if model not in ("qwen", "whisper"):
                raise ValueError("Modelo no disponible")
            if self.session is not None and self.model_name != model:
                self._unload()
            if self.session is None:
                factory = self.factory if model == "qwen" else self.whisper_factory
                if factory is None:
                    raise ValueError("Modelo no disponible")
                self.session = factory()
                self.model_name = model
            return self.session.transcribe_chunk(
                path, start, audio_index=audio_index, language=language
            )
        finally:
            self.last_used = self.clock()

    def _transcribe(self, path, audio_index=None):
        try:
            if self.session is not None and self.model_name != "qwen":
                self._unload()
            if self.session is None:
                self.session = self.factory()
                self.model_name = "qwen"
            if audio_index is None:
                return self.session.transcribe(path)
            return self.session.transcribe(path, audio_index=audio_index)
        finally:
            # Count inactivity from completion, including failures.
            self.last_used = self.clock()

    def expire(self):
        self.executor.submit(self._expire).result()

    def _expire(self):
        if (
            self.last_used is not None
            and self.clock() - self.last_used >= self.idle_seconds
        ):
            self._unload()

    def _unload(self):
        if self.session is not None and hasattr(self.session, "close"):
            self.session.close()
        self.session = None
        self.model_name = None
        self.last_used = None
        self.cleanup()

    def close(self):
        self.executor.submit(self._unload).result()
        self.executor.shutdown(wait=True)


def clear_metal():
    gc.collect()
    # No import/model allocation until the first actual inference.
    import sys

    mx = sys.modules.get("mlx.core")
    if mx is not None:
        mx.clear_cache()


def result_payload(result):
    if result.truncated:
        raise ValueError("ASR incompleto: se alcanzó el límite de generación")
    if not result.segments:
        raise ValueError("ASR no devolvió segmentos con tiempos")

    def timestamp(value):
        if not math.isfinite(value) or value < 0:
            raise ValueError("Timestamp ASR inválido")
        ms = round(value * 1000)
        hours, ms = divmod(ms, 3600000)
        minutes, ms = divmod(ms, 60000)
        seconds, ms = divmod(ms, 1000)
        return f"{hours:02}:{minutes:02}:{seconds:02},{ms:03}"

    blocks = []
    for segment in result.segments:
        start, end = segment["start"], segment["end"]
        text = segment["text"].strip()
        if end <= start or not text:
            continue
        blocks.append(
            f"{len(blocks) + 1}\n{timestamp(start)} --> {timestamp(end)}\n{text}"
        )
    if not blocks:
        raise ValueError("ASR no devolvió subtítulos válidos")
    return {"srt": "\n\n".join(blocks) + "\n", "language": result.language}


def is_silent_audio(audio):
    return max(abs(float(audio.min())), abs(float(audio.max()))) <= 2 / 32768


def silence_flags(audio, intervals, sample_rate=16000):
    """Mark cues whose audio is below -50 dB RMS for over 80% of 20 ms frames."""
    frame_size = max(1, sample_rate // 50)
    threshold_squared = 10 ** (-50 / 10)
    result = []
    for start, end in intervals:
        first = max(0, min(len(audio), int(start * sample_rate)))
        last = max(first, min(len(audio), int(end * sample_rate)))
        frames = silent = 0
        for offset in range(first, last, frame_size):
            frame = audio[offset : min(last, offset + frame_size)]
            energy = sum(float(value) ** 2 for value in frame) / len(frame)
            silent += energy < threshold_squared
            frames += 1
        result.append(bool(frames and silent / frames > 0.8))
    return result


def annotate_asr_flags(payload, audio, chunk_start, low_confidence=None):
    pattern = r"(?m)^(\d+):(\d{2}):(\d{2}),(\d{3}) --> (\d+):(\d{2}):(\d{2}),(\d{3})$"

    def seconds(groups):
        h, m, s, ms = map(int, groups)
        return 3600 * h + 60 * m + s + ms / 1000 - chunk_start

    intervals = [
        (seconds(m.groups()[:4]), seconds(m.groups()[4:]))
        for m in re.finditer(pattern, payload.get("srt", ""))
    ]
    silent = silence_flags(audio, intervals)
    confidence = (
        low_confidence
        if low_confidence and len(low_confidence) == len(intervals)
        else [False] * len(intervals)
    )
    flags = [
        "silence" if is_silent else "low_confidence" if low else None
        for is_silent, low in zip(silent, confidence)
    ]
    if any(flags):
        payload["flags"] = flags


def qwen_chunk_payload(result, segments, start, duration):
    from types import SimpleNamespace

    valid = bool(segments) and all(
        math.isfinite(s["start"])
        and math.isfinite(s["end"])
        and 0 <= s["start"] < s["end"] <= duration + 0.001
        and s["text"].strip()
        for s in segments
    )
    if not valid:
        text = result.text.strip()
        if not text:
            return {"srt": "", "language": result.language}
        segments = [{"start": 0, "end": max(duration, 0.001), "text": text}]
    shifted = [
        {**s, "start": s["start"] + start, "end": s["end"] + start} for s in segments
    ]
    payload = result_payload(
        SimpleNamespace(
            segments=shifted, language=result.language, truncated=result.truncated
        )
    )
    if not valid:
        payload["estimated_timing"] = True
    return payload


def whisper_chunk_payload(result, start, duration):
    """Keep the recognized text and constrain timestamps to decoded audio."""
    from types import SimpleNamespace

    duration = max(0.001, duration)
    adjusted = False
    segments = []
    for item in result.get("segments", []):
        text = item.get("text", "").strip()
        if not text:
            continue
        begin, end = item.get("start"), item.get("end")
        if (
            not isinstance(begin, (int, float))
            or not isinstance(end, (int, float))
            or not math.isfinite(begin)
            or not math.isfinite(end)
        ):
            begin, end = 0, duration
            adjusted = True
        else:
            clipped_begin, clipped_end = max(0, begin), min(duration, end)
            if round(clipped_end * 1000) <= round(clipped_begin * 1000):
                clipped_begin, clipped_end = 0, duration
            if clipped_begin != begin or clipped_end != end:
                adjusted = True
            begin, end = clipped_begin, clipped_end
        segments.append({"start": start + begin, "end": start + end, "text": text})
    if not segments:
        text = result.get("text", "").strip()
        if not text:
            return {"srt": "", "language": result.get("language", "auto")}
        segments = [{"start": start, "end": start + duration, "text": text}]
        adjusted = True
    payload = result_payload(
        SimpleNamespace(
            segments=segments, truncated=False, language=result.get("language", "auto")
        )
    )
    if adjusted:
        payload["estimated_timing"] = True
    return payload


class MLXSession:
    def __init__(self, model, aligner_model):
        from mlx_qwen3_asr import Session
        from mlx_qwen3_asr.forced_aligner import ForcedAligner

        self.asr = Session(model=model)
        self.aligner = ForcedAligner(model_path=aligner_model)

    def transcribe(self, path, audio_index=None):
        audio = str(path)
        if audio_index is not None:
            import numpy as np
            from local_files import decode_audio

            pcm = decode_audio(path, audio_index)
            audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        result = self.asr.transcribe(
            audio, return_timestamps=True, forced_aligner=self.aligner
        )
        # Upstream timestamps are words; preserve the CLI's sentence grouping.
        from dataclasses import replace
        from mlx_qwen3_asr.writers import group_subtitle_segments

        if result.segments:
            result = replace(
                result,
                segments=group_subtitle_segments(
                    result.segments, language=result.language, text=result.text
                ),
            )
        return result_payload(result)

    def transcribe_chunk(self, path, start, audio_index=None, language=None):
        import numpy as np
        from local_files import decode_audio_chunk
        from mlx_qwen3_asr.writers import group_subtitle_segments

        pcm = decode_audio_chunk(path, audio_index, start)
        end_of_audio = len(pcm) < 30 * 16000 * 2
        if not pcm:
            return {"srt": "", "end_of_audio": True, "language": language or "auto"}
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        # Digital silence has no speech to align; Qwen can emit zero-length
        # hallucinations for it, so do not advance through the aligner.
        if is_silent_audio(audio):
            return {
                "srt": "",
                "end_of_audio": end_of_audio,
                "language": language or "auto",
            }
        result = self.asr.transcribe(
            audio,
            language=language,
            return_timestamps=True,
            forced_aligner=self.aligner,
        )
        if result.truncated:
            raise ValueError("ASR incompleto: se alcanzó el límite de generación")
        segments = (
            group_subtitle_segments(
                result.segments, language=result.language, text=result.text
            )
            if result.segments
            else []
        )
        payload = qwen_chunk_payload(result, segments, start, len(audio) / 16000)
        annotate_asr_flags(payload, audio, start)
        payload["end_of_audio"] = end_of_audio
        return payload


class WhisperSession:
    def __init__(self, model="mlx-community/whisper-large-v3-mlx"):
        self.model = model

    def transcribe_chunk(self, path, start, audio_index=None, language=None):
        import numpy as np
        import mlx_whisper
        from local_files import decode_audio_chunk

        pcm = decode_audio_chunk(path, audio_index, start)
        end = len(pcm) < 30 * 16000 * 2
        if not pcm:
            return {"srt": "", "end_of_audio": True, "language": language or "auto"}
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        if is_silent_audio(audio):
            return {"srt": "", "end_of_audio": end, "language": language or "auto"}
        language_codes = {
            "Romanian": "ro",
            "Spanish": "es",
            "English": "en",
            "Portuguese": "pt",
            "French": "fr",
            "Italian": "it",
            "German": "de",
            "Dutch": "nl",
            "Japanese": "ja",
            "Chinese": "zh",
        }
        code = language_codes.get(language) if language else None
        if language and not code:
            raise ValueError("Idioma no admitido por Whisper")
        result = mlx_whisper.transcribe(
            audio, path_or_hf_repo=self.model, language=code, verbose=None
        )
        payload = whisper_chunk_payload(result, start, len(audio) / 16000)
        confidence = [
            (
                isinstance(segment.get("avg_logprob"), (int, float))
                and segment["avg_logprob"] < -1.0
            )
            or (
                isinstance(segment.get("no_speech_prob"), (int, float))
                and segment["no_speech_prob"] > 0.6
            )
            for segment in result.get("segments", [])
            if segment.get("text", "").strip()
        ]
        annotate_asr_flags(payload, audio, start, confidence)
        payload["end_of_audio"] = end
        return payload

    def close(self):
        import importlib

        module = importlib.import_module("mlx_whisper.transcribe")
        module.ModelHolder.model = None
        module.ModelHolder.model_path = None
