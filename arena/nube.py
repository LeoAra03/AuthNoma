"""Modo nube: conduce arena.ai (Agent Mode) sin clonar el repo en el disco.

MODELO DE TRABAJO
  * LOTE   = N fases (por defecto 500) en UN SOLO prompt. El agente las hace seguidas en
             la misma rama, marca @@FASE_OK@@ <id> por cada una y cierra con @@LOTE_OK@@.
  * SESIÓN  = 2500 fases (5 lotes) en una rama y un PR.
  * El MERGE solo se hace al cerrar la SESIÓN (2500 fases) o por emergencia.
    Después: merge -> borrar rama -> archivar chat -> chat NUEVO sobre main -> seguir.
  * El bot NUNCA interrumpe: antes de enviar espera a que el agente esté libre.
  * Si la pestaña se cuelga, la espera lo distingue de "terminó" (ver puente.py).
  * El navegador se levanta y se espera solo; las pestañas de arena se ajustan al número
    pedido y se eligen siempre en el mismo orden (ver navegador.py y puente.py).

    py nube.py --repo owner/repo --branch main
    py nube.py --resumen
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

import puente  # noqa: E402
import ramas  # noqa: E402
from fases import Backlog, elegir_fases  # noqa: E402

try:
    from notificar import avisar as _avisar_mod  # noqa: E402
except Exception:  # noqa: BLE001
    _avisar_mod = None

try:
    import pulidor  # noqa: E402
except Exception:  # noqa: BLE001
    pulidor = None

PROTOCOLO = AQUI / "protocolo_nube.md"
STOP = AQUI / "STOP"
REPO_TXT = AQUI / "REPO.txt"
ARCHIVO_CHATS = AQUI / "chats_archivados.jsonl"

MARCA_LOTE = "@@LOTE_OK@@"
RE_FASE_OK = re.compile(r"@@FASE_OK@@\s*([A-Za-z0-9_.\-]+)")
RE_BLOQUEO_ID = re.compile(r"@@BLOQUEADO:\s*([A-Za-z0-9_.\-]+)\s*[·\-:|]\s*(.+?)@@", re.S)
RE_BLOQUEO_SUELTO = re.compile(r"@@BLOQUEADO:\s*(.+?)@@", re.S)
MARCA_PR = re.compile(r"@@PR:\s*(\S+?)@@")

_RECUPERABLE = re.compile(
    r"sesi[oó]n|session|cerrad|closed|clos|rama|branch|push|remote|remoto|"
    r"pr\s*#|pull request|merged|merge|nueva sesi[oó]n|github bloquea",
    re.I,
)

REANUDAR_LOTE = (
    "Tu turno se cortó a mitad del LOTE. NO empieces de cero.\n"
    "Sigue en LA MISMA rama y EL MISMO PR. Retoma por la PRIMERA fase que todavía no tenga "
    "su @@FASE_OK@@, termina el lote entero y cierra con @@LOTE_OK@@."
)

EMPUJON_LOTE = (
    "Sigues sin cerrar el lote. Termina en la MISMA rama las fases que falten, escribe "
    "@@FASE_OK@@ <id> por cada una que completes y cierra con @@LOTE_OK@@."
)

_CANDADO_CHATS = threading.Lock()
_CANDADO_ESTADO = threading.Lock()
ESTADO: dict[int, dict] = {}


# ------------------------------------------------------------------ avisos
def _avisador_imprime() -> bool:
    """Detecta si notificar.avisar ya imprime por su cuenta (evita líneas dobles)."""
    if _avisar_mod is None:
        return False
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            _avisar_mod("__sonda__")
    except Exception:  # noqa: BLE001
        return False
    return bool(buffer.getvalue().strip())


_AVISADOR_IMPRIME = _avisador_imprime()


def avisar(mensaje: str) -> None:
    if not _AVISADOR_IMPRIME:
        print(mensaje, flush=True)
    if _avisar_mod is not None:
        with contextlib.suppress(Exception):
            _avisar_mod(mensaje)


# ---------------------------------------------------------------- utilidades
def _texto(fase: dict) -> str:
    for attr in ("objetivo", "texto", "descripcion", "linea"):
        valor = fase.get(attr)
        if valor:
            return str(valor).strip()
    return str(fase).strip()


def _clave(fase: dict) -> str:
    valor = fase.get("clave") or fase.get("id")
    return str(valor) if valor else hashlib.sha1(_texto(fase).encode("utf-8")).hexdigest()[:16]


def _marca_lote(numero: int, desde: str, hasta: str, clave: str, intento: int) -> str:
    return f"===== LOTE {numero} · fases {desde}-{hasta} [{clave}-{intento}] ====="


def _rango(fases: list[dict], spec: str | None) -> list[dict]:
    if not spec:
        return fases
    a, _, b = spec.partition("-")
    desde = max(1, int(a)) - 1
    hasta = int(b) if b else len(fases)
    return fases[desde:hasta]


def _prompt_lote(marca, fases, protocolo, con_protocolo, repo, rama_base, rama, rama_existe, ya_hechas, mostrar_rama):
    cab = f"{protocolo}\n\n" if con_protocolo else ""
    reglas = [
        f"Repositorio: `{repo}` · Rama base: `{rama_base}`.",
        f"Vas a ejecutar estas {len(fases)} fases SEGUIDAS, en ESTA MISMA rama y ESTE MISMO PR, "
        f"sin parar entre ellas.",
        "- Una fase = su propio commit en la rama. NO abras rama nueva ni PR nuevo.",
        "- Al terminar CADA fase escribe una línea EXACTA:  @@FASE_OK@@ <id>",
        "- Si una fase necesita decisión humana escribe  @@BLOQUEADO: <id> · <motivo>@@  y SIGUE con la siguiente.",
        "- Al terminar TODAS escribe como última línea:  @@LOTE_OK@@",
        "- No pares a preguntar ni resumas el lote entero al final.",
        "- No pidas confirmación: decide y sigue.",
    ]
    if ya_hechas:
        reglas.append(f"- Ya están hechas y empujadas: {', '.join(ya_hechas)}. NO las repitas.")
    if rama and rama_existe:
        reglas.append(f"- La rama `{rama}` YA existe con su PR abierto: continúa en ELLA.")
    elif rama and mostrar_rama:
        reglas.append(f"- Rama de trabajo de esta sesión: `{rama}` (créala desde `{rama_base}`).")

    cuerpo = "\n\n".join(f"--- FASE {f['id']} ---\n{_texto(f)}" for f in fases)
    return f"{cab}{marca}\n\n" + "\n".join(reglas) + f"\n\n{cuerpo}\n\nCierra con @@LOTE_OK@@."


def _leer_remoto(args) -> tuple[str, str]:
    repo = (args.repo or os.environ.get("AUTONOMA_REPO") or "").strip()
    rama = (args.branch or os.environ.get("AUTONOMA_RAMA") or "").strip()
    if (not repo or not rama) and REPO_TXT.is_file():
        lineas = REPO_TXT.read_text(encoding="utf-8").splitlines()
        if not repo and lineas:
            repo = lineas[0].strip()
        if not rama:
            rama = lineas[2].strip() if len(lineas) > 2 else (lineas[1].strip() if len(lineas) > 1 else "")
    return repo, (rama or "main")


def registrar_chat(chat: str, motivo: str, clave: str) -> None:
    entrada = {
        "fecha": time.strftime("%Y-%m-%d %H:%M:%S"),
        "chat": chat or "",
        "motivo": motivo,
        "fase": clave,
    }
    with _CANDADO_CHATS:
        with contextlib.suppress(Exception):
            with ARCHIVO_CHATS.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entrada, ensure_ascii=False) + "\n")


def _vivo(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    except Exception:  # noqa: BLE001
        return True
    return True


# --------------------------------------------------------- instancia y reclamos
def _tomar_instancia(slug: str) -> Path | None:
    nombre = slug.replace("/", "_") or "local"
    archivo = AQUI / f".nube-{nombre}.lock"
    if archivo.is_file():
        try:
            pid = int((archivo.read_text(encoding="utf-8").split() or ["0"])[0])
        except Exception:  # noqa: BLE001
            pid = 0
        if pid and pid != os.getpid() and _vivo(pid):
            return None
    archivo.write_text(f"{os.getpid()}\n", encoding="utf-8")
    return archivo


class Reclamos:
    def __init__(self, archivo: Path) -> None:
        self.dir = archivo.with_suffix(archivo.suffix + ".reclamos")
        self.dir.mkdir(parents=True, exist_ok=True)

    def _lock(self, clave: str) -> Path:
        return self.dir / f"{clave}.lock"

    def limpiar(self, minutos: float) -> int:
        quitados = 0
        ahora = time.time()
        for ruta in self.dir.glob("*.lock"):
            pid, edad = 0, 10**9
            try:
                pid = int((ruta.read_text(encoding="utf-8", errors="replace").split() or ["0"])[0])
                edad = ahora - ruta.stat().st_mtime
            except Exception:  # noqa: BLE001
                pass
            if (pid and not _vivo(pid)) or edad > minutos * 60:
                with contextlib.suppress(OSError):
                    ruta.unlink()
                quitados += 1
        return quitados

    def reclamar(self, clave: str) -> bool:
        try:
            descriptor = os.open(self._lock(clave), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        os.write(descriptor, f"{os.getpid()} {int(time.time())}".encode())
        os.close(descriptor)
        return True

    def liberar(self, clave: str) -> None:
        with contextlib.suppress(FileNotFoundError):
            os.remove(self._lock(clave))


# ------------------------------------------------- sesión persistida en disco
def _sesion_ruta(slug: str, indice: int) -> Path:
    nombre = (slug or "local").replace("/", "_")
    return AQUI / f".nube-{nombre}.sesion-{indice}.json"


def guardar_sesion(slug: str, indice: int, chat: dict) -> None:
    if not slug:
        return
    with contextlib.suppress(Exception):
        _sesion_ruta(slug, indice).write_text(
            json.dumps(
                {
                    "rama": chat.get("rama") or "",
                    "fases": int(chat.get("fases") or 0),
                    "actualizado": time.time(),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


def adoptar_sesion(chat: dict, slug: str, indice: int) -> None:
    """Si quedó una sesión viva de una ejecución anterior, la retoma.

    Evita el peor error posible: relanzar tras un corte y fusionar a las 300 fases
    porque el contador de la sesión se perdió con el proceso.
    """
    ruta = _sesion_ruta(slug, indice)
    if not slug or not ruta.is_file():
        return
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return
    rama = str(datos.get("rama") or "")
    if not rama or not ramas.existe_rama(slug, rama):
        return
    chat["rama"] = rama
    chat["fases"] = int(datos.get("fases") or 0)
    avisar(f"[tab {indice}] sesión recuperada: {rama} ({chat['fases']} fases ya empujadas)")


# ------------------------------------------------------------- github: cierre
def _slug(args) -> str:
    if args.sin_github or not ramas.activo():
        return ""
    repo, _ = _leer_remoto(args)
    return ramas.repositorio(repo)


def detectar_rama(slug: str, foto: set[str], respuesta: str) -> str:
    if not slug or not ramas.hay_token():
        return ""
    encontrado = MARCA_PR.search(respuesta or "")
    if encontrado:
        pr = ramas.pr_por_url(slug, encontrado.group(1))
        if pr:
            head = str((pr.get("head") or {}).get("ref") or "")
            if head:
                return head
    nuevas = [r for r in ramas.ramas_de_trabajo(slug) if r not in foto]
    if not nuevas:
        return ""
    con_pr = [r for r in nuevas if ramas.pr_de_rama(slug, r)]
    return (con_pr or nuevas)[-1]


def _anotar_rama(chat: dict, slug: str, respuesta: str) -> None:
    if chat.get("rama") or not slug:
        return
    rama = detectar_rama(slug, chat.get("foto") or set(), respuesta)
    if rama:
        chat["rama"] = rama
        avisar(f"[nube] rama de la sesión: {rama}")


def cerrar_ciclo(p, args, chat: dict, motivo: str, slug: str, clave: str = "", indice: int = 0) -> bool:
    """Merge del PR + archivar + chat nuevo sobre main. SOLO emergencia o checkpoint."""
    rama = chat.get("rama") or detectar_rama(slug, chat.get("foto") or set(), "")
    ok, detalle = True, "sin rama que fusionar"

    if rama and slug and ramas.hay_token():
        ok, detalle = ramas.fusionar(slug, rama, borrar=True)
        avisar(f"[nube] MERGE ({motivo}): {'ok' if ok else 'FALLO'} — {detalle}")
    else:
        avisar(f"[nube] cierre sin rama ({motivo})")

    registro = p.chat_id()
    registrar_chat(registro, motivo, clave)
    if not p.archivar_chat():
        avisar("[nube] aviso: no pude archivar en la interfaz; recargo y sigo")
    p.nueva_charla()
    with contextlib.suppress(Exception):
        p.cerrar_modal()
    for linea in p.preparar_agente():
        avisar(f"[nube] agente: {linea}")

    chat["foto"] = ramas.foto(slug) if slug else set()
    chat["rama"] = ""
    chat["fases"] = 0
    guardar_sesion(slug, indice, chat)
    return ok


# ------------------------------------------------------------ recuperar pestana
def descolgar(p, args, parar_agente: bool = True) -> bool:
    for intento in range(1, args.reintentos_recarga + 1):
        try:
            if p.descolgar(parar_agente):
                avisar("[nube] pestaña descolgada; seguimos en el MISMO chat")
                return True
        except Exception as exc:  # noqa: BLE001
            avisar(f"[nube] descolgar {intento}/{args.reintentos_recarga} falló: {type(exc).__name__}")
        time.sleep(3)
    return False


def recargar(p, args) -> bool:
    for intento in range(1, args.reintentos_recarga + 1):
        try:
            p.reiniciar_charla()
            if p.parece_logueado():
                p.preparar_agente()
                avisar("[nube] pestaña recargada de cero")
                return True
            avisar(f"[nube] tras recargar, arena.ai no está listo ({intento}/{args.reintentos_recarga})")
        except Exception as exc:  # noqa: BLE001
            avisar(f"[nube] recarga {intento}/{args.reintentos_recarga} falló: {type(exc).__name__}")
        time.sleep(3)
    return False


def _enviar_verificado(p, args, texto, marca, etiqueta) -> tuple[bool, str]:
    for intento in (1, 2):
        try:
            eco = p.enviar(texto, marca)
        except Exception as exc:  # noqa: BLE001
            avisar(f"[{etiqueta}] fallo al enviar ({type(exc).__name__})")
            eco = ""
        if p.hay_texto(marca) and not p.compositor_con_texto():
            return True, eco
        avisar(f"[{etiqueta}] el mensaje no llegó al chat (intento {intento})")
        if intento == 1 and descolgar(p, args):
            continue
        return False, eco
    return False, ""


def _pulir(texto: str) -> str:
    if pulidor is None or not pulidor.activado():
        return texto
    return pulidor.pulir(texto)


def _tick(indice: int, etiqueta: str, numero: int, total: int):
    def cb(esperando: float, quieto: float, largo: int) -> None:
        if quieto < 0:
            estado_txt = "página lenta"
        elif largo <= 5:
            estado_txt = "esperando"
        else:
            estado_txt = "trabajando"
        with _CANDADO_ESTADO:
            ESTADO[indice] = {
                "clave": etiqueta, "numero": numero, "total": total,
                "esperando": esperando, "quieto": quieto, "largo": largo,
                "estado": estado_txt,
            }
    return cb


def _hay_stop() -> bool:
    return STOP.exists()


# --------------------------------------------------------------------- lote
def procesar_lote(p, args, backlog, fases, numero_lote, total, slug, chat, indice) -> dict:
    """Ejecuta un LOTE (varias fases) en un solo prompt."""
    ids = [f["id"] for f in fases]
    desde, hasta = ids[0], ids[-1]
    clave_lote = hashlib.sha1(",".join(ids).encode("utf-8")).hexdigest()[:8]
    etiqueta = f"lote {numero_lote} ({desde}-{hasta})"

    # El tope escala con el trabajo encargado: 500 fases no caben en 40 minutos.
    tope = max(float(args.tope_lote), len(fases) * float(args.segundos_por_fase))

    hechas: list[dict] = []
    bloqueadas: list[tuple[dict, str]] = []
    pendientes: list[dict] = []

    intento = 0
    modo = "completo"
    suaves = recargas = empujones = 0
    max_intentos_lote = max(1, int(args.max_intentos))
    rama_existe = False
    incluir_protocolo = numero_lote == 1
    estado, respuesta = "timeout", ""

    repo, rama_base = _leer_remoto(args)

    while True:
        rama = chat.get("rama") or f"{ramas.prefijo()}{clave_lote}"
        intento += 1
        if intento > max_intentos_lote:
            avisar(
                f"[{etiqueta}] alcanzado el máximo de {max_intentos_lote} intentos; "
                "devuelvo las fases a la cola"
            )
            estado = "timeout"
            break
        marca = _marca_lote(numero_lote, desde, hasta, clave_lote, intento)
        with _CANDADO_ESTADO:
            ESTADO[indice] = {"clave": etiqueta, "numero": numero_lote, "total": total,
                              "esperando": 0.0, "quieto": 0.0, "largo": 0, "estado": "enviando"}

        if modo == "completo":
            ya = [f["id"] for f in fases if backlog.estado_de(f["id"]) == "hecha"]
            texto = _pulir(_prompt_lote(marca, fases, PROTOCOLO_TXT, incluir_protocolo,
                                        repo, rama_base, rama, rama_existe, ya, args.mostrar_rama))
        elif modo == "reanudar":
            texto = f"{marca}\n\n{REANUDAR_LOTE}"
        else:
            texto = f"{marca}\n\n{EMPUJON_LOTE}"

        avisar(f"[{etiqueta}] intento {intento} ({modo}) · tope {int(tope)}s · {len(fases)} fases")
        fin_previos = p.contar(MARCA_LOTE)
        enviado, eco = _enviar_verificado(p, args, texto, marca, etiqueta)
        if not enviado:
            estado, respuesta = "timeout", ""
        else:
            for fase in fases:
                if backlog.estado_de(fase["id"]) != "hecha":
                    backlog.marcar_enviada(fase["id"])
            modo = "reanudar"
            rama_existe = bool(chat.get("rama"))
            try:
                estado, respuesta = p.esperar_fase(
                    marca, tope, _tick(indice, etiqueta, numero_lote, total),
                    fin=MARCA_LOTE, parar_en_bloqueo=False,
                    fin_previos=fin_previos, peso=len(fases), cancelar=_hay_stop,
                )
            except Exception as exc:  # noqa: BLE001
                avisar(f"[{etiqueta}] excepción esperando: {type(exc).__name__}")
                estado, respuesta = "timeout", ""

        if estado in ("ok", "cancelado"):
            break

        if estado == "sin_marca":
            empujones += 1
            avisar(f"[{etiqueta}] el agente se quedó quieto sin cerrar (empujón {empujones}/{args.empujones_max})")
            if empujones <= args.empujones_max:
                modo = "empujar"
                continue
            estado = "timeout"

        avisar(f"[{etiqueta}] timeout")
        if suaves < args.reintentos_suaves:
            suaves += 1
            avisar(f"[{etiqueta}] recuperación suave (mismo chat)")
            if descolgar(p, args):
                modo = "reanudar"
                continue
        if recargas < args.recargas_max:
            recargas += 1
            avisar(f"[{etiqueta}] recarga dura de la pestaña")
            if recargar(p, args):
                modo = "completo"
                incluir_protocolo = True
                rama_existe = bool(chat.get("rama"))
                continue
        if descolgar(p, args):
            modo = "reanudar"
            continue

        if intento >= max_intentos_lote:
            avisar(
                f"[{etiqueta}] sin recuperación tras {max_intentos_lote} intentos; "
                "devuelvo las fases a la cola"
            )
            estado = "timeout"
            break

        avisar(f"[{etiqueta}] EMERGENCIA: cierro la sesión y reintento el lote")
        cerrar_ciclo(p, args, chat, "emergencia-lote", slug, clave_lote, indice)
        modo, rama_existe, incluir_protocolo = "completo", False, True
        suaves = recargas = empujones = 0

    # --------------------------------------------------------- leer resultado
    _anotar_rama(chat, slug, respuesta)
    ok_ids = set(RE_FASE_OK.findall(respuesta))
    motivos: dict[str, str] = {}
    for encontrado in RE_BLOQUEO_ID.finditer(respuesta):
        motivos[encontrado.group(1)] = " ".join(encontrado.group(2).split())[:200]
    if not motivos and not ok_ids:
        suelto = RE_BLOQUEO_SUELTO.search(respuesta)
        if suelto:
            motivos[ids[0]] = " ".join(suelto.group(1).split())[:200]

    recuperable = False
    for fase in fases:
        fid = fase["id"]
        if fid in ok_ids:
            backlog.marcar(fid, "hecha")
            hechas.append(fase)
        elif fid in motivos:
            motivo = motivos[fid]
            if _RECUPERABLE.search(motivo):
                recuperable = True
            backlog.marcar(fid, "bloqueada", motivo)
            bloqueadas.append((fase, motivo))
        else:
            backlog.reintentar(fid)
            backlog.marcar(fid, "pendiente")
            pendientes.append(fase)

    if recuperable:
        avisar("[nube] bloqueo de sesión dentro del lote: cierro la sesión")
        cerrar_ciclo(p, args, chat, "bloqueo-sesion", slug, clave_lote, indice)
        for fase, _ in bloqueadas:
            backlog.marcar(fase["id"], "pendiente")
            pendientes.append(fase)
        bloqueadas = []

    avisar(
        f"[{etiqueta}] resultado ({estado}): {len(hechas)} hechas · "
        f"{len(bloqueadas)} bloqueadas · {len(pendientes)} pendientes"
    )
    return {"hechas": hechas, "bloqueadas": bloqueadas, "pendientes": pendientes, "estado": estado}


PROTOCOLO_TXT = ""


# --------------------------------------------------------------------- latido
def latir(args, parar: threading.Event) -> None:
    intervalo = max(5, int(args.latido))
    while not parar.is_set():
        if parar.wait(intervalo):
            return
        with _CANDADO_ESTADO:
            copia = dict(ESTADO)
        for indice in sorted(copia):
            d = copia[indice]
            quieto = int(d["quieto"]) if d["quieto"] >= 0 else -1
            avisar(
                f"[latido] tab {indice} · {d['estado']} · {d['clave']} · "
                f"esperando {int(d['esperando'])}s · sin cambios {quieto}s · respuesta {d['largo']} chars"
            )


# --------------------------------------------------------------------- bucle
def trabajador(indice, backlog, reclamos, pendientes, args, resumen, candado, slug) -> None:
    mia = pendientes[indice :: max(1, args.pestanas)]
    if not mia:
        return
    avisar(f"[tab {indice}] {len(mia)} fases asignadas · lotes de {args.fases_por_prompt} · "
           f"merge cada {args.merge_cada or '∞'} fases")

    with puente.Puente(indice_pestana=indice) as p:
        for intento in range(1, 4):
            if p.parece_logueado():
                break
            avisar(f"[tab {indice}] arena.ai no parece listo; recargo ({intento}/3)")
            with contextlib.suppress(Exception):
                p.reiniciar_charla()
        else:
            avisar(f"[tab {indice}] arena.ai no responde; salgo")
            return

        avisar(f"[tab {indice}] trabajando en {p.descripcion_pestana()}")

        chat = {"foto": ramas.foto(slug) if slug else set(), "rama": "", "fases": 0}
        adoptar_sesion(chat, slug, indice)

        # Si no hay sesión que retomar, chat limpio: nunca escribir en uno viejo.
        if not chat["rama"]:
            with contextlib.suppress(Exception):
                p.nueva_charla()
        with contextlib.suppress(Exception):
            p.cerrar_modal()
        for linea in p.preparar_agente():
            avisar(f"[tab {indice}] agente: {linea}")

        cola = list(mia)
        total = len(mia)
        numero_lote = 0
        hechas = 0

        while cola:
            if STOP.exists():
                avisar(f"[tab {indice}] STOP detectado, salgo")
                break
            if args.max and resumen["hechas"] >= args.max:
                break

            candidatas = cola[: args.fases_por_prompt]
            cola = cola[len(candidatas):]
            reclamadas = [f for f in candidatas if reclamos.reclamar(_clave(f))]
            if not reclamadas:
                continue

            try:
                backlog.refrescar()
                lote = [f for f in reclamadas if backlog.estado_de(f["id"]) not in ("hecha", "bloqueada")]
                if not lote:
                    continue
                numero_lote += 1
                resultado = procesar_lote(p, args, backlog, lote, numero_lote, total, slug, chat, indice)
            except Exception as exc:  # noqa: BLE001
                avisar(f"[tab {indice}] lote reventó: {type(exc).__name__}; reinicio la pestaña")
                for fase in reclamadas:
                    backlog.marcar(fase["id"], "pendiente")
                resultado = {"hechas": [], "bloqueadas": [], "pendientes": list(reclamadas)}
                with contextlib.suppress(Exception):
                    p.reiniciar_charla()
                p.preparar_agente()
                chat = {"foto": ramas.foto(slug) if slug else set(), "rama": "", "fases": 0}
            finally:
                for fase in reclamadas:
                    reclamos.liberar(_clave(fase))
                with _CANDADO_ESTADO:
                    ESTADO.pop(indice, None)

            nuevas = resultado["hechas"]
            hechas += len(nuevas)
            chat["fases"] += len(nuevas)
            with candado:
                resumen["hechas"] += len(nuevas)
            guardar_sesion(slug, indice, chat)

            # Lo pendiente vuelve a la cola; si agotó intentos, se marca bloqueada
            # (antes se quedaba en `pendiente` para siempre y el bucle no cerraba).
            for fase in resultado["pendientes"]:
                if backlog.estado_de(fase["id"]) != "pendiente":
                    continue
                if backlog.intentos_de(fase["id"]) < args.max_intentos:
                    cola.append(fase)
                else:
                    backlog.marcar(fase["id"], "bloqueada",
                                   f"sin avance tras {args.max_intentos} intentos")
                    avisar(f"[tab {indice}] {fase['id']} bloqueada por falta de avance")

            avisar(
                f"[tab {indice}] {hechas}/{total} · sesión {chat['fases']}/{args.merge_cada or '∞'} fases · "
                f"cola {len(cola)} · lote {numero_lote}: {len(nuevas)} hechas"
            )

            # MERGE solo por checkpoint de sesión (2500 fases) o emergencia.
            if args.merge_cada and chat["fases"] >= args.merge_cada:
                avisar(f"[tab {indice}] checkpoint: {chat['fases']} fases en la sesión -> merge y chat nuevo")
                cerrar_ciclo(p, args, chat, "checkpoint", slug, "", indice)

            if args.pausa:
                time.sleep(args.pausa)


def main() -> int:
    global PROTOCOLO_TXT
    for flujo in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            flujo.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser("nube", description="Autonoma en la nube: lotes de fases, una sesión, un PR.")
    ap.add_argument("--fases", default=None)
    ap.add_argument("--repo", default=None)
    ap.add_argument("--branch", default=None)
    ap.add_argument("--cdp", default=None, help="URL CDP, p.ej. http://127.0.0.1:9222")
    ap.add_argument("--cerrar-extras", action=argparse.BooleanOptionalAction, default=None,
                    help="cerrar pestañas de arena sobrantes al arrancar (por defecto sí)")
    ap.add_argument("--pestana", type=int, default=0)
    ap.add_argument("--pestanas", type=int, default=1)
    ap.add_argument("--rango", default=None, help="p.ej. 900-1200")
    ap.add_argument("--max", type=int, default=0, help="tope de fases en esta ejecución (0 = sin tope)")
    ap.add_argument("--pausa", type=float, default=None)
    ap.add_argument("--fases-por-prompt", type=int, default=None, help="fases por lote (por defecto 500)")
    ap.add_argument("--merge-cada", type=int, default=None,
                    help="fases por sesión antes de fusionar el PR (por defecto 2500; 0 = solo emergencia)")
    ap.add_argument("--tope-lote", type=float, default=None, help="segundos mínimos por lote antes de escalar")
    ap.add_argument("--segundos-por-fase", type=float, default=None,
                    help="presupuesto de segundos por fase; el tope del lote escala con él")
    ap.add_argument("--reintentos-recarga", type=int, default=3)
    ap.add_argument("--reintentos-suaves", type=int, default=None)
    ap.add_argument("--recargas-max", type=int, default=None)
    ap.add_argument("--max-intentos", type=int, default=0)
    ap.add_argument("--empujones-max", type=int, default=0)
    ap.add_argument("--latido", type=int, default=0)
    ap.add_argument("--minutos-reclamo", type=int, default=0)
    ap.add_argument("--una-instancia", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--mostrar-rama", action=argparse.BooleanOptionalAction, default=None)
    ap.add_argument("--metodo-merge", default="", choices=("", "squash", "merge", "rebase"))
    ap.add_argument("--github", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--barrer", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--resumen", action="store_true")
    ap.add_argument("--reiniciar", action="store_true")
    args = ap.parse_args()

    args.sin_github = not args.github
    if args.fases_por_prompt is None:
        args.fases_por_prompt = max(1, int(puente.CFG.get("fases_por_prompt", 500) or 500))
    if args.merge_cada is None:
        args.merge_cada = int(puente.CFG.get("merge_cada", 2500) or 0)
    if args.tope_lote is None:
        args.tope_lote = float(puente.CFG.get("timeout_lote_segundos", 43200) or 43200)
    if args.segundos_por_fase is None:
        args.segundos_por_fase = float(puente.CFG.get("segundos_por_fase", 12) or 12)
    if args.pausa is None:
        args.pausa = float(puente.CFG.get("pausa", 2.0) or 0.0)
    if not args.max_intentos:
        args.max_intentos = int(puente.CFG.get("max_intentos", 3) or 3)
    if not args.empujones_max:
        args.empujones_max = int(puente.CFG.get("empujones_max", 2) or 2)
    if not args.latido:
        args.latido = int(puente.CFG.get("latido_segundos", 30) or 30)
    if not args.minutos_reclamo:
        args.minutos_reclamo = int(puente.CFG.get("minutos_reclamo", 60) or 60)
    if args.reintentos_suaves is None:
        args.reintentos_suaves = int(puente.CFG.get("reintentos_suaves", 2) or 2)
    if args.recargas_max is None:
        args.recargas_max = int(puente.CFG.get("recargas_max", 1) or 1)
    if args.mostrar_rama is None:
        args.mostrar_rama = bool(puente.CFG.get("prompt_mostrar_rama", True))

    os.environ["AUTONOMA_MODO"] = "nube"

    ruta = Path(args.fases).expanduser() if args.fases else elegir_fases(AQUI.parent / "proyecto", None, nube=True)
    if not ruta.is_file():
        avisar(f"[nube] no encuentro el backlog: {ruta}")
        return 2

    backlog = Backlog(ruta)
    if args.reiniciar:
        backlog.reiniciar()
        avisar("[nube] estado reiniciado")
        return 0

    repo, rama = _leer_remoto(args)
    slug = _slug(args) if repo else ""

    if args.resumen:
        print(f"backlog   : {ruta}")
        print(f"estado    : {backlog.estado_ruta}")
        print(f"resumen   : {backlog.resumen()}")
        print(f"pendientes: {len(backlog.pendientes())}")
        print(f"repo      : {repo or '(vacío)'} · token github: {'sí' if ramas.hay_token() else 'no'}")
        print(f"lotes     : {args.fases_por_prompt} fases por prompt · merge cada {args.merge_cada or '∞'} fases")
        print(f"tope lote : {int(args.tope_lote)}s + {args.segundos_por_fase}s/fase · "
              f"suaves {args.reintentos_suaves} · recargas {args.recargas_max}")
        print(f"navegador : {puente.CFG.get('cdp')} · cerrar pestañas sobrantes: "
              f"{puente.CFG.get('cerrar_pestanas_extras')}")
        if slug and ramas.hay_token():
            for nombre in ramas.ramas_de_trabajo(slug):
                pr = ramas.pr_de_rama(slug, nombre)
                print(f"  rama viva: {nombre} -> {'PR #%s' % pr['number'] if pr else 'sin PR'}")
        return 0

    if not repo:
        avisar("[nube] falta el remoto: usa --repo owner/repo o crea REPO.txt")
        return 2

    if not ramas.hay_token():
        avisar("[nube] AVISO: sin GITHUB_TOKEN no hay merge ni borrado de ramas; "
               "crea arena/credenciales.txt con `GITHUB_TOKEN=ghp_...`")

    candado_instancia = None
    if args.una_instancia:
        candado_instancia = _tomar_instancia(slug)
        if candado_instancia is None:
            avisar(f"[nube] ya hay una instancia viva de nube.py para {slug}. Usa --no-una-instancia para forzar.")
            return 3
        avisar(f"[nube] instancia única: pid {os.getpid()} · {candado_instancia.name}")

    try:
        pendientes = _rango(backlog.pendientes(), args.rango)

        if args.barrer and slug and ramas.hay_token():
            informe = ramas.barrer(slug)
            avisar(f"[nube] barrido previo: {informe['fusionadas']}/{informe['revisadas']} ramas fusionadas y borradas")
            for linea in informe["fallidas"]:
                avisar(f"[nube]   [!] {linea}")

        puente.CFG.setdefault("agente", {})
        puente.CFG["agente"]["activo"] = True
        puente.CFG["agente"]["repositorio"] = repo
        puente.CFG["agente"]["branch"] = rama
        if args.metodo_merge:
            puente.CFG.setdefault("github", {})["metodo_merge"] = args.metodo_merge

        if args.cdp:
            puente.CFG["cdp"] = args.cdp
        if args.cerrar_extras is not None:
            puente.CFG["cerrar_pestanas_extras"] = bool(args.cerrar_extras)
        info = puente.preparar_navegador(args.pestanas)
        if not info["puerto"]:
            avisar(puente.guia_cdp())
            return 4
        avisar(
            f"[nube] navegador listo (puerto {info['puerto']}) · pestañas de arena: {info['arena']} "
            f"(creadas {info['creadas']}, cerradas {info['cerradas']}) · trabajaré en la pestaña 0"
        )

        PROTOCOLO_TXT = PROTOCOLO.read_text(encoding="utf-8") if PROTOCOLO.is_file() else ""
        if not PROTOCOLO_TXT:
            avisar("[nube] aviso: falta protocolo_nube.md, se envia sin preambulo")

        reclamos = Reclamos(ruta)
        limpiados = reclamos.limpiar(args.minutos_reclamo)
        if limpiados:
            avisar(f"[nube] reclamos huérfanos limpiados: {limpiados}")

        avisar(
            f"[nube] backlog={ruta.name} · repo={repo} ({rama}) · pendientes={len(pendientes)} · "
            f"github={'sí' if slug and ramas.hay_token() else 'no'} · "
            f"lotes={args.fases_por_prompt} · merge_cada={args.merge_cada or '∞'} · "
            f"tope_lote={int(args.tope_lote)}s +{args.segundos_por_fase}s/fase · latido={args.latido}s"
        )

        if not pendientes:
            avisar("[nube] nada pendiente")
            return 0

        resumen = {"hechas": 0}
        candado = threading.Lock()

        parar = threading.Event()
        threading.Thread(target=latir, args=(args, parar), daemon=True).start()

        if args.pestanas > 1:
            hilos = [
                threading.Thread(
                    target=trabajador,
                    args=(i, backlog, reclamos, pendientes, args, resumen, candado, slug),
                    daemon=True,
                )
                for i in range(args.pestanas)
            ]
            for hilo in hilos:
                hilo.start()
            for hilo in hilos:
                hilo.join()
        else:
            trabajador(args.pestana, backlog, reclamos, pendientes, args, resumen, candado, slug)

        parar.set()
        avisar(f"[nube] terminado. hechas={resumen['hechas']} · {backlog.resumen()}")
        return 0
    finally:
        if candado_instancia is not None:
            with contextlib.suppress(OSError):
                candado_instancia.unlink()


if __name__ == "__main__":
    sys.exit(main())