"""Ajusta y prueba la selección de repositorio/rama en arena.ai (Agent Mode).

    py arena\\agente.py --ver
        Lista los botones y campos visibles. Busca los que digan GitHub / repositorio /
        rama y cópialos a config.json -> agente.pasos.

    py arena\\agente.py --repo https://github.com/LeoAra03/Fire-ash-modifier --branch main --probar
        Acepta URL, owner/repo o carpeta: la normaliza a `owner/repo`, la deja en
        config.json y ejecuta los pasos contándote qué encontró y qué no.

Necesita Brave abierto con --remote-debugging-port=9222 y sesión iniciada en arena.ai.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

from puente import Puente  # noqa: E402
from repo_url import partir  # noqa: E402

CFG = json.loads((AQUI / "config.json").read_text(encoding="utf-8"))


def _utf8() -> None:
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    _utf8()
    ap = argparse.ArgumentParser(description="Ver/ajustar la selección de repo y rama en Agent Mode.")
    ap.add_argument("--ver", action="store_true", help="lista botones y campos visibles")
    ap.add_argument("--probar", action="store_true", help="ejecuta config.json -> agente.pasos")
    ap.add_argument("--repo", default="", help="URL, owner/repo o carpeta del repositorio")
    ap.add_argument("--branch", default="", help="rama a elegir")
    args = ap.parse_args()

    ag = CFG.setdefault("agente", {})
    if args.repo:
        slug, _ = partir(args.repo)
        ag["repositorio"] = slug or args.repo
    if args.branch:
        ag["branch"] = args.branch
    ag["activo"] = True
    print(f"repositorio: {ag.get('repositorio') or '(vacío)'} · rama: {ag.get('branch') or '(vacío)'}")

    with Puente() as puente:
        if args.ver or not args.probar:
            print("\nControles visibles (etiqueta | texto):")
            for item in puente.listar_controles():
                print(f"  {item['tag']:>10} | {item['txt']}")
            print(
                "\nAcciones disponibles en agente.pasos:\n"
                '  {"accion":"clic_texto","texto":"Select a repository"}   {"accion":"clic_selector","selector":"..."}\n'
                '  {"accion":"escribir","texto":"{{repo_busqueda}}"}        {"accion":"tecla","tecla":"Escape"}\n'
                '  {"accion":"esperar","segundos":1}                        {"accion":"esperar_texto","texto":"..."}\n'
                "Huecos: {{repositorio}} (owner/repo), {{repo_busqueda}} (solo el nombre), {{branch}}.\n"
                "Las claves son las de config.json -> agente.pasos."
            )

        if args.probar:
            print("\nEjecutando agente.pasos:")
            for linea in puente.preparar_agente():
                print(f"  {linea}")
            print("\nSi no ha quedado elegido, ajusta los pasos con lo que viste en --ver.")
    return 0


if __name__ == "__main__":
    sys.exit(main())