"""Recoverable snapshots for optional transcript corrections."""

import json
import os
from pathlib import Path
from app.core import DATA


def snapshots(pid):
    folder = Path(DATA) / pid
    return sorted(
        folder.glob("improvement-*.json"),
        key=lambda p: p.stat().st_mtime_ns,
        reverse=True,
    )


def latest(pid):
    for path in snapshots(pid):
        try:
            content = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not content.get("restored"):
            return path, content
    return None, None


def write(path, content):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(content, ensure_ascii=False))
    os.chmod(temp, 0o600)
    temp.replace(path)
