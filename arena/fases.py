"""Fases del proyecto: se leen de un archivo y su estado vive aparte.

Tres formatos, en este orden de prioridad:

  * `tareas.txt`  -> UNA LÍNEA = UNA FASE. Es el modo para listas de 900 o 42000 tareas.
  * `fases.txt`   -> bloques separados por una línea de tres guiones (`---`).
  * `fases.jsonl` -> una fase JSON por línea.

El estado (pendiente/enviada/hecha/bloqueada, intentos, motivo, enviada_en) NO se escribe
en esos archivos: vive en `<archivo>.estado.json`, indexado por el TEXTO del objetivo.
El estado se guarda fusionando con lo que ya haya en disco antes de escribir: varios
procesos (varias pestañas) pueden marcar fases a la vez sin pisarse.

`refrescar()` vuelve a leer el estado de disco para que un trabajador no repita una fase
que otro proceso acaba de marcar como hecha.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

__all__ = ["Backlog", "ESTADOS", "cargar", "elegir_fases"]

ESTADOS = {"pendiente", "enviada", "hecha", "bloqueada"}
_POR_HACER = {"pendiente", "enviada"}
_TERMINADAS = {"hecha", "bloqueada"}
_SEPARADOR = re.compile(r"^\s*-{3,}\s*$")
_COMENTARIO = re.compile(r"^\s*#")
NOMBRES = ("tareas.txt", "fases.txt", "fases.jsonl")


def _clave(texto: str) -> str:
    return hashlib.sha1(texto.strip().encode("utf-8")).hexdigest()[:16]


def _normalizar(crudo: Any, numero: int) -> dict[str, Any]:
    if isinstance(crudo, str):
        crudo = {"objetivo": crudo}
    if not isinstance(crudo, dict):
        crudo = {"objetivo": str(crudo)}
    fase = dict(crudo)
    fase["id"] = str(fase.get("id") or f"{numero:03d}")
    objetivo = str(fase.get("objetivo") or fase.get("prompt") or "").strip()
    fase["objetivo"] = objetivo
    titulo = str(fase.get("titulo") or "").strip()
    if not titulo:
        titulo = (objetivo.splitlines()[0][:60] if objetivo else fase["id"])
    fase["titulo"] = titulo
    if isinstance(fase.get("archivos"), str):
        fase["archivos"] = [fase["archivos"]]
    fase.setdefault("estado", "pendiente")
    return fase


def _desde_lineas(ruta: Path) -> list[Any]:
    crudos: list[Any] = []
    if not ruta.is_file():
        return crudos
    for linea in ruta.read_text(encoding="utf-8", errors="replace").splitlines():
        limpia = linea.strip()
        if not limpia or limpia.startswith("#"):
            continue
        crudos.append(limpia)
    return crudos


def _desde_texto(ruta: Path) -> list[Any]:
    crudos: list[Any] = []
    if not ruta.is_file():
        return crudos
    for bloque in _SEPARADOR.split(ruta.read_text(encoding="utf-8", errors="replace")):
        lineas = [l for l in bloque.splitlines() if not _COMENTARIO.match(l)]
        texto = "\n".join(lineas).strip()
        if texto:
            crudos.append(texto)
    return crudos


def _desde_jsonl(ruta: Path) -> list[Any]:
    crudos: list[Any] = []
    if not ruta.is_file():
        return crudos
    for numero, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
        if not linea.strip():
            continue
        try:
            crudos.append(json.loads(linea))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{ruta.name}:{numero} no es JSON válido: {exc}") from exc
    return crudos


def cargar(ruta: Path) -> list[dict[str, Any]]:
    ruta = Path(ruta).expanduser()
    nombre = ruta.name.lower()
    if nombre.startswith("tareas"):
        crudos = _desde_lineas(ruta)
    elif ruta.suffix.lower() == ".txt":
        crudos = _desde_texto(ruta)
    else:
        crudos = _desde_jsonl(ruta)
    return [_normalizar(crudo, numero) for numero, crudo in enumerate(crudos, 1)]


def elegir_fases(proyecto: Path, explicito: str | None = None, nube: bool | None = None) -> Path:
    if nube is None:
        nube = os.environ.get("AUTONOMA_MODO", "").lower() in ("nube", "cloud")

    base = Path(proyecto)

    if explicito:
        for candidato in (Path(explicito).expanduser(), base / explicito, base.parent / explicito):
            if candidato.is_file():
                return candidato
        return Path(explicito).expanduser()

    if nube:
        carpetas = (base.parent / "arena", base, base.parent)
        orden = ("tareas.txt",) + tuple(n for n in NOMBRES if n != "tareas.txt")
    else:
        carpetas = (base, base.parent / "arena", base.parent)
        orden = NOMBRES

    for carpeta in carpetas:
        for nombre in orden:
            ruta = carpeta / nombre
            if ruta.is_file():
                return ruta
    return base / NOMBRES[0]


class Backlog:
    """Lista ordenada de fases con su estado, persistida aparte del archivo de fases."""

    def __init__(self, ruta: Path) -> None:
        self.ruta = Path(ruta).expanduser().resolve()
        self.estado_ruta = self.ruta.with_suffix(".estado.json")
        self._estado: dict[str, dict[str, Any]] = self._leer_estado()
        self.fases = [self._fusion(fase) for fase in cargar(self.ruta)]

    # ------------------------------------------------------------- estado en disco
    def _leer_estado(self) -> dict[str, dict[str, Any]]:
        if not self.estado_ruta.is_file():
            return {}
        try:
            datos = json.loads(self.estado_ruta.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
        return datos if isinstance(datos, dict) else {}

    def refrescar(self) -> None:
        """Vuelve a leer el estado de disco y recompone las fases.

        Sirve para que un trabajador no repita una fase que otro proceso (u otra pestaña)
        acaba de marcar como hecha o bloqueada mientras este dormía.
        """
        self._estado = self._leer_estado()
        self.fases = [self._fusion(fase) for fase in cargar(self.ruta)]

    def _fusion(self, fase: dict[str, Any]) -> dict[str, Any]:
        entrada = self._estado.get(_clave(fase["objetivo"])) or {}
        fusionada = dict(fase)
        fusionada["estado"] = entrada.get("estado", fase.get("estado", "pendiente"))
        if "intentos" in entrada:
            fusionada["intentos"] = entrada["intentos"]
        if "critica" in entrada:
            fusionada["critica"] = entrada["critica"]
        return fusionada

    def _guardar(self, fusionar: bool = True) -> None:
        if fusionar:
            en_disco = self._leer_estado()
            en_disco.update(self._estado)
            self._estado = en_disco
        texto = json.dumps(self._estado, ensure_ascii=False, indent=2) + "\n"
        self.estado_ruta.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporal = tempfile.mkstemp(
            dir=self.estado_ruta.parent, prefix=".estado-", suffix=".tmp"
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(texto)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temporal, self.estado_ruta)
        finally:
            with contextlib.suppress(OSError):
                Path(temporal).unlink(missing_ok=True)

    # ------------------------------------------------------------------- consulta
    def _fase(self, id_fase: str) -> dict[str, Any]:
        for fase in self.fases:
            if str(fase.get("id")) == str(id_fase):
                return fase
        raise KeyError(f"fase desconocida: {id_fase}")

    def intentos_de(self, id_fase: str) -> int:
        return int(self._fase(id_fase).get("intentos") or 0)

    def _entrada(self, fase: dict[str, Any]) -> dict[str, Any]:
        return self._estado.setdefault(_clave(fase["objetivo"]), {})

    def estado_de(self, id_fase: str) -> str:
        return str(self._fase(id_fase).get("estado") or "pendiente")

    def siguiente(self) -> dict[str, Any] | None:
        for fase in self.fases:
            if str(fase.get("estado") or "pendiente") in _POR_HACER:
                return fase
        return None

    def pendientes(self) -> list[dict[str, Any]]:
        return [f for f in self.fases if str(f.get("estado") or "pendiente") not in _TERMINADAS]

    # ------------------------------------------------------------------- escritura
    def marcar(self, id_fase: str, estado: str, critica: str = "") -> None:
        fase = self._fase(id_fase)
        fase["estado"] = estado
        entrada = self._entrada(fase)
        entrada["estado"] = estado
        if estado != "enviada":
            entrada.pop("enviada_en", None)
        if critica:
            entrada["critica"] = critica
            fase["critica"] = critica
        elif estado != "bloqueada":
            entrada.pop("critica", None)
            fase.pop("critica", None)
        self._guardar()

    def marcar_enviada(self, id_fase: str) -> None:
        """Se persiste ANTES de esperar la respuesta: un reinicio no reenvía a ciegas."""
        fase = self._fase(id_fase)
        fase["estado"] = "enviada"
        entrada = self._entrada(fase)
        entrada["estado"] = "enviada"
        entrada["enviada_en"] = time.time()
        self._guardar()

    def enviada_hace(self, id_fase: str) -> float | None:
        entrada = self._estado.get(_clave(self._fase(id_fase)["objetivo"])) or {}
        cuando = entrada.get("enviada_en")
        return (time.time() - float(cuando)) if cuando else None

    def reintentar(self, id_fase: str) -> int:
        fase = self._fase(id_fase)
        entrada = self._entrada(fase)
        entrada["intentos"] = int(entrada.get("intentos") or 0) + 1
        fase["intentos"] = entrada["intentos"]
        self._guardar()
        return entrada["intentos"]

    def reiniciar(self) -> None:
        self._estado.clear()
        for fase in self.fases:
            fase["estado"] = "pendiente"
            fase.pop("intentos", None)
            fase.pop("critica", None)
        self._guardar(fusionar=False)

    def resumen(self) -> str:
        hechas = sum(1 for f in self.fases if f.get("estado") == "hecha")
        bloqueadas = sum(1 for f in self.fases if f.get("estado") == "bloqueada")
        return f"{hechas}/{len(self.fases)} hechas · {bloqueadas} bloqueadas"


def _main() -> int:
    for flujo in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            flujo.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser("fases", description="Estado del backlog de Autonoma.")
    ap.add_argument("--proyecto", default="proyecto")
    ap.add_argument("--fases", default=None)
    ap.add_argument("--nube", action="store_true")
    ap.add_argument("--resumen", action="store_true")
    ap.add_argument("--reiniciar", action="store_true")
    args = ap.parse_args()

    if args.nube:
        os.environ["AUTONOMA_MODO"] = "nube"

    ruta = elegir_fases(Path(args.proyecto), args.fases, nube=args.nube)
    if not ruta.is_file():
        print(f"[fases] no encuentro el backlog: {ruta}")
        return 2

    backlog = Backlog(ruta)
    if args.reiniciar:
        backlog.reiniciar()
        print("[fases] estado reiniciado")

    print(f"backlog : {ruta}")
    print(f"estado  : {backlog.estado_ruta}")
    print(f"resumen : {backlog.resumen()}")
    if not args.resumen:
        for fase in backlog.fases:
            marca = {"hecha": "[x]", "enviada": "[>]", "bloqueada": "[!]"}.get(fase.get("estado"), "[ ]")
            print(f"  {marca} {fase.get('id')} {fase.get('titulo', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())