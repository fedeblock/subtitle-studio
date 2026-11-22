"""Load dotenv as data (never execute it as shell), then start one gateway."""

import os
from pathlib import Path
from dotenv import load_dotenv
import uvicorn


def launchd_socket():
    import ctypes
    import socket

    libc = ctypes.CDLL(None, use_errno=True)
    fds = ctypes.POINTER(ctypes.c_int)()
    count = ctypes.c_size_t()
    libc.launch_activate_socket.argtypes = [
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_int)),
        ctypes.POINTER(ctypes.c_size_t),
    ]
    libc.launch_activate_socket.restype = ctypes.c_int
    status = libc.launch_activate_socket(
        b"Listeners", ctypes.byref(fds), ctypes.byref(count)
    )
    if status:
        raise OSError(status, "No se pudo activar el socket de launchd")
    try:
        if count.value != 1:
            raise RuntimeError(
                f"Se esperaba un socket de launchd, se recibieron {count.value}"
            )
        return socket.socket(fileno=fds[0])
    finally:
        libc.free.argtypes = [ctypes.c_void_p]
        libc.free(fds)


def main():
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env", override=False, interpolate=False)
    token = os.environ.get("MAC_TOKEN", "")
    if not token or token == "CHANGE_MAC_TOKEN":
        raise SystemExit("Configura MAC_TOKEN con un secreto aleatorio en .env")
    data = Path(os.environ.get("STUDIO_DATA_DIR", "data"))
    if not data.is_absolute():
        data = root / data
    os.environ["STUDIO_DATA"] = str(data.resolve())
    os.environ["STUDIO_TOKEN"] = token
    os.environ["STUDIO_TRANSLATION_MODEL"] = os.environ.get(
        "TRANSLATION_MODEL", "qwen3:14b-q8_0"
    )
    os.environ["STUDIO_ASR_MODEL"] = os.environ.get("ASR_MODEL", "Qwen/Qwen3-ASR-1.7B")
    os.environ["STUDIO_ALIGNER_MODEL"] = os.environ.get(
        "ALIGNER_MODEL", "Qwen/Qwen3-ForcedAligner-0.6B"
    )
    if os.environ.get("STUDIO_LAUNCHD_SOCKET") == "1":
        config = uvicorn.Config("server:app", workers=1)
        uvicorn.Server(config).run(sockets=[launchd_socket()])
    else:
        uvicorn.run(
            "server:app",
            host=os.environ.get("MAC_BIND_HOST", "0.0.0.0"),
            port=int(os.environ.get("MAC_PORT", "8765")),
            workers=1,
        )


if __name__ == "__main__":
    main()
