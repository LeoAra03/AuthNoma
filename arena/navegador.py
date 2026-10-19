"""Localiza Brave con el puerto CDP abierto, o lo levanta. Devuelve el puerto; 0 si no.

Sin dependencias: urllib para sondear, subprocess para lanzar. Cubre Windows, macOS y
Linux. Si no hay Brave, `guia()` dice exactamente qué hacer. El resto del bot no necesita
saber cómo se arranca el navegador: solo pide un puerto.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
_PUERTO_DEFECTO = 9222

_RUTAS_WINDOWS = (
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
    os.path.expandvars(r"%PROGRAMFILES%\BraveSoftware\Brave-Browser\Application\brave.exe"),
)
_RUTAS_MAC = (
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    os.path.expanduser("~/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
)
_RUTAS_LINUX = (
    "/usr/bin/brave-browser",
    "/usr/bin/brave-browser-stable",
    "/usr/bin/brave",
    "/snap/bin/brave",
    "/opt/brave.com/brave/brave",
)


def _config() -> dict:
    try:
        datos = json.loads((AQUI / "config.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return datos if isinstance(datos, dict) else {}


def puerto_config() -> int:
    cdp = str(_config().get("cdp") or "")
    cola = cdp.rstrip("/").rsplit(":", 1)[-1]
    return int(cola) if cola.isdigit() else _PUERTO_DEFECTO


def _responde(puerto: int, tope: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{puerto}/json/version", timeout=tope
        ) as respuesta:
            return respuesta.status == 200
    except Exception:  # noqa: BLE001
        return False


def _candidatos() -> list[str]:
    sistema = platform.system().lower()
    if sistema == "windows":
        rutas = list(_RUTAS_WINDOWS)
        hallado = shutil.which("brave") or shutil.which("brave.exe")
    elif sistema == "darwin":
        rutas = list(_RUTAS_MAC)
        hallado = shutil.which("brave")
    else:
        rutas = list(_RUTAS_LINUX)
        hallado = shutil.which("brave-browser") or shutil.which("brave")
    if hallado:
        rutas.insert(0, hallado)
    vistos, limpias = set(), []
    for ruta in rutas:
        if ruta and ruta not in vistos and Path(ruta).is_file():
            vistos.add(ruta)
            limpias.append(ruta)
    return limpias


def _perfil() -> Path:
    """Carpeta de perfil propia: no ensucia tu perfil normal de Brave."""
    ruta = str(_config().get("perfil_brave") or "").strip()
    base = Path(ruta).expanduser() if ruta else (AQUI / ".brave-perfil")
    with contextlib.suppress(OSError):
        base.mkdir(parents=True, exist_ok=True)
    return base


def lanzar_brave(puerto: int | None = None) -> bool:
    """Abre Brave con depuración remota. True si el puerto acaba respondiendo."""
    puerto = puerto or puerto_config()
    if _responde(puerto):
        return True
    perfil = _perfil()
    for exe in _candidatos():
        argv = [
            exe,
            f"--remote-debugging-port={puerto}",
            f"--user-data-dir={perfil}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        try:
            opciones: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
            if platform.system().lower() == "windows":
                opciones["creationflags"] = 0x00000008 | 0x08000000  # DETACHED | NO_WINDOW
            subprocess.Popen(argv, **opciones)
        except Exception:  # noqa: BLE001
            continue
        for _ in range(30):
            if _responde(puerto):
                return True
            time.sleep(1)
    return _responde(puerto)


def esperar_cdp(tope: float = 90, lanzar: bool = True) -> int:
    """Puerto CDP listo, o 0. Si `lanzar`, levanta Brave y espera."""
    puerto = puerto_config()
    limite = time.time() + max(5.0, float(tope))
    intento_lanzar = bool(lanzar)
    while True:
        if _responde(puerto):
            return puerto
        if intento_lanzar:
            intento_lanzar = False
            lanzar_brave(puerto)
            continue
        if time.time() >= limite:
            return puerto if _responde(puerto) else 0
        time.sleep(1)


def guia() -> str:
    puerto = puerto_config()
    return (
        "No consigo hablar con Brave por CDP.\n"
        f"  1) Abre Brave con el puerto abierto:  brave --remote-debugging-port={puerto}\n"
        f"  2) Comprueba que http://127.0.0.1:{puerto}/json/version responde en el navegador.\n"
        "  3) Si usas otro puerto, cámbialo en arena/config.json (clave \"cdp\").\n"
        "  Windows: en un acceso directo a brave.exe añade el parámetro al final del destino."
    )


def _main() -> int:
    for flujo in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            flujo.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser("navegador", description="Espera (y si hace falta levanta) Brave con CDP.")
    ap.add_argument("--tope", type=float, default=90)
    ap.add_argument("--no-lanzar", action="store_true")
    args = ap.parse_args()
    puerto = esperar_cdp(args.tope, lanzar=not args.no_lanzar)
    if puerto:
        print(f"CDP listo en http://127.0.0.1:{puerto}")
        return 0
    print(guia())
    return 1


if __name__ == "__main__":
    sys.exit(_main())