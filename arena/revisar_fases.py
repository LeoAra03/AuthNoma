"""Preflight y estado del backlog. No envía nada a arena.ai.

Se corre ANTES de abrir Brave: valida config.json (y lo regenera si falta), el brief,
las fases y playwright; si Brave ya está abierto, comprueba el puerto de depuración.
Después muestra el estado del archivo de fases que el bot va a usar.

  * --repo acepta URL de GitHub, owner/repo o carpeta local.
  * El archivo de fases se elige como lo hace el bot (proyecto/ y arena/) y puede ser
    tareas.txt (una línea = una fase) o fases.jsonl.
  * Comprueba el cierre de fases: sin GITHUB_TOKEN los PR no se fusionan solos y las
    ramas `autonoma/*` se acumulan. Eso es un aviso, no un fallo.

Salida: 0 = listo para arrancar (los avisos no impiden); 1 = hay algo que corregir.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
PROYECTO = AQUI.parent / "proyecto"

from fases import cargar, elegir_fases  # noqa: E402
from repo_url import resolver as resolver_repo  # noqa: E402

_CLAVES_CONFIG = ("cdp", "url_arena", "selector_compositor", "idle_segundos", "timeout_fase_segundos")
_CLAVES_GITHUB = ("prefijo_rama", "base", "metodo_merge")
_CLAVES_FASE = ("id", "titulo", "objetivo")
_ESTADOS = {"pendiente", "enviada", "hecha", "bloqueada"}
_METODOS_MERGE = {"squash", "merge", "rebase"}

fallos: list[str] = []
avisos: list[str] = []


def mal(msg: str) -> None:
    fallos.append(msg)


def ojo(msg: str) -> None:
    avisos.append(msg)


def _utf8() -> None:
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def _regenerar_config() -> None:
    script = AQUI / "reparar_config.py"
    if script.is_file():
        subprocess.run([sys.executable, str(script)], check=False)


def _leer_config() -> dict:
    ruta = AQUI / "config.json"
    if not ruta.is_file():
        ojo("no hay config.json: lo genero con reparar_config.py")
        _regenerar_config()
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        ojo(f"config.json ilegible ({exc}): lo regenero")
        _regenerar_config()
        try:
            return json.loads(ruta.read_text(encoding="utf-8"))
        except Exception as exc2:  # noqa: BLE001
            mal(f"config.json sigue ilegible tras regenerarlo: {exc2}")
            return {}


def revisar_config() -> dict:
    datos = _leer_config()
    for clave in _CLAVES_CONFIG:
        if not datos.get(clave):
            mal(f"config.json sin `{clave}`")
    if not (datos.get("comandos_verificacion") or []):
        ojo("sin comandos_verificacion: las fases se darán por hechas sin verificar")
    if not datos.get("ntfy"):
        ojo("sin ntfy: no habrá avisos al móvil (no es un problema)")
    return datos


def revisar_brief(ruta: Path) -> None:
    if not ruta.is_file():
        mal(f"falta el brief: {ruta}")
    elif not ruta.read_text(encoding="utf-8", errors="replace").strip():
        mal(f"el brief está vacío: {ruta}")


def _leer_fases(ruta: Path) -> list[dict]:
    """Lee el archivo de fases: .jsonl/.json o lista de texto (tareas.txt)."""
    if not ruta.is_file():
        mal(f"falta el archivo de fases: {ruta}")
        return []
    if ruta.suffix.lower() != ".jsonl":
        try:
            return cargar(ruta)
        except Exception as exc:  # noqa: BLE001
            mal(f"{ruta.name} ilegible: {exc}")
            return []
    fases: list[dict] = []
    for numero, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
        if not linea.strip():
            continue
        try:
            fase = json.loads(linea)
        except json.JSONDecodeError as exc:
            mal(f"{ruta.name}:{numero} no es JSON válido ({exc})")
            continue
        if isinstance(fase, dict):
            fases.append(fase)
    return fases


def revisar_fases(fases: list[dict], nombre: str) -> None:
    vistas: set[str] = set()
    for numero, fase in enumerate(fases, 1):
        for clave in _CLAVES_FASE:
            if not str(fase.get(clave) or "").strip():
                mal(f"{nombre}:{numero} sin `{clave}`")
        if fase.get("id") in vistas:
            mal(f"{nombre}:{numero} id duplicado: {fase.get('id')}")
        vistas.add(fase.get("id"))
        if (fase.get("estado") or "pendiente") not in _ESTADOS:
            mal(f"{nombre}:{numero} estado desconocido: {fase.get('estado')}")
        if "archivos" in fase and not isinstance(fase["archivos"], list):
            mal(f"{nombre}:{numero} `archivos` debe ser lista")


def revisar_cdp(url: str) -> None:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/json/list", timeout=4) as respuesta:
            datos = json.loads(respuesta.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001
        ojo(f"CDP no responde en {url} ({type(exc).__name__}): arrancar.bat abrirá Brave con el puerto")
        return
    urls = [str(p.get("url", "")) for p in datos if isinstance(p, dict) and p.get("type") == "page"]
    if any("arena" in u.lower() for u in urls):
        print("  CDP: enganchado, y ya hay una pestaña de arena.ai abierta.")
    else:
        ojo("CDP responde pero no hay pestaña de arena.ai: el bot abrirá una (inicia sesión ahí)")


def revisar_github(config: dict) -> None:
    """Cierre de fases: una fase = una rama = un PR, y el PR se cierra al terminar.

    Sin token, `nube.py` sigue funcionando pero no puede fusionar ni borrar ramas, así
    que los PR se acumulan y `main` se queda atrás. Todo esto son avisos: el preflight
    no debe impedir arrancar por algo que se arregla en un archivo de texto.
    """
    bloque = config.get("github")
    if not isinstance(bloque, dict) or not bloque:
        ojo("config.json sin bloque `github`: corre `py arena/reparar_config.py` para tener el cierre de PR")
        return
    if not bloque.get("activo", True):
        ojo("github.activo = false: nada se fusionará ni se borrará automáticamente")
        return

    for clave in _CLAVES_GITHUB:
        if not bloque.get(clave):
            ojo(f"github.{clave} vacío: se usará el valor por defecto")
    metodo = str(bloque.get("metodo_merge") or "squash")
    if metodo not in _METODOS_MERGE:
        mal(f"github.metodo_merge desconocido: {metodo} (usa squash, merge o rebase)")
    prefijo = str(bloque.get("prefijo_rama") or "autonoma/")
    if prefijo == str(bloque.get("base") or "main"):
        mal(f"github.prefijo_rama ({prefijo}) no puede ser igual que la base")

    try:
        import ramas  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        ojo(f"no pude cargar ramas.py ({type(exc).__name__}): el cierre de PR quedará a mano")
        return

    if not ramas.hay_token():
        ojo(
            "sin GITHUB_TOKEN: crea arena/credenciales.txt con `GITHUB_TOKEN=ghp_...` "
            "(fine-grained, contents:write y pull_requests:write) para que los PR se cierren solos"
        )
        return

    slug = ramas.repositorio()
    if not slug:
        ojo("con token pero sin repositorio: rellena arena/REPO.txt o usa --repo")
        return
    print(f"  github: token presente, repositorio {slug}")

    vivas = ramas.listar_ramas(slug, ramas.prefijo())
    if not vivas:
        print(f"  github: ninguna rama `{ramas.prefijo()}*` viva; main limpio")
        return
    con_pr = 0
    for rama in vivas:
        if ramas.pr_de_rama(slug, rama):
            con_pr += 1
    ojo(
        f"{len(vivas)} rama(s) `{ramas.prefijo()}*` vivas ({con_pr} con PR abierto): "
        f"`py arena/ramas.py --barrer` las fusiona y borra, o deja que nube.py lo haga al arrancar"
    )


def mostrar_estado(fases: list[dict], resumen: bool = False) -> None:
    if not fases:
        ojo("no hay fases que ejecutar")
        return
    pendientes = [f for f in fases if (f.get("estado") or "pendiente") not in {"hecha", "bloqueada"}]
    print(f"  fases: {len(fases)} · hechas: {len(fases) - len(pendientes)} · por hacer: {len(pendientes)}")
    if pendientes:
        print(f"  siguiente: {pendientes[0].get('id')} — {pendientes[0].get('titulo', '')}")
    if resumen:
        return
    for fase in fases:
        estado = (fase.get("estado") or "pendiente").upper()
        marca = {"HECHA": "[x]", "ENVIADA": "[>]", "BLOQUEADA": "[!]"}.get(estado, "[ ]")
        print(f"    {marca} {fase.get('id')} {fase.get('titulo', '')} <{estado}>")


def main() -> int:
    _utf8()
    ap = argparse.ArgumentParser(description="Preflight y estado antes de arrancar el bot.")
    ap.add_argument("--repo", default="", help="URL de GitHub, owner/repo o carpeta local")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--brief", default=str(PROYECTO / "brief.md"))
    ap.add_argument("--fases", default="", help="archivo de fases (por defecto, el que elija el bot)")
    ap.add_argument("--resumen", action="store_true", help="no listar las 2700 fases una por una")
    ap.add_argument("--github", action=argparse.BooleanOptionalAction, default=True,
                    help="revisar el cierre de fases por API (--no-github para saltarlo)")
    args = ap.parse_args()

    print("Preflight de Autonoma (no envía nada a arena.ai)")
    config = revisar_config()
    revisar_brief(Path(args.brief).expanduser())
    ruta_fases = Path(args.fases).expanduser() if args.fases else elegir_fases(PROYECTO)
    print(f"  fases: {ruta_fases}")
    fases = _leer_fases(ruta_fases)
    revisar_fases(fases, ruta_fases.name)
    if config.get("cdp"):
        revisar_cdp(str(config["cdp"]))
    if args.github:
        revisar_github(config)

    try:
        import playwright  # noqa: F401

        print("  playwright: instalado.")
    except ImportError:
        mal("falta playwright: pip install -r arena/requirements.txt")

    if args.repo:
        try:
            destino = resolver_repo(args.repo, args.branch, quiet=True)
        except SystemExit as exc:
            mal(str(exc))
        else:
            if destino is None:
                # Modo nube: no hay clon, el remoto se anota en arena/REPO.txt.
                print(f"  repo: {args.repo} (modo nube, sin clon)")
            else:
                print(f"  repo: {destino.resolve()} (ok)")

    print("  estado del backlog:")
    mostrar_estado(fases, resumen=args.resumen)
    for mensaje in avisos:
        print(f"  [aviso] {mensaje}")
    for mensaje in fallos:
        print(f"  [FALLO] {mensaje}")
    if fallos:
        print(f"\n{len(fallos)} problema(s): corrígelos y vuelve a intentarlo.")
        return 1
    print("\nTodo en su sitio. Arrancando.")
    return 0


if __name__ == "__main__":
    sys.exit(main())