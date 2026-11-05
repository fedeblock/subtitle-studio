from threading import get_ident
from types import SimpleNamespace
import pytest


def test_lazy_reuse_expiry_and_same_thread():
    from model_runtime import ASRRuntime

    now = [0.0]
    events = []

    class Session:
        def transcribe(self, path, **kwargs):
            events.append(("infer", get_ident()))
            now[0] += 1000  # Inference duration is not idle time.
            return {"srt": "result"}

    def factory():
        events.append(("load", get_ident()))
        return Session()

    def cleanup():
        events.append(("unload", get_ident()))

    runtime = ASRRuntime(factory, cleanup, clock=lambda: now[0])
    try:
        assert events == []
        assert runtime.transcribe("clip") == {"srt": "result"}
        now[0] += 599
        runtime.expire()
        assert [e[0] for e in events] == ["load", "infer"]
        runtime.transcribe("clip")
        now[0] += 600
        runtime.expire()
        assert [e[0] for e in events] == ["load", "infer", "infer", "unload"]
        runtime.transcribe("clip")
        assert [e[0] for e in events][-2:] == ["load", "infer"]
        assert len({e[1] for e in events}) == 1
        assert events[0][1] != get_ident()
    finally:
        runtime.close()


def test_failed_inference_still_expires():
    from model_runtime import ASRRuntime

    now = [0]
    unloaded = []

    class Session:
        def transcribe(self, path):
            raise ValueError("bad media")

    runtime = ASRRuntime(Session, lambda: unloaded.append(True), clock=lambda: now[0])
    try:
        with pytest.raises(ValueError):
            runtime.transcribe("bad")
        now[0] = 600
        runtime.expire()
        assert unloaded == [True]
    finally:
        runtime.close()


def test_asr_rejects_truncated_or_missing_timestamps():
    from model_runtime import result_payload

    for result in [
        SimpleNamespace(
            truncated=True, segments=[{"start": 0, "end": 1, "text": "hi"}]
        ),
        SimpleNamespace(truncated=False, segments=None),
    ]:
        with pytest.raises(ValueError):
            result_payload(result)


def test_asr_generates_valid_srt():
    from model_runtime import result_payload

    result = SimpleNamespace(
        truncated=False,
        language="English",
        segments=[{"start": 0.2, "end": 1.5, "text": "Hello world."}],
    )
    payload = result_payload(result)
    assert payload == {
        "language": "English",
        "srt": "1\n00:00:00,200 --> 00:00:01,500\nHello world.\n",
    }


def test_silence_detection_skips_only_very_low_amplitude_audio():
    from model_runtime import is_silent_audio

    class Audio:
        def __init__(self, low, high):
            self.low, self.high = low, high

        def min(self):
            return self.low

        def max(self):
            return self.high

    assert is_silent_audio(Audio(0, 0))
    assert not is_silent_audio(Audio(-0.01, 0.01))
