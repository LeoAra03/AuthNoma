"""Contrato de salida de arena: bloques ```lang path=ruta con el archivo COMPLETO."""
import re
from pathlib import Path

RE_BLOQUE = re.compile(r"```[\w+-]*\s+path=([^\s`]+)\s*\n(.*?)```", re.S)
RE_BORRAR = re.compile(r"^\s*BORRAR:\s*(\S+)\s*$", re.M)

def parsear(texto: str) -> tuple[list[tuple[str, str]], list[str]]:
    return RE_BLOQUE.findall(texto), RE_BORRAR.findall(texto)

def aplicar(repo: Path, archivos, borrados) -> list[str]:
    repo = repo.resolve()
    tocados = []
    for ruta, contenido in archivos:
        p = (repo / ruta.strip()).resolve()
        if not str(p).startswith(str(repo)):
            raise RuntimeError(f"{ruta} se sale del repo")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(contenido.rstrip() + "\n", encoding="utf-8")
        tocados.append(ruta.strip())
    for ruta in borrados:
        p = (repo / ruta.strip()).resolve()
        if p.is_file():
            p.unlink(); tocados.append(f"-{ruta.strip()}")
    return tocados