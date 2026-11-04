"""Authenticated local gateway requests; media is streamed without a disk copy."""

import os
import requests
from fastapi import HTTPException

MAC_URL = os.environ.get("MAC_URL", "http://host.docker.internal:8765")
TOKEN = os.environ.get("MAC_TOKEN", "")


def native_request(method, path, **kwargs):
    headers = kwargs.pop("headers", {})
    headers["X-Worker-Token"] = TOKEN
    try:
        response = requests.request(
            method,
            MAC_URL + path,
            headers=headers,
            timeout=kwargs.pop("timeout", (5, 60)),
            **kwargs,
        )
    except requests.RequestException as exc:
        raise HTTPException(
            503, "Gateway nativo no disponible. Abre scripts/start-mac.sh."
        ) from exc
    if not response.ok:
        try:
            detail = response.json().get("detail", "Error del gateway nativo")
        except ValueError:
            detail = "Error del gateway nativo"
        code = response.status_code
        response.close()
        raise HTTPException(code, detail)
    return response
