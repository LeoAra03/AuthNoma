"""Orquestador: manda fases a arena.ai, recoge los archivos y verifica en el repo.

Pensado para dejarlo solo: lee una tarea por línea de proyecto/tareas.txt, la manda,
espera la respuesta, aplica los archivos, corre la verificación y commitea. Si algo
falla reintenta; si se atasca, marca la fase como bloqueada y SIGUE con la siguiente.

  * Acepta --repo como URL de GitHub, owner/repo o carpeta (resuelve el clon local).
  * Cierra el modal de fin de turno de arena.ai.
  * Si la respuesta no trae bloques ```path=, se lo vuelve a pedir.
  * Cada `nueva_charla_cada` fases recarga la conversación (contexto limpio).
  * Todo queda en arena/registro.log; `arena/STOP` lo para limpio.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

from contrato import aplicar, parsear  # noqa: E402
from fases import Backlog, elegir_fases  # noqa: E402
from notificar import avisar  # noqa: E402
from puente import Puente  # noqa: E402
from repo_url import resolver as resolver_repo  # noqa: E402

CFG = json.loads((AQUI / "config.json").read_text(encoding="utf-8"))
PROYECTO = AQUI.parent / "proyecto"

ACUSE = "Responde sólo: @@FASE_OK@@"

REINTENTO_FORMATO = (
    "No vi ningún bloque de archivo en tu respuesta. Devuelve AHORA el contenido COMPLETO "
    "de cada archivo, uno por bloque, exactamente así:\n\n"
    "```python path=ruta/del/archivo.py\n<contenido completo>\n```\n\n"
    "La ruta va en la misma línea que las tres comillas, detrás de `path=`, relativa a la "
    "raíz del proyecto. Nada de diffs ni de resúmenes. Termina con @@FASE_OK@@ en su propia línea."
)


def _utf8() -> None:
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
           