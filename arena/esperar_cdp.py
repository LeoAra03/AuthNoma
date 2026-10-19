"""Espera a que Brave tenga CDP abierto (y lo levanta si hace falta). Código 0 = listo.

Lo llama arrancar-nube.bat antes de nada. Nada de `netstat`: se comprueba de verdad si el
puerto responde, y si no, se abre Brave y se espera.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

import navegador  # noqa: E402


def _main() -> int:
    for flujo in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            flujo.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser("esperar_cdp", description="Espera a Brave/CDP.")
    ap.add_argument("--tope", type=float, default=90, help="segundos máximos de espera")
    ap.add_argument("--no-lanzar", action="store_true", help="no intentar abrir Brave")
    args = ap.parse_args()

    puerto = navegador.esperar_cdp(args.tope, lanzar=not args.no_lanzar)
    if puerto:
        print(f"[esperar_cdp] listo en http://127.0.0.1:{puerto}")
        return 0
    print(f"[esperar_cdp] no hay CDP tras {int(args.tope)}s")
    print(navegador.guia())
    return 1


if __name__ == "__main__":
    sys.exit(_main())