"""Ramas y PR de cada fase: cierra el ciclo sin clonar el repositorio.

En modo nube el trabajo lo hace arena.ai sobre GitHub, no esta maquina. La regla es
una sesion = una rama = un PR: se empuja en el mismo PR mientras la sesion vive, y al
cerrarla se fusiona, se borra la rama y se archiva el chat. Asi `main` esta siempre al
dia y no quedan PR abiertos acumulandose.

OJO: arena.ai nombra las ramas `arena/<uuid>-<repo>`, no con nuestro prefijo. Por eso
`barrer()` recorre TODAS las ramas menos las protegidas, en vez de filtrar por prefijo.

  py ramas.py --estado                 lista ramas y PR abiertos
  py ramas.py --barrer                 fusiona y borra todo lo que quedo abierto
  py ramas.py --fusionar <rama>        fusiona y borra una rama concreta
  py ramas.py --cerrar <url|numero>    cierra un PR sin fusionar

Token: `GITHUB_TOKEN` o `GH_TOKEN` en el entorno, o una linea `GITHUB_TOKEN=...` en
`credenciales.txt`. Sin token se intenta por git local; sin nada, se avisa y se sigue.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
API = "https://api.github.com"
REPO_TXT = AQUI / "REPO.txt"
CREDENCIALES = ("credenciales.txt", ".env")
_PROTEGIDAS_POR_DEFECTO = ["main", "master", "develop", "dev", "gh-pages", "staging"]


def _utf8() -> None:
    for flujo in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            flujo.reconfigure(encoding="utf-8", errors="replace")


# ------------------------------------------------------------------ configuracion
def _cfg() -> dict:
    try:
        datos = json.loads((AQUI / "config.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return datos.get("github") or {}


def activo() -> bool:
    return bool(_cfg().get("activo", True))


def prefijo() -> str:
    return str(_cfg().get("prefijo_rama") or "autonoma/")


def base() -> str:
    return str(_cfg().get("base") or "main")


def metodo_merge() -> str:
    return str(_cfg().get("metodo_merge") or "squash")


def borrar_rama() -> bool:
    return bool(_cfg().get("borrar_rama", True))


def crear_pr_si_falta() -> bool:
    return bool(_cfg().get("crear_pr_si_falta", True))


def protegidas() -> list[str]:
    try:
        datos = json.loads((AQUI / "config.json").read_text(encoding="utf-8"))
        lista = datos.get("ramas_protegidas") or []
    except Exception:  # noqa: BLE001
        lista = []
    nombres = [str(n).strip() for n in lista if str(n).strip()]
    return nombres or list(_PROTEGIDAS_POR_DEFECTO)


def token() -> str:
    for nombre in ("GITHUB_TOKEN", "GH_TOKEN"):
        valor = (os.environ.get(nombre) or "").strip()
        if valor:
            return valor
    for carpeta in (AQUI, AQUI.parent):
        for archivo in CREDENCIALES:
            ruta = carpeta / archivo
            if not ruta.is_file():
                continue
            for linea in ruta.read_text(encoding="utf-8", errors="replace").splitlines():
                limpia = linea.strip()
                if not limpia or limpia.startswith(("#", ";", "//")):
                    continue
                clave, _, valor = limpia.partition("=")
                if clave.strip().upper() in {"GITHUB_TOKEN", "GH_TOKEN"} and valor.strip():
                    return valor.strip().strip("\"'")
    return ""


def hay_token() -> bool:
    return bool(token())


def repositorio(explicito: str = "") -> str:
    """owner/repo desde el argumento, el entorno o REPO.txt."""
    valor = (explicito or os.environ.get("AUTONOMA_REPO") or "").strip()
    if not valor and REPO_TXT.is_file():
        lineas = REPO_TXT.read_text(encoding="utf-8", errors="replace").splitlines()
        valor = lineas[0].strip() if lineas else ""
    valor = valor.strip().strip('"')
    valor = valor.replace("https://github.com/", "").replace("git@github.com:", "")
    valor = valor[:-4] if valor.endswith(".git") else valor
    valor = valor.strip("/")
    return valor if valor.count("/") == 1 else ""


# ----------------------------------------------------------------------- peticion
def _peticion(metodo: str, ruta: str, cuerpo: object = None, timeout: int = 30):
    url = ruta if ruta.startswith("http") else API + ruta
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    cabeceras = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "autonoma",
    }
    if datos is not None:
        cabeceras["Content-Type"] = "application/json"
    clave = token()
    if clave:
        cabeceras["Authorization"] = f"Bearer {clave}"
    peticion = urllib.request.Request(url, data=datos, headers=cabeceras, method=metodo)
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
            crudo = respuesta.read().decode("utf-8", "replace")
            return respuesta.status, (json.loads(crudo) if crudo.strip() else {})
    except urllib.error.HTTPError as exc:
        crudo = exc.read().decode("utf-8", "replace")
        with contextlib.suppress(Exception):
            crudo = json.loads(crudo)
        return exc.code, crudo
    except Exception as exc:  # noqa: BLE001
        return 0, f"{type(exc).__name__}: {exc}"


def _detalle(datos: object) -> str:
    if isinstance(datos, dict):
        return str(datos.get("message") or datos)
    return str(datos)


# ------------------------------------------------------------------------- ramas
def listar_ramas(slug: str, con_prefijo: str | None = None) -> list[str]:
    nombres: list[str] = []
    pagina = 1
    while pagina <= 6:
        codigo, datos = _peticion("GET", f"/repos/{slug}/branches?per_page=100&page={pagina}")
        if codigo != 200 or not isinstance(datos, list) or not datos:
            break
        for rama in datos:
            if isinstance(rama, dict) and rama.get("name"):
                nombres.append(str(rama["name"]))
        if len(datos) < 100:
            break
        pagina += 1
    nombres.sort()
    if con_prefijo:
        nombres = [n for n in nombres if n.startswith(con_prefijo)]
    return nombres


def ramas_de_trabajo(slug: str) -> list[str]:
    """Todas las ramas que no son protegidas: lo que arena.ai haya dejado vivo."""
    protegidas_ = set(protegidas())
    return [r for r in listar_ramas(slug) if r not in protegidas_]


def existe_rama(slug: str, rama: str) -> bool:
    if not slug or not rama:
        return False
    codigo, _ = _peticion("GET", f"/repos/{slug}/branches/{urllib.parse.quote(rama, safe='')}")
    return codigo == 200


def foto(slug: str) -> set[str]:
    """Instantanea de ramas ANTES de enviar, para detectar la que cree el agente."""
    if not slug or not hay_token():
        return set()
    return set(listar_ramas(slug))


# ---------------------------------------------------------------------------- PR
def pr_de_rama(slug: str, rama: str) -> dict | None:
    dueno = slug.split("/")[0]
    consulta = urllib.parse.urlencode({"state": "all", "head": f"{dueno}:{rama}"})
    codigo, datos = _peticion("GET", f"/repos/{slug}/pulls?{consulta}")
    if codigo == 200 and isinstance(datos, list) and datos:
        return datos[0]
    return None


def pr_abierto_de_rama(slug: str, rama: str) -> dict | None:
    pr = pr_de_rama(slug, rama)
    return pr if pr and pr.get("state") == "open" else None


def pr_por_url(slug: str, url: str) -> dict | None:
    numero = str(url).rstrip("/").split("/")[-1]
    if not numero.isdigit():
        return None
    codigo, datos = _peticion("GET", f"/repos/{slug}/pulls/{numero}")
    return datos if codigo == 200 and isinstance(datos, dict) else None


def asegurar_pr(slug: str, rama: str, base_: str | None = None, titulo: str = "") -> dict | None:
    """Devuelve el PR abierto de la rama, creandolo si el agente no lo hizo."""
    base_ = base_ or base()
    existente = pr_abierto_de_rama(slug, rama)
    if existente:
        return existente
    if not crear_pr_si_falta():
        return None
    cuerpo = (
        f"Rama `{rama}` generada por Autonoma en modo nube.\n\n"
        f"Se fusiona y se borra al cerrar la sesion de arena.ai que la creo."
    )
    codigo, datos = _peticion(
        "POST",
        f"/repos/{slug}/pulls",
        {"title": titulo or f"autonoma: {rama}", "head": rama, "base": base_, "body": cuerpo},
    )
    if codigo in (200, 201) and isinstance(datos, dict):
        return datos
    return None


def cerrar_pr(slug: str, numero: int | str) -> bool:
    codigo, _ = _peticion("PATCH", f"/repos/{slug}/pulls/{numero}", {"state": "closed"})
    return codigo in (200, 201)


def borrar_ref(slug: str, rama: str) -> bool:
    ruta = f"/repos/{slug}/git/refs/heads/{urllib.parse.quote(rama, safe='')}"
    codigo, _ = _peticion("DELETE", ruta)
    return codigo in (200, 204)


# ------------------------------------------------------------------------ fusion
def fusionar(
    slug: str,
    rama: str,
    base_: str | None = None,
    metodo: str | None = None,
    borrar: bool | None = None,
) -> tuple[bool, str]:
    """Fusiona la rama en la base y la borra. Devuelve (ok, detalle)."""
    base_ = base_ or base()
    metodo = metodo or metodo_merge()
    borrar = borrar_rama() if borrar is None else borrar

    if not rama:
        return True, "sin rama"
    if rama == base_:
        return True, "es la base"

    if hay_token():
        ok, detalle = _fusionar_api(slug, rama, base_, metodo, borrar)
    else:
        ok, detalle = _fusionar_git(slug, rama, base_, borrar)

    if ok and borrar:
        if existe_rama(slug, rama):
            return False, f"{detalle}; la rama {rama} SIGUE VIVA"
        return True, f"{detalle}; rama borrada"
    return ok, detalle


def _fusionar_api(slug: str, rama: str, base_: str, metodo: str, borrar: bool) -> tuple[bool, str]:
    pr = pr_abierto_de_rama(slug, rama)
    if pr is None:
        cerrado = pr_de_rama(slug, rama)
        if cerrado and cerrado.get("merged_at"):
            if borrar:
                borrar_ref(slug, rama)
            return True, f"PR #{cerrado['number']} ya estaba fusionado"
        pr = asegurar_pr(slug, rama, base_)
    if pr:
        numero = pr.get("number")
        codigo, datos = _peticion(
            "PUT",
            f"/repos/{slug}/pulls/{numero}/merge",
            {"merge_method": metodo, "commit_title": f"autonoma: {rama} ({metodo})"},
        )
        if codigo in (200, 201):
            if borrar:
                borrar_ref(slug, rama)
            return True, f"PR #{numero} fusionado ({metodo})"
        if codigo == 409:
            cerrar_pr(slug, numero)
            if borrar:
                borrar_ref(slug, rama)
            return True, f"PR #{numero} sin cambios: cerrado"
        return False, f"PR #{numero} no fusionable: {_detalle(datos)}"

    codigo, datos = _peticion(
        "POST",
        f"/repos/{slug}/merges",
        {"base": base_, "head": rama, "commit_message": f"autonoma: fusionar {rama}"},
    )
    if codigo in (200, 201, 204):
        if borrar:
            borrar_ref(slug, rama)
        return True, "fusion directa"
    if codigo == 409:
        return False, "conflicto: hay que resolverlo a mano"
    return False, f"no se pudo fusionar: {_detalle(datos)}"


def _git(cwd: Path, *args: str) -> tuple[int, str]:
    proceso = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return proceso.returncode, ((proceso.stdout or "") + (proceso.stderr or "")).strip()


def _clon(slug: str) -> Path | None:
    nombre = slug.split("/")[-1]
    base_cfg = ""
    with contextlib.suppress(Exception):
        datos = json.loads((AQUI / "config.json").read_text(encoding="utf-8"))
        base_cfg = str((datos.get("agente") or {}).get("carpeta_repos") or "")
    candidatos = []
    if base_cfg:
        candidatos.append(Path(base_cfg).expanduser() / nombre)
    candidatos.append(Path.home() / "autonoma-repos" / nombre)
    for candidato in candidatos:
        if (candidato / ".git").is_dir():
            return candidato
    return None


def _fusionar_git(slug: str, rama: str, base_: str, borrar: bool) -> tuple[bool, str]:
    if not shutil.which("git"):
        return False, "sin token y sin git en el PATH"
    clon = _clon(slug)
    if clon is None:
        return False, "sin token y sin clon local"
    for paso in (
        ["fetch", "--prune", "origin"],
        ["checkout", base_],
        ["pull", "--ff-only", "origin", base_],
        ["merge", "--no-edit", f"origin/{rama}"],
        ["push", "origin", base_],
    ):
        codigo, salida = _git(clon, *paso)
        if codigo:
            cola = salida.splitlines()[-1] if salida else str(codigo)
            return False, f"git {' '.join(paso)}: {cola}"
    if borrar:
        _git(clon, "push", "origin", "--delete", rama)
    return True, "fusion por git local"


def barrer(slug: str, base_: str | None = None, borrar: bool | None = None) -> dict:
    """Fusiona y borra TODAS las ramas de trabajo que quedaran vivas.

    No filtra por prefijo: arena.ai nombra las ramas `arena/<uuid>-<repo>`, asi que
    cualquier rama que no este en `ramas_protegidas` se considera trabajo nuestro.
    """
    base_ = base_ or base()
    informe: dict = {"fusionadas": 0, "fallidas": [], "revisadas": 0}
    for rama in ramas_de_trabajo(slug):
        informe["revisadas"] += 1
        ok, detalle = fusionar(slug, rama, base_, borrar=borrar)
        if ok:
            informe["fusionadas"] += 1
        else:
            informe["fallidas"].append(f"{rama}: {detalle}")
    return informe


# ---------------------------------------------------------------------------- CLI
def _main() -> int:
    _utf8()
    ap = argparse.ArgumentParser("ramas", description="Ramas y PR de Autonoma (cierre de sesiones).")
    ap.add_argument("--repo", default="", help="owner/repo (por defecto REPO.txt)")
    ap.add_argument("--estado", action="store_true", help="lista ramas y PR abiertos")
    ap.add_argument("--barrer", action="store_true", help="fusiona y borra todo lo pendiente")
    ap.add_argument("--fusionar", default="", help="rama concreta a fusionar y borrar")
    ap.add_argument("--cerrar", default="", help="PR (url o numero) a cerrar sin fusionar")
    args = ap.parse_args()

    slug = repositorio(args.repo)
    if not slug:
        print("[ramas] falta el repositorio: usa --repo owner/repo o crea REPO.txt")
        return 2
    if not hay_token():
        print("[ramas] aviso: sin GITHUB_TOKEN; el barrido usara git local si hay clon")

    if args.estado or not (args.barrer or args.fusionar or args.cerrar):
        print(f"repositorio : {slug}")
        print(f"base        : {base()}   protegidas: {', '.join(protegidas())}")
        print(f"token       : {'si' if hay_token() else 'no'}")
        ramas = ramas_de_trabajo(slug)
        if not ramas:
            print("  (ninguna rama de trabajo viva)")
        for rama in ramas:
            pr = pr_de_rama(slug, rama)
            estado = "sin PR"
            if pr:
                estado = f"PR #{pr['number']} {pr.get('state')}"
            print(f"  {rama}  ->  {estado}")
        return 0

    if args.barrer:
        informe = barrer(slug)
        print(f"barrido: {informe['fusionadas']}/{informe['revisadas']} fusionadas y borradas")
        for linea in informe["fallidas"]:
            print(f"  [!] {linea}")
    if args.fusionar:
        ok, detalle = fusionar(slug, args.fusionar)
        print(f"{args.fusionar}: {'ok' if ok else 'FALLO'} ({detalle})")
    if args.cerrar:
        numero = args.cerrar.rstrip("/").split("/")[-1]
        print(f"PR {numero}: {'cerrado' if cerrar_pr(slug, numero) else 'no se pudo cerrar'}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())