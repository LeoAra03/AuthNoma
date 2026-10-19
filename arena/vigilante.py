"""Mantiene el bucle vivo: avisa si CDP se cayó y relanza el orquestador si murió.

Corrección: se lanza `orquestador.py` por ruta ABSOLUTA (antes era relativa y fallaba
según desde dónde lo ejecutaras) pero sin cambiar el cwd, para que `--repo` y `--brief`
sigan resolviéndose contra donde estás.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from notificar import avisar  # noqa: E402

AQUI = Path(__file__).resolve().parent
PUERTO = 9222
_REINTENTO_SEGUNDOS = 15


def cdp_vivo() -> bool:
    s = socket.socket()
    s.settimeout(2)
    try:
        s.connect(("127.0.0.1", PUERTO))
        return True
    except OSError:
        return False
    finally:
        s.close()


def main() -> int:
    args = sys.argv[1:]
    while True:
        if not cdp_vivo():
            avisar(f"CDP caído: Brave no responde en {PUERTO}. Relánzalo con --remote-debugging-port={PUERTO}.")
        proceso = subprocess.run([sys.executable, str(AQUI / "orquestador.py"), *args])
        if proceso.returncode == 0:
            return 0
        if proceso.returncode == 2:
            # Login/captcha o arranque fallido: relanzar en bucle no arregla nada.
            avisar("El orquestador pidió intervención humana (código 2). Paro.")
            return 2
        avisar(f"El orquestador terminó con {proceso.returncode}; relanzo en {_REINTENTO_SEGUNDOS} s.")
        time.sleep(_REINTENTO_SEGUNDOS)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nParado a mano.")
        sys.exit(0)