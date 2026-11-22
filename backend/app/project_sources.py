import json
from pathlib import Path
from app.core import DATA


def reference(pid):
    path = Path(DATA) / pid / "source.json"
    if not path.exists():
        path = Path(DATA) / pid / "workflow.json"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def record_estimated_timing(pid, start):
    path = Path(DATA) / pid / "source.json"
    info = reference(pid)
    warnings = info.setdefault("timing_warnings", [])
    if start not in warnings:
        warnings.append(start)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(info, ensure_ascii=False))
        temp.replace(path)


def save_workflow(
    pid, source, action, audio_index=None, asr_language=None, asr_model=None,
    target_language=None, translation_model=None,
):
    path = Path(DATA) / pid / "source.json"
    if not path.exists():
        path = Path(DATA) / pid / "workflow.json"
    info = reference(pid)
    info.update(selected_source=source, action=action, audio_index=audio_index)
    if asr_language is not None:
        info["asr_language"] = asr_language
    if asr_model is not None:
        info["asr_model"] = asr_model
    if target_language is not None:
        info["target_language"] = target_language
    if translation_model is not None:
        info["translation_model"] = translation_model
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(info, ensure_ascii=False))
    temp.replace(path)
