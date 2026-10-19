"""Anota owner/repo y rama en arena/REPO.txt.

En modo nube NO clona nada: solo deja anotado el remoto para que nube.py lo lea.
En modo local, además mantiene un clon al día y devuelve su carpeta.

  py repo_url.py --url https://github.com/owner/repo --branch main --modo nube
  py repo_url.py --url owner/repo --branch main
"""

from __future__ import annotations

import argparse
import contextlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
REPO_TXT = AQUI / "REPO.txt"
RE_REPO = re.compile(r"^[\w.\-]+/[\w.\-]+$")


def _utf8() -> None:
    for flujo in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            flujo.reconfigure(encoding="utf-8", errors="replace")


def normalizar(valor: str) -> str:
    v = (valor or "").strip().strip("\"'").strip()
    for prefijo in ("https://github.com/", "http://github.com/", "git@github.com:",
                    "ssh://git@github.com/"):
        v = v.replace(prefijo, "")
    if v.endswith(".git"):
        v = v[:-4]
    v = v.strip("/").strip()
    return v if RE_REPO.match(v) else ""


def anotar(slug: str, branch: str) -> None:
    REPO_TXT.write_text(f"{slug}\n{branch}\n{branch}\n", encoding="utf-8")


def _git(cwd: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).strip()


def _clonar(slug: str, branch: str, quiet: bool) -> Path:
    if not shutil.which("git"):
        raise SystemExit("no encuentro git en el PATH")
    destino = AQUI.parent / "proyecto" / slug.split("/")[-1]
    if (destino / ".git").is_dir():
        codigo, salida = _git(destino, "fetch", "--prune", "origin")
        if codigo and not quiet:
            print(f"[repo_url] fetch: {salida.splitlines()[-1:]}")
        _git(destino, "checkout", branch)
        _git(destino, "pull", "--ff-only", "origin", branch)
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    codigo, salida = _git(
        destino.parent, "clone", "--branch", branch,
        f"https://github.com/{slug}.git", destino.name,
    )
    if codigo:
        raise SystemExit(f"no pude clonar {slug}: {salida.splitlines()[-1:]}")
    return destino


def resolver(valor: str, branch: str = "main", quiet: bool = False, modo: str = "local") -> Path:
    slug = normalizar(valor)
    if not slug:
        carpeta = Path(valor).expanduser()
        if carpeta.is_dir():
            return carpeta
        raise SystemExit(f"no entiendo el repositorio: {valor!r}")
    anotar(slug, branch)
    if modo == "nube":
        if not quiet:
            print(f"[repo_url] anotado {slug} ({branch}) en {REPO_TXT.name} · sin clonar")
        return REPO_TXT
    destino = _clonar(slug, branch, quiet)
    if not quiet:
        print(f"[repo_url] clon al día en {destino}")
    return destino


def _main() -> int:
    _utf8()
    ap = argparse.ArgumentParser("repo_url", description="Anota el remoto (y clona en modo local).")
    ap.add_argument("--url", required=True)
    ap.add_argument("--branch", default="main")
    ap.add_argument("--modo", default="local", choices=("local", "nube"))
    args = ap.parse_args()
    print(resolver(args.url, args.branch, quiet=False, modo=args.modo))
    return 0


if __name__ == "__main__":
    sys.exit(_main())