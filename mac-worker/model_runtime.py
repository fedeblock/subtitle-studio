"""Lazy native MLX ownership. All model work stays on one Metal thread."""

import gc
import math
import time
from concurrent.futures import ThreadPoolExecutor


class ASRRuntime:
    def __init__(self, factory, cleanup, *, idle_seconds=600, clock=time.monotonic):
        self.factory = factory
        self.cleanup = cleanup
        self.idle_seconds = idle_seconds
        self.clock = clock
        self.executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="studio-metal"
        )
        self.session = None
        self.last_used = None

    def transcribe(self, path, audio_index=None):
        return self.executor.submit(self._transcribe, path, audio_index).result()

    def transcribe_chunk(self, path, start, audio_index=None, language=None):
        return self.executor.submit(
            self._transcribe_chunk, path, start, audio_index, language
        ).result()

    def _transcribe_chunk(self, path, start, audio_index, language):
        try:
            if self.session is None:
                self.session = self.factory()
            return self.session.transcribe_chunk(
                path, start, audio_index=audio_index, language=language
            )
        finally:
            self.last_used = self.clock()

    def _transcribe(self, path, audio_index=None):
        try:
            if self.session is None:
                self.session = self.factory()
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
        self.session = None
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
        from dataclasses import replace
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
        if not result.segments:
            if not result.text.strip():
                return {
                    "srt": "",
                    "end_of_audio": end_of_audio,
                    "language": result.language,
                }
            raise ValueError("ASR no devolvió segmentos con tiempos")
        segments = group_subtitle_segments(
            result.segments, language=result.language, text=result.text
        )
        shifted = [
            {**seg, "start": seg["start"] + start, "end": seg["end"] + start}
            for seg in segments
        ]
        payload = result_payload(replace(result, segments=shifted))
        payload["end_of_audio"] = end_of_audio
        return payload
