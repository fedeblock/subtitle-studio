from threading import get_ident
from types import SimpleNamespace
import pytest


def test_silent_cue_detection_uses_audio_energy_and_cue_boundaries():
    from model_runtime import silence_flags

    audio = [0.0] * 16000 + [0.1] * 16000
    flags = silence_flags(audio, [(0, 1), (1, 2), (0.5, 1.5)], 16000)
    assert flags == [True, False, False]


def test_asr_flags_follow_srt_positions_and_whisper_confidence():
    from model_runtime import annotate_asr_flags

    payload = {
        "srt": "1\n00:00:30,000 --> 00:00:31,000\nQuiet\n\n2\n00:00:31,000 --> 00:00:32,000\nUncertain\n"
    }
    audio = [0.0] * 16000 + [0.1] * 16000
    annotate_asr_flags(payload, audio, 30, [False, True])
    assert payload["flags"] == ["silence", "low_confidence"]


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


def test_invalid_qwen_alignment_preserves_text_with_estimated_chunk_timing():
    from model_runtime import qwen_chunk_payload

    result = SimpleNamespace(
        truncated=False, language="Romanian", text="Texto reconocido", segments=[]
    )
    payload = qwen_chunk_payload(
        result, [{"text": "Texto reconocido", "start": 0, "end": 0}], 30, 12
    )
    assert payload["estimated_timing"] is True
    assert "00:00:30,000 --> 00:00:42,000" in payload["srt"]
    assert "Texto reconocido" in payload["srt"]


def test_qwen_valid_alignment_keeps_real_times():
    from model_runtime import qwen_chunk_payload

    result = SimpleNamespace(
        truncated=False, language="Romanian", text="Hola", segments=[]
    )
    payload = qwen_chunk_payload(
        result, [{"text": "Hola", "start": 1, "end": 2}], 30, 30
    )
    assert not payload.get("estimated_timing", False)
    assert "00:00:31,000 --> 00:00:32,000" in payload["srt"]


def test_whisper_clamps_overrun_without_losing_text():
    from model_runtime import whisper_chunk_payload

    result = {
        "text": "uno dos",
        "language": "ro",
        "segments": [
            {"start": 27.32, "end": 29.32, "text": "uno"},
            {"start": 29.32, "end": 30.32, "text": "dos"},
        ],
    }
    payload = whisper_chunk_payload(result, 300, 30)
    assert "00:05:27,320 --> 00:05:29,320" in payload["srt"]
    assert "00:05:29,320 --> 00:05:30,000" in payload["srt"]
    assert "uno" in payload["srt"] and "dos" in payload["srt"]
    assert payload["estimated_timing"] is True


def test_whisper_preserves_unalignable_text_and_short_final_chunk():
    from model_runtime import whisper_chunk_payload

    result = {
        "text": "fuera",
        "language": "ro",
        "segments": [{"start": 8, "end": 9, "text": "fuera"}],
    }
    payload = whisper_chunk_payload(result, 30, 5.5)
    assert "00:00:30,000 --> 00:00:35,500" in payload["srt"]
    assert "fuera" in payload["srt"] and payload["estimated_timing"] is True


def test_whisper_valid_times_remain_unchanged():
    from model_runtime import whisper_chunk_payload

    result = {
        "text": "hola",
        "language": "es",
        "segments": [{"start": 0.1, "end": 2, "text": "hola"}],
    }
    payload = whisper_chunk_payload(result, 0, 30)
    assert "00:00:00,100 --> 00:00:02,000" in payload["srt"]
    assert "estimated_timing" not in payload


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


def test_model_switch_unloads_previous_session_on_its_owner_thread():
    from model_runtime import ASRRuntime

    events = []

    class Session:
        def __init__(self, name):
            self.name = name

        def transcribe_chunk(self, path, start, **kwargs):
            events.append(("transcribe", self.name, get_ident()))
            return {"srt": "", "end_of_audio": True}

        def close(self):
            events.append(("close", self.name, get_ident()))

    runtime = ASRRuntime(
        lambda: Session("qwen"),
        lambda: None,
        whisper_factory=lambda: Session("whisper"),
    )
    try:
        runtime.transcribe_chunk("clip", 0, model="qwen")
        runtime.transcribe_chunk("clip", 0, model="whisper")
        assert [(e[0], e[1]) for e in events] == [
            ("transcribe", "qwen"),
            ("close", "qwen"),
            ("transcribe", "whisper"),
        ]
        assert len({e[2] for e in events}) == 1
    finally:
        runtime.close()


def test_model_cannot_be_deleted_during_inference():
    from threading import Event, Thread
    from model_runtime import ASRRuntime

    started, release = Event(), Event()

    class Session:
        def transcribe_chunk(self, *args, **kwargs):
            started.set()
            assert release.wait(5)
            return {"srt": "", "end_of_audio": True}

    runtime = ASRRuntime(Session, lambda: None)
    thread = Thread(target=lambda: runtime.transcribe_chunk("clip", 0))
    thread.start()
    try:
        assert started.wait(5)
        with pytest.raises(RuntimeError, match="en curso"):
            runtime.remove_model(lambda: pytest.fail("must not delete"))
    finally:
        release.set()
        thread.join()
        runtime.close()
