"""Avisos por consola y, opcionalmente, a ntfy.sh. Nunca lanza y nunca bloquea.

`avisar()` SIEMPRE imprime: nube.py detecta esa salida para no duplicar líneas. El aviso
a ntfy se limita en frecuencia (si no, cada latido de 30 s te llenaría el móvil) y se
silencia en la sonda de arranque.
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
_MIN_SEGUNDOS = 8.0
_ULTIMO = {"t": 0.0}


def _cfg_ntfy() -> str:
    try:
        datos = json.loads((AQUI / "config.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return ""
    return str((datos or {}).get("ntfy") or "")


def avisar(mensaje: str, nivel: str = "info") -> None:
    texto = str(mensaje)
    print(texto, flush=True)

    if texto == "__sonda__" or nivel == "latido":
        return

    url = _cfg_ntfy()
    if not url:
        return

    ahora = time.time()
    if ahora - _ULTIMO["t"] < _MIN_SEGUNDOS:
        return
    _ULTIMO["t"] = ahora

    try:
        peticion = urllib.request.Request(url, data=texto.encode("utf-8"), method="POST")
        urllib.request.urlopen(peticion, timeout=6).read()
    except Exception:  # noqa: BLE001
        pass


def titulo(texto: str) -> None:
    avisar(f"=== {texto} ===")