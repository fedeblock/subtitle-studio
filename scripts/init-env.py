"""Create local secrets once; never replace an existing configuration."""

import os
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / ".env"
if path.exists():
    print(".env existente: conservado sin cambios.")
else:
    content = (root / ".env.example").read_text()
    content = content.replace("CHANGE_DB_PASSWORD", secrets.token_hex(28))
    content = content.replace("CHANGE_MAC_TOKEN", secrets.token_hex(36))
    # Exclusive creation and restrictive permissions from the first byte.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        output.write(content)
    print(".env creado con secretos aleatorios (0600).")
