"""Comprobacion previa. Si dice LISTO, el bot va a funcionar."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

AQUI = Path(__file__).parent
RAIZ = AQUI.parent
sys.path.insert(0, str(AQUI))

FALLOS, AVISOS = [], []


def ok(m): print(f"  [ok]    {m}")
def aviso(m): print(f"  [aviso] {m}"); AVISOS.append(m)
def fallo(m): print(f"  [FALLO] {m}"); FALLOS.append(m)


def paso(nombre, fn):
    print(f"\n{nombre}")
    try:
        fn()
    except Exception as e:
        fallo(str(e))


def cfg():
    return json.loads((AQUI / "config.json").read_text(encoding="utf-8"))


def chk_config():
    c = cfg()
    for clave in ("cdp", "url_arena", "patron_pestana", "selectores", "metodo_envio"):
        if clave not in c:
            raise RuntimeError(f"config.json no tiene '{clave}'")
    ok(f"config.json valido (envio por {c['metodo_envio']})")


def chk_protocolo():
    r = AQUI / "protocolo.md"
    if not r.exists():
        raise RuntimeError(f"falta {r}")
    ok(f"protocolo.md ({len(r.read_text(encoding='utf-8'))} chars)")


def chk_fases():
    r = RAIZ / "proyecto" / "fases.jsonl"
    if not r.exists():
        raise RuntimeError(f"falta {r}")
    n = pend = 0
    for i, linea in enumerate(r.read_text(encoding="utf-8").splitlines(), 1):
        if not linea.strip():
            continue
        f = json.loads(linea)
        n += 1
        if f.get("estado") != "hecha":
            pend += 1
        for c in ("id", "titulo", "objetivo", "criterio"):
            if not f.get(c):
                raise RuntimeError(f"{r}:{i} sin '{c}'")
    ok(f"{n} fase(s), {pend} pendiente(s)")


def chk_playwright():
    from playwright.sync_api import sync_playwright  # noqa
    ok("playwright instalado")


def chk_puerto():
    destino = cfg()["cdp"].split("//")[-1]
    host, puerto = destino.rsplit(":", 1)
    s = socket.socket(); s.settimeout(2)
    try:
        s.connect((host, int(puerto)))
    finally:
        s.close()
    ok(f"{destino} escucha")


def chk_pestana():
    c = cfg()
    datos = json.loads(urllib.request.urlopen(c["cdp"].rstrip("/") + "/json/list", timeout=5).read())
    urls = [t.get("url", "") for t in datos if t.get("type") == "page"]
    if not urls:
        raise RuntimeError("Brave no tiene pestanas")
    if any(c["patron_pestana"] in u for u in urls):
        ok("pestana de arena.ai encontrada")
    else:
        aviso(f"ninguna pestana contiene '{c['patron_pestana']}'; se abrira {c['url_arena']}")


def chk_git():
    r = subprocess.run("git rev-parse --is-inside-work-tree", shell=True,
                       cwd=str(RAIZ), capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("la carpeta del proyecto no es un repo git")
    ok("repo git presente")


def chk_sesion():
    from puente import Puente
    with Puente() as p:
        if not p.parece_logueado():
            raise RuntimeError("no veo el compositor; inicia sesion en arena.ai")
    ok("arena.ai con sesion activa")


def main():
    print("=== Autonoma: comprobacion previa ===")
    paso("1. config.json", chk_config)
    paso("2. protocolo.md", chk_protocolo)
    paso("3. proyecto/fases.jsonl", chk_fases)
    paso("4. dependencias", chk_playwright)
    paso("5. puerto de depuracion", chk_puerto)
    paso("6. pestana de arena.ai", chk_pestana)
    paso("7. git", chk_git)
    paso("8. sesion en arena.ai", chk_sesion)

    print("\n" + "=" * 40)
    if FALLOS:
        print("NO LISTO. Arregla:")
        for f in FALLOS:
            print("  - " + f)
        return 1
    print("LISTO PARA ARRANCAR -> py arena\\orquestador.py")
    for a in AVISOS:
        print("  (aviso) " + a)
    return 0


if __name__ == "__main__":
    sys.exit(main())