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

    def transcribe(self, path):
        return self.executor.submit(self._transcribe, path).result()

    def _transcribe(self, path):
        try:
            if self.session is None:
                self.session = self.factory()
            return self.session.transcribe(path)
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


class MLXSession:
    def __init__(self, model, aligner_model):
        from mlx_qwen3_asr import Session
        from mlx_qwen3_asr.forced_aligner import ForcedAligner

        self.asr = Session(model=model)
        self.aligner = ForcedAligner(model_path=aligner_model)

    def transcribe(self, path):
        result = self.asr.transcribe(
            str(path), return_timestamps=True, forced_aligner=self.aligner
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
