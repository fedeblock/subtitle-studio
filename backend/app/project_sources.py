import json
from pathlib import Path
from app.core import DATA


def reference(pid):
    path = Path(DATA) / pid / "source.json"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def save_workflow(pid, source, action, audio_index=None):
    path = Path(DATA) / pid / "source.json"
    info = reference(pid)
    info.update(selected_source=source, action=action, audio_index=audio_index)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(info, ensure_ascii=False))
    temp.replace(path)
