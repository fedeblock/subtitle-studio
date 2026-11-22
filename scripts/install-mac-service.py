#!/usr/bin/env python3
"""Install the native gateway as a per-user launchd service on macOS."""

import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime

LABEL = "com.subtitle-studio.gateway"


def bootstrap(domain, target):
    # bootout may return before the former gateway has released its port.
    for attempt in range(12):
        result = subprocess.run(
            ["launchctl", "bootstrap", domain, str(target)],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return
        if (
            subprocess.run(
                ["launchctl", "print", f"{domain}/{LABEL}"], capture_output=True
            ).returncode
            == 0
        ):
            return
        if attempt < 11:
            time.sleep(1)
    raise subprocess.CalledProcessError(
        result.returncode, result.args, stderr=result.stderr
    )


def agent_config(root, logs, ffmpeg_dir, port=8765, bind_host="0.0.0.0", legacy=False):
    search_path = list(
        dict.fromkeys(
            [
                ffmpeg_dir,
                "/opt/homebrew/bin",
                "/usr/local/bin",
                "/usr/bin",
                "/bin",
                "/usr/sbin",
                "/sbin",
            ]
        )
    )
    config = {
        "Label": LABEL,
        "ProgramArguments": ["/bin/bash", str(root / "scripts" / "start-mac.sh")],
        "WorkingDirectory": str(root),
        "EnvironmentVariables": {"PATH": ":".join(search_path)},
        "ThrottleInterval": 10,
        "StandardOutPath": str(logs / "subtitle-studio-gateway.out.log"),
        "StandardErrorPath": str(logs / "subtitle-studio-gateway.err.log"),
    }
    if legacy:
        config.update(RunAtLoad=True, KeepAlive=True)
    else:
        config["EnvironmentVariables"]["STUDIO_LAUNCHD_SOCKET"] = "1"
        config["Sockets"] = {
            "Listeners": {
                "SockServiceName": str(port),
                "SockNodeName": bind_host,
                "SockFamily": "IPv4",
                "SockType": "stream",
            }
        }
    return config


def main():
    if sys.platform != "darwin":
        raise SystemExit("Este servicio requiere macOS.")
    root = Path(__file__).resolve().parents[1]
    if not (root / ".env").is_file() or not os.access(
        root / "mac-worker/.venv/bin/python", os.X_OK
    ):
        raise SystemExit("Ejecuta primero: bash scripts/setup.sh")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("No se encontró FFmpeg en el PATH.")
    folder = Path.home() / "Library/LaunchAgents"
    folder.mkdir(parents=True, exist_ok=True)
    settings = subprocess.check_output(
        [
            str(root / "mac-worker/.venv/bin/python"),
            "-c",
            "import os,sys; from dotenv import dotenv_values; d=dotenv_values(sys.argv[1],interpolate=False); print(os.environ.get('MAC_PORT',d.get('MAC_PORT') or '8765')); print(os.environ.get('MAC_BIND_HOST',d.get('MAC_BIND_HOST') or '0.0.0.0'))",
            str(root / ".env"),
        ],
        text=True,
    ).splitlines()
    port, bind_host = int(settings[0]), settings[1]
    if not 1 <= port <= 65535:
        raise SystemExit("MAC_PORT debe estar entre 1 y 65535.")
    logs = Path.home() / "Library/Logs"
    ffmpeg_dir = str(Path(ffmpeg).parent)
    config = agent_config(root, logs, ffmpeg_dir, port, bind_host)
    target = folder / f"{LABEL}.plist"
    if target.is_symlink():
        raise SystemExit(f"No se modificó el enlace existente: {target}")
    domain = f"gui/{os.getuid()}"
    loaded = (
        subprocess.run(
            ["launchctl", "print", f"{domain}/{LABEL}"], capture_output=True
        ).returncode
        == 0
    )
    if target.exists():
        with target.open("rb") as stream:
            previous = plistlib.load(stream)
            if previous != config and previous != agent_config(
                root, logs, ffmpeg_dir, legacy=True
            ):
                raise SystemExit(
                    f"Existe otra configuración; revísala antes de continuar: {target}"
                )
        if previous != config:
            backup = target.with_name(
                target.name + ".previous-" + datetime.now().strftime("%Y%m%d%H%M%S%f")
            )
            with backup.open("xb") as stream:
                plistlib.dump(previous, stream)
            if loaded:
                subprocess.run(
                    ["launchctl", "bootout", f"{domain}/{LABEL}"], check=True
                )
                loaded = False
            with tempfile.NamedTemporaryFile(
                dir=folder, prefix=".subtitle-studio-", delete=False
            ) as stream:
                plistlib.dump(config, stream)
                temporary = stream.name
            os.replace(temporary, target)
    else:
        with target.open("xb") as stream:
            plistlib.dump(config, stream)
    if not loaded:
        try:
            bootstrap(domain, target)
        except subprocess.CalledProcessError:
            if "backup" in locals():
                shutil.copyfile(backup, target)
                try:
                    bootstrap(domain, target)
                except subprocess.CalledProcessError:
                    pass
            raise
    print(f"Servicio {LABEL} instalado para arrancar bajo demanda en el puerto {port}.")
    print(f"Registros: {config['StandardErrorPath']}")


if __name__ == "__main__":
    main()
