"""Revisa o rehace arena/config.json sin destruir lo tuyo.

  py reparar_config.py --revisar    avisa de claves que falten y las AÑADE (no toca las tuyas)
  py reparar_config.py --rehacer    reescribe config.json desde cero (guarda .bak)
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

import ajustes  # noqa: E402

CONFIG = AQUI / "config.json"
BAK = AQUI / "config.json.bak"


def _utf8() -> None:
    for flujo in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            flujo.reconfigure(encoding="utf-8", errors="replace")


def _escribir(datos: dict) -> None:
    with contextlib.suppress(OSError):
        CONFIG.write_text(
            json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


def revisar() -> int:
    crudo = ajustes.leer_crudo()
    faltan = [clave for clave in ajustes.DEFECTOS if clave not in crudo]
    if not faltan:
        print(f"[reparar_config] {CONFIG.name} está completo ({len(crudo)} claves)")
        return 0
    print(f"[reparar_config] faltan {len(faltan)} claves; las añado con sus valores por defecto:")
    for clave in faltan:
        print(f"  + {clave}")
    completo = ajustes.cargar()
    _escribir(completo)
    print(f"[reparar_config] {CONFIG.name} reparado")
    return 0


def rehacer() -> int:
    if CONFIG.is_file():
        BAK.write_text(CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"[reparar_config] copia de seguridad en {BAK.name}")
    _escribir(ajustes.cargar())
    print(f"[reparar_config] {CONFIG.name} reescrito desde los valores por defecto")
    return 0


def _main() -> int:
    _utf8()
    ap = argparse.ArgumentParser("reparar_config", description="Repara arena/config.json.")
    grupo = ap.add_mutually_exclusive_group()
    grupo.add_argument("--revisar", action="store_true", help="añade solo lo que falte")
    grupo.add_argument("--rehacer", action="store_true", help="reescribe desde cero (guarda .bak)")
    args = ap.parse_args()
    if args.rehacer:
        return rehacer()
    return revisar()


if __name__ == "__main__":
    sys.exit(_main())