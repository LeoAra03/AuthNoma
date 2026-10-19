"""Conduce una pestaña de arena.ai por CDP. Sin tocar el disco.

Endurecido para LOTES de 200 fases y para pestañas lentas:

  * `_leer()` distingue "no pude leer" de "leí y está vacío": una pestaña congelada ya no
    se confunde con una respuesta terminada ni provoca empujones falsos.
  * La espera se ancla en la CABECERA ÚNICA del envío. Si la virtualización del DOM se la
    lleva, cae a conteo de terminadores contra la foto previa al envío.
  * El botón de parar manda: mientras siga visible, la espera NO declara "sin_marca" por
    mucho que el texto no cambie. Eso evita interrumpir un lote largo.
  * `enviar()` no mata al agente: le da un presupuesto amplio antes de pulsar parar.
  * El reloj de timeout NO corre mientras la pestaña no responde.
  * El prompt se escribe POR TROZOS verificados: un insert_text de 60.000 caracteres
    tarda minutos y parece colgado.
  * La conexión CDP reintenta y, si hace falta, levanta Brave (ver navegador.py).
  * Las pestañas de arena se eligen en ORDEN ESTABLE y se ajustan al número pedido.
  * La config se carga por ajustes.py: un config.json recortado no rompe nada.
"""

from __future__ import annotations

import contextlib
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable

from playwright.sync_api import sync_playwright

AQUI = Path(__file__).resolve().parent
if str(AQUI) not in sys.path:
    sys.path.insert(0, str(AQUI))

import ajustes  # noqa: E402
import navegador  # noqa: E402

CFG: dict[str, Any] = ajustes.cargar()

MARCA_OK = "@@FASE_OK@@"
MARCAS_BLOQUEO = ("@@BLOQUEADO:", "@@BLOQUEADO")

_COLA = 3000
_MIN_RESPUESTA = 5
_ESPERA_ECO = 25.0
_ESPERA_ENVIO = 20.0
_ESPERA_ENVIO_TOTAL = 30.0
_POLL = 2.0
_INTENTOS_CDP = 3

_RE_MODAL = re.compile(
    r"continuar trabajando|continue working|esta tarea fue exitosa|"
    r"was this task successful|task successful",
    re.I,
)
_CLAVES_URL = {"agent", "chat", "c", "es", "en", "arena", "arena.ai", "https:", "http:"}


# --------------------------------------------------------------- navegador
def _pestanas_arena(ctx: Any) -> list[Any]:
    """Pestañas de arena en ORDEN ESTABLE: primero las de /agent, luego por URL.

    El orden importa: `ctx.pages` no es estable entre arranques, así que el índice de
    pestaña se resuelve siempre contra esta lista ordenada.
    """
    paginas: list[Any] = []
    for pagina in ctx.pages:
        try:
            if pagina.is_closed():
                continue
            url = (pagina.url or "").lower()
        except Exception:  # noqa: BLE001
            continue
        if "arena" in url:
            paginas.append(pagina)
    paginas.sort(key=lambda p: (0 if "/agent" in (p.url or "").lower() else 1, (p.url or "")))
    return paginas


def _ajustar_pestanas(cantidad: int) -> dict:
    """Deja EXACTAMENTE `cantidad` pestañas de arena (crea las que falten, cierra las que sobren)."""
    informe = {"arena": 0, "creadas": 0, "cerradas": 0}
    with sync_playwright() as pw:
        nav = pw.chromium.connect_over_cdp(CFG["cdp"], timeout=15000)
        if not nav.contexts:
            raise RuntimeError("Brave respondió pero no tiene contextos: ¿se está cerrando?")
        ctx = nav.contexts[0]
        paginas = _pestanas_arena(ctx)
        informe["arena"] = len(paginas)

        if CFG.get("cerrar_pestanas_extras", True):
            for sobrante in paginas[cantidad:]:
                with contextlib.suppress(Exception):
                    sobrante.close()
                    informe["cerradas"] += 1
            paginas = paginas[:cantidad]

        while len(paginas) < cantidad:
            nueva = ctx.new_page()
            with contextlib.suppress(Exception):
                nueva.goto(CFG["url_arena"], wait_until="domcontentloaded")
            paginas.append(nueva)
            informe["creadas"] += 1

        informe["arena"] = len(paginas)
    return informe


def preparar_navegador(pestanas: int = 1) -> dict:
    """Deja Brave escuchando en CDP con el número justo de pestañas.

    Devuelve {"puerto": int, "arena": int, "creadas": int, "cerradas": int}.
    puerto = 0 si no lo consigue.
    """
    informe = {"puerto": 0, "arena": 0, "creadas": 0, "cerradas": 0}
    puerto = navegador.esperar_cdp()
    if not puerto:
        return informe
    CFG["cdp"] = f"http://127.0.0.1:{puerto}"
    informe["puerto"] = puerto
    with contextlib.suppress(Exception):
        informe.update(_ajustar_pestanas(max(1, int(pestanas))))
    return informe


def guia_cdp() -> str:
    return navegador.guia()


def abrir_pestanas(cantidad: int) -> int:
    puerto = navegador.esperar_cdp(lanzar=False)
    if not puerto:
        raise RuntimeError(navegador.guia())
    CFG["cdp"] = f"http://127.0.0.1:{puerto}"
    return int(_ajustar_pestanas(max(1, cantidad))["arena"])


def _cfg(clave: str, defecto):
    valor = CFG.get(clave, defecto)
    return defecto if valor is None else valor


JS_TEXTO = """
() => {
  const main = document.querySelector('main');
  const nodo = (main && (main.innerText || '').trim().length > 40) ? main : document.body;
  return nodo ? (nodo.innerText || '') : '';
}
"""

JS_SCROLL_FIN = """
() => {
  const nodos = Array.from(document.querySelectorAll('main, div, section'))
    .filter(el => {
      const st = getComputedStyle(el);
      return (st.overflowY === 'auto' || st.overflowY === 'scroll')
             && el.scrollHeight > el.clientHeight + 40;
    });
  if (!nodos.length) return false;
  nodos.sort((a, b) => b.scrollHeight - a.scrollHeight);
  const el = nodos[0];
  el.scrollTop = el.scrollHeight;
  return true;
}
"""

JS_HAY_MODAL = """
() => {
  const re = /continuar trabajando|continue working|esta tarea fue exitosa|was this task successful|task successful/i;
  const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  if (Array.from(document.querySelectorAll('button')).some(b => re.test((b.innerText || '').trim()) && vis(b))) return true;
  return Array.from(document.querySelectorAll('[role=dialog], [role=alertdialog], [data-state=open]'))
    .some(d => vis(d) && re.test(d.innerText || ''));
}
"""

JS_CERRAR_MODAL = """
() => {
  const norm = s => (s || '').normalize('NFKD').replace(/[\\u0300-\\u036f]/g, '').toLowerCase().trim();
  const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const bs = Array.from(document.querySelectorAll('button, [role=button]')).filter(vis);
  const busca = (re) => bs.find(b => re.test(norm(b.innerText)) || re.test(norm(b.getAttribute('aria-label') || '')));
  let b = busca(/continuar trabajando|continue working/);
  if (!b) b = busca(/^(si|sí|yes)$/);
  if (!b) return false;
  b.click();
  return true;
}
"""

JS_NORM = """
const norm = (s) => (s || '').normalize('NFKD').replace(/[\\u0300-\\u036f]/g, '').toLowerCase().trim();
"""

JS_CLIC_TEXTO = (
    "(texto) => {"
    + JS_NORM
    + """
  const t = norm(texto);
  if (!t) return false;
  const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const sel = 'button, [role=button], [role=option], [role=menuitem], [role=tab], a, li, span, div';
  const cands = Array.from(document.querySelectorAll(sel))
    .filter(el => vis(el) && norm(el.innerText).includes(t));
  if (!cands.length) return false;
  cands.sort((a, b) => (a.innerText || '').length - (b.innerText || '').length);
  const el = cands[0];
  const objetivo = el.closest('button, [role=button], [role=option], [role=menuitem], [role=tab], a, li') || el;
  objetivo.click();
  return true;
}
"""
)

JS_HAY_TEXTO = (
    "(texto) => {"
    + JS_NORM
    + """
  const t = norm(texto);
  if (!t) return false;
  return Array.from(document.querySelectorAll('button, [role=button], [role=option], li, div, span, p'))
    .some(el => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && norm(el.innerText).includes(t);
    });
}
"""
)

JS_MENU_CHAT = """
() => {
  const norm = s => (s || '').normalize('NFKD').replace(/[\\u0300-\\u036f]/g, '').toLowerCase().trim();
  const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const bs = Array.from(document.querySelectorAll('button, [role=button]')).filter(vis);
  let b = bs.find(x => /more options|mas opciones|opciones|options/.test(
    norm(x.getAttribute('aria-label') || x.title || '')));
  if (!b) b = bs.find(x => /more options/.test(norm(x.innerText || '')));
  if (!b) {
    const cab = document.querySelector('header') || document.body;
    const hs = Array.from(cab.querySelectorAll('button')).filter(vis);
    b = hs[hs.length - 1];
  }
  if (!b) return false;
  b.click();
  return true;
}
"""

JS_ARCHIVAR = """
() => {
  const norm = s => (s || '').normalize('NFKD').replace(/[\\u0300-\\u036f]/g, '').toLowerCase().trim();
  const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const items = Array.from(document.querySelectorAll('[role=menuitem], [role=option], button, li, div, span'))
    .filter(el => vis(el) && ['archive', 'archivar'].includes(norm(el.innerText)));
  if (!items.length) return false;
  items.sort((a, b) => (a.innerText || '').length - (b.innerText || '').length);
  const el = items[0];
  const objetivo = el.closest('[role=menuitem], [role=option], button, li') || el;
  objetivo.click();
  return true;
}
"""

JS_LISTAR = """
() => {
  const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const sel = 'button, [role=button], [role=option], input, textarea, [contenteditable=true], a';
  const out = [];
  for (const el of document.querySelectorAll(sel)) {
    if (!vis(el)) continue;
    const txt = (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('placeholder') || '')
      .trim().replace(/\\s+/g, ' ');
    if (!txt) continue;
    out.push({ tag: el.tagName.toLowerCase(), txt: txt.slice(0, 70) });
  }
  const vistos = new Set();
  return out.filter(o => { const k = o.tag + '|' + o.txt; if (vistos.has(k)) return false; vistos.add(k); return true; });
}
"""

JS_HAY_FOCO_CAMPO = """
() => {
  const a = document.activeElement;
  if (!a) return false;
  const t = a.tagName.toLowerCase();
  return t === 'input' || t === 'textarea' || a.isContentEditable === true;
}
"""

JS_PARAR = """
() => {
  const re = /^(stop|detener|parar|stop generating)$/i;
  const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const b = Array.from(document.querySelectorAll('button'))
    .find(x => vis(x) && (re.test((x.innerText || '').trim())
      || re.test((x.getAttribute('aria-label') || '').trim())));
  if (!b) return false;
  b.click();
  return true;
}
"""

JS_HAY_PARAR = """
() => {
  const re = /^(stop|detener|parar|stop generating)$/i;
  const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  return Array.from(document.querySelectorAll('button'))
    .some(x => vis(x) && (re.test((x.innerText || '').trim())
      || re.test((x.getAttribute('aria-label') || '').trim())));
}
"""


class Puente:
    """Conecta con el Brave que ya corre y conduce UNA pestaña. No la cierra al salir."""

    def __init__(self, indice_pestana: int | None = None) -> None:
        self._pw: Any = None
        self._navegador: Any = None
        self.pagina: Any = None
        self._indice = indice_pestana
        self.lecturas_fallidas = 0

    def __enter__(self) -> "Puente":
        self._pw = sync_playwright().start()

        # Un solo intento no basta: Brave puede tardar en abrir el WebSocket.
        ultimo: Exception | None = None
        for _ in range(1, _INTENTOS_CDP + 1):
            try:
                self._navegador = self._pw.chromium.connect_over_cdp(CFG["cdp"], timeout=15000)
                break
            except Exception as exc:  # noqa: BLE001
                ultimo = exc
                # Si el puerto se cayó entre medias, lo reintentamos levantar.
                with contextlib.suppress(Exception):
                    navegador.esperar_cdp(tope=20)
                time.sleep(2)
        else:
            self._pw.stop()
            raise RuntimeError(
                f"{navegador.guia()}\n(último error: {type(ultimo).__name__}: {ultimo})"
            )

        if not self._navegador.contexts:
            self._pw.stop()
            raise RuntimeError("Brave respondió pero no tiene contextos: ¿se está cerrando?")
        ctx = self._navegador.contexts[0]

        self.pagina = self._buscar_pestana(ctx)
        if self.pagina is None:
            # Faltaba la pestaña: la creamos aquí en vez de reventar.
            self.pagina = ctx.new_page()
            with contextlib.suppress(Exception):
                self.pagina.goto(CFG["url_arena"], wait_until="domcontentloaded")
            self.pagina.wait_for_timeout(1500)

        if CFG.get("traer_al_frente", True):
            with contextlib.suppress(Exception):
                self.pagina.bring_to_front()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._pw is not None:
            with contextlib.suppress(Exception):
                self._pw.stop()

    def _buscar_pestana(self, ctx: Any) -> Any:
        paginas = _pestanas_arena(ctx)
        if self._indice is not None:
            if 0 <= self._indice < len(paginas):
                return paginas[self._indice]
            return None
        for pagina in paginas:
            if "/agent" in (pagina.url or "").lower():
                return pagina
        return paginas[0] if paginas else None

    def descripcion_pestana(self) -> str:
        try:
            return f"pestaña {self._indice} · {self.pagina.url}"
        except Exception:  # noqa: BLE001
            return f"pestaña {self._indice}"

    # --------------------------------------------------------------- localizar
    def _selectores(self, clave: str) -> list[str]:
        valor = CFG.get(clave)
        if valor is None:
            anidado = CFG.get("selectores") or {}
            corto = clave[len("selector_"):] if clave.startswith("selector_") else clave
            valor = anidado.get(corto)
        if not valor:
            return []
        return [valor] if isinstance(valor, str) else [str(item) for item in valor]

    def _localizar(self, clave: str, *, obligatorio: bool = True) -> Any:
        for selector in self._selectores(clave):
            loc = self.pagina.locator(selector)
            try:
                total = loc.count()
            except Exception:  # noqa: BLE001
                continue
            for indice in range(total - 1, -1, -1):
                item = loc.nth(indice)
                try:
                    if item.is_visible() and item.is_enabled():
                        return item
                except Exception:  # noqa: BLE001
                    continue
        if obligatorio:
            raise RuntimeError(
                f"no encuentro ningún selector de {clave}: {self._selectores(clave)}. Corre inspeccion.py"
            )
        return None

    # ------------------------------------------------------------ modal Sí/No
    def hay_modal(self) -> bool:
        try:
            return bool(self.pagina.evaluate(JS_HAY_MODAL))
        except Exception:  # noqa: BLE001
            return False

    def cerrar_modal(self) -> bool:
        if not self.hay_modal():
            return False
        try:
            if self.pagina.evaluate(JS_CERRAR_MODAL):
                self.pagina.wait_for_timeout(500)
                return True
        except Exception:  # noqa: BLE001
            pass
        try:
            loc = self.pagina.get_by_text(_RE_MODAL)
            for indice in range(loc.count() - 1, -1, -1):
                item = loc.nth(indice)
                if item.is_visible():
                    item.click()
                    self.pagina.wait_for_timeout(500)
                    return True
        except Exception:  # noqa: BLE001
            pass
        with contextlib.suppress(Exception):
            self.pagina.keyboard.press("Escape")
            self.pagina.wait_for_timeout(400)
            return True
        return False

    # ---------------------------------------------------- chat: id y ciclo de vida
    def chat_id(self) -> str:
        try:
            url = self.pagina.url or ""
        except Exception:  # noqa: BLE001
            return ""
        partes = [p for p in url.split("?")[0].split("/") if p]
        for parte in reversed(partes):
            if parte.lower() not in _CLAVES_URL and "." not in parte:
                return parte
        return ""

    def puede_escribir(self) -> bool:
        comp = self._localizar("selector_compositor", obligatorio=False)
        if comp is None:
            self.pagina.wait_for_timeout(800)
            comp = self._localizar("selector_compositor", obligatorio=False)
        return comp is not None

    def charla_limpia(self) -> bool:
        if not self.puede_escribir():
            return False
        return len(self.texto().strip()) < 400

    def parar(self) -> bool:
        try:
            return bool(self.pagina.evaluate(JS_PARAR))
        except Exception:  # noqa: BLE001
            return False

    def agente_libre(self) -> bool:
        """True si no hay botón de parar: el agente terminó y acepta envío.

        Es la ÚNICA señal de fondo fiable. Si no se puede leer, se asume libre.
        """
        try:
            return not bool(self.pagina.evaluate(JS_HAY_PARAR))
        except Exception:  # noqa: BLE001
            return True

    def _esperar_libre(self, tope: float = 30.0) -> bool:
        limite = time.time() + tope
        while time.time() < limite:
            if self.agente_libre():
                return True
            self.pagina.wait_for_timeout(600)
        return self.agente_libre()

    def descolgar(self, parar_agente: bool = True) -> bool:
        """Recuperación SUAVE: corta la carga y libera el compositor SIN salir del chat."""
        with contextlib.suppress(Exception):
            self.pagina.evaluate("window.stop()")
        if parar_agente:
            with contextlib.suppress(Exception):
                self.parar()
        with contextlib.suppress(Exception):
            self.pagina.keyboard.press("Escape")
        with contextlib.suppress(Exception):
            self.cerrar_modal()
        self.pagina.wait_for_timeout(700)
        return self.puede_escribir()

    def archivar_chat(self) -> bool:
        if not CFG.get("archivar_en_ui", True):
            return False
        for _ in range(1, 4):
            try:
                if not self.pagina.evaluate(JS_MENU_CHAT):
                    break
            except Exception:  # noqa: BLE001
                break
            self.pagina.wait_for_timeout(700)
            try:
                if self.pagina.evaluate(JS_ARCHIVAR):
                    self.pagina.wait_for_timeout(1300)
                    return True
            except Exception:  # noqa: BLE001
                pass
            with contextlib.suppress(Exception):
                self.pagina.keyboard.press("Escape")
            self.pagina.wait_for_timeout(600)
        return False

    def nueva_charla(self) -> bool:
        self.cerrar_modal()
        if self.charla_limpia():
            return True
        if CFG.get("nueva_charla_por_boton", True):
            for etiqueta in ("Nuevo chat", "New chat", "Nueva conversación", "New conversation"):
                if self.clic_texto(etiqueta) and self.charla_limpia():
                    self.cerrar_modal()
                    return True
        try:
            self.reiniciar_charla()
        except Exception:  # noqa: BLE001
            return False
        return self.puede_escribir()

    # ---------------------------------------------------------- agente: repo/rama
    def _resolver(self, texto: str) -> str:
        ag = CFG.get("agente") or {}
        repo = str(ag.get("repositorio") or "")
        return (
            str(texto)
            .replace("{{repositorio}}", repo)
            .replace("{{repo_busqueda}}", repo.split("/")[-1])
            .replace("{{branch}}", str(ag.get("branch") or CFG.get("branch") or ""))
        )

    def clic_texto(self, texto: str) -> bool:
        texto = self._resolver(texto).strip()
        if not texto:
            return False
        try:
            return bool(self.pagina.evaluate(JS_CLIC_TEXTO, texto))
        except Exception:  # noqa: BLE001
            return False

    def hay_texto(self, texto: str) -> bool:
        texto = self._resolver(texto).strip()
        if not texto:
            return False
        try:
            return bool(self.pagina.evaluate(JS_HAY_TEXTO, texto))
        except Exception:  # noqa: BLE001
            return False

    def listar_controles(self) -> list[dict[str, str]]:
        try:
            return list(self.pagina.evaluate(JS_LISTAR))
        except Exception:  # noqa: BLE001
            return []

    def _hay_foco_campo(self) -> bool:
        try:
            return bool(self.pagina.evaluate(JS_HAY_FOCO_CAMPO))
        except Exception:  # noqa: BLE001
            return False

    def _enfocar_campo(self) -> bool:
        for selector in ("input[type=search]", "input:not([type=hidden])", "[role=combobox]", "textarea"):
            loc = self.pagina.locator(selector)
            try:
                total = loc.count()
            except Exception:  # noqa: BLE001
                continue
            for indice in range(total - 1, -1, -1):
                item = loc.nth(indice)
                try:
                    if item.is_visible() and item.is_enabled():
                        item.click()
                        self.pagina.wait_for_timeout(150)
                        return True
                except Exception:  # noqa: BLE001
                    continue
        return False

    def repo_puesto(self) -> bool:
        """¿Se ve el repositorio elegido en la interfaz de Agent Mode?"""
        ag = CFG.get("agente") or {}
        repo = str(ag.get("repositorio") or "")
        if not repo:
            return True
        return self.hay_texto(repo.split("/")[-1]) or self.hay_texto(repo)

    def asegurar_repositorio(self, intentos: int = 2) -> bool:
        """Comprueba que el repo está elegido y, si no, intenta elegirlo.

        Los `agente.pasos` son frágiles: si la UI cambia un texto, el repo se queda sin
        elegir y el agente trabaja sobre lo que hubiera antes. Esta comprobación lo caza.
        """
        ag = CFG.get("agente") or {}
        repo = str(ag.get("repositorio") or "")
        if not ag.get("activo") or not repo:
            return True
        nombre = repo.split("/")[-1]
        for _ in range(max(1, intentos)):
            if self.repo_puesto():
                return True
            for etiqueta in ("Select a repository", "Seleccionar repositorio",
                             "Elegir repositorio", "Repositorio", "Repository"):
                if self.clic_texto(etiqueta):
                    self.pagina.wait_for_timeout(700)
                    break
            if not self._hay_foco_campo():
                self._enfocar_campo()
            with contextlib.suppress(Exception):
                self.pagina.keyboard.insert_text(nombre)
            self.pagina.wait_for_timeout(1400)
            self.clic_texto(nombre)
            self.pagina.wait_for_timeout(700)
            with contextlib.suppress(Exception):
                self.pagina.keyboard.press("Escape")
            if self.repo_puesto():
                return True
        return self.repo_puesto()

    def preparar_agente(self) -> list[str]:
        ag = CFG.get("agente") or {}
        if not ag.get("activo"):
            return []
        registro: list[str] = []
        for numero, paso in enumerate(ag.get("pasos") or [], 1):
            accion = str(paso.get("accion") or "").lower()
            try:
                if accion == "esperar":
                    self.pagina.wait_for_timeout(int(float(paso.get("segundos", 1)) * 1000))
                    registro.append(f"{numero}. esperar {paso.get('segundos', 1)}s")
                elif accion == "clic_texto":
                    texto = self._resolver(str(paso.get("texto", "")))
                    if not texto:
                        registro.append(f"{numero}. clic «{paso.get('texto')}» (vacío, salto)")
                        continue
                    hecho = self.clic_texto(texto)
                    registro.append(f"{numero}. clic «{texto}» {'ok' if hecho else 'NO'}")
                elif accion == "clic_selector":
                    loc = self.pagina.locator(str(paso.get("selector", "")))
                    if loc.count():
                        loc.last.click()
                        registro.append(f"{numero}. clic {paso.get('selector')} ok")
                    else:
                        registro.append(f"{numero}. clic {paso.get('selector')} NO")
                elif accion == "escribir":
                    texto = self._resolver(str(paso.get("texto", "")))
                    if not texto:
                        registro.append(f"{numero}. escribir (vacío, salto)")
                        continue
                    if not self._hay_foco_campo():
                        self._enfocar_campo()
                    self.pagina.keyboard.insert_text(texto)
                    registro.append(f"{numero}. escribir «{texto}»")
                elif accion == "tecla":
                    tecla = str(paso.get("tecla", "Escape"))
                    self.pagina.keyboard.press(tecla)
                    registro.append(f"{numero}. tecla {tecla}")
                elif accion == "esperar_texto":
                    texto = self._resolver(str(paso.get("texto", "")))
                    limite = time.time() + float(paso.get("segundos", 10))
                    while time.time() < limite and not self.hay_texto(texto):
                        self.pagina.wait_for_timeout(400)
                    registro.append(f"{numero}. esperar texto «{texto}»")
                else:
                    registro.append(f"{numero}. acción desconocida: {accion}")
            except Exception as exc:  # noqa: BLE001
                registro.append(f"{numero}. {accion} FALLÓ: {type(exc).__name__}")
        registro.append(f"repo puesto: {'sí' if self.asegurar_repositorio() else 'NO'}")
        return registro

    # ------------------------------------------------------------------ estado
    def _leer(self) -> tuple[str, bool]:
        """(texto, leible). `leible=False` significa que la pestaña no respondió."""
        try:
            valor = self.pagina.evaluate(JS_TEXTO)
        except Exception:  # noqa: BLE001
            self.lecturas_fallidas += 1
            return "", False
        if valor is None:
            self.lecturas_fallidas += 1
            return "", False
        texto = str(valor)
        if not texto.strip():
            self.lecturas_fallidas += 1
            return texto, False
        self.lecturas_fallidas = 0
        return texto, True

    def texto(self) -> str:
        try:
            return str(self.pagina.evaluate(JS_TEXTO) or "")
        except Exception:  # noqa: BLE001
            return ""

    def contar(self, marca: str) -> int:
        if not marca:
            return 0
        return self.texto().count(marca)

    def marcas(self) -> int:
        return self.texto().count(MARCA_OK)

    def scroll_fin(self) -> bool:
        try:
            return bool(self.pagina.evaluate(JS_SCROLL_FIN))
        except Exception:  # noqa: BLE001
            return False

    def _texto_compositor(self, comp: Any) -> str:
        for lectura in ("inner_text", "input_value"):
            try:
                valor = getattr(comp, lectura)()
            except Exception:  # noqa: BLE001
                continue
            if valor and str(valor).strip():
                return str(valor).strip()
        return ""

    def _largo_compositor(self, comp: Any) -> int:
        return len(self._texto_compositor(comp))

    def _limpiar_compositor(self, comp: Any) -> None:
        with contextlib.suppress(Exception):
            comp.click()
        with contextlib.suppress(Exception):
            self.pagina.keyboard.press("Control+A")
        with contextlib.suppress(Exception):
            self.pagina.keyboard.press("Backspace")
        self.pagina.wait_for_timeout(150)

    def compositor_con_texto(self) -> bool:
        comp = self._localizar("selector_compositor", obligatorio=False)
        if comp is None:
            return False
        return bool(self._texto_compositor(comp))

    def parece_logueado(self) -> bool:
        self.cerrar_modal()
        comp = self._localizar("selector_compositor", obligatorio=False)
        if comp is None:
            self.pagina.wait_for_timeout(1200)
            comp = self._localizar("selector_compositor", obligatorio=False)
        if comp is None:
            return False
        texto = self.texto().lower()
        return "captcha" not in texto and "verify you are human" not in texto

    def _esperar_compositor(self) -> Any:
        limite = time.time() + float(CFG.get("esperar_compositor_segundos", 30))
        while True:
            comp = self._localizar("selector_compositor", obligatorio=False)
            if comp is not None:
                return comp
            self.cerrar_modal()
            if time.time() >= limite:
                raise RuntimeError(
                    f"no encuentro ningún selector de selector_compositor: "
                    f"{self._selectores('selector_compositor')}. Corre inspeccion.py"
                )
            self.pagina.wait_for_timeout(500)

    # ------------------------------------------------------------------- enviar
    def _escribir(self, comp: Any, texto: str) -> int:
        """Mete el texto en el compositor. Devuelve cuántos caracteres quedaron puestos.

        Con prompts de decenas de miles de caracteres, UN SOLO insert_text puede tardar
        minutos: el editor re-renderiza en cada llamada y parece colgado. Aquí:
          1. se intenta un `fill()` por JS, que es instantáneo;
          2. si no cuaja, se escribe POR TROZOS, cada uno verificado y con progreso;
        así nunca se queda mudo y se ve por dónde va.
        """
        texto = texto.rstrip("\n")
        meta = len(texto)
        trozo = max(500, int(_cfg("trozo_escritura", 2000)))

        self._limpiar_compositor(comp)

        # 1) atajo por JS: un solo fill
        with contextlib.suppress(Exception):
            comp.fill(texto)
        self.pagina.wait_for_timeout(400)
        puesto = self._largo_compositor(comp)
        if puesto >= meta * 0.9:
            print(f"[puente] prompt escrito de golpe: {puesto} caracteres", flush=True)
            return puesto

        # 2) trozos, cada uno verificado
        print(
            f"[puente] fill dejó {puesto}/{meta}; escribo en trozos de {trozo} "
            f"({(meta + trozo - 1) // trozo} trozos)",
            flush=True,
        )
        self._limpiar_compositor(comp)
        with contextlib.suppress(Exception):
            comp.click()

        inicio = 0
        while inicio < meta:
            parte = texto[inicio:inicio + trozo]
            antes = self._largo_compositor(comp)
            for _intento in (1, 2, 3):
                with contextlib.suppress(Exception):
                    self.pagina.keyboard.insert_text(parte)
                self.pagina.wait_for_timeout(50)
                if self._largo_compositor(comp) > antes:
                    break
                with contextlib.suppress(Exception):
                    comp.click()
                    self.pagina.keyboard.press("End")
            else:
                print(f"[puente] aviso: el trozo desde {inicio} no entró", flush=True)
            inicio += trozo
            if inicio % (trozo * 10) == 0 or inicio >= meta:
                print(f"[puente] escritos {min(inicio, meta)}/{meta}", flush=True)

        puesto = self._largo_compositor(comp)
        if puesto and meta > 400 and puesto < meta * 0.85:
            print(
                f"[puente] AVISO: el compositor tiene {puesto} de {meta} caracteres. "
                f"arena podría estar recortando el prompt.",
                flush=True,
            )
        return puesto

    def enviar(self, texto: str, marca: str = "") -> str:
        """Escribe y envía. Nunca interrumpe a la ligera: espera a que el agente esté libre."""
        self.cerrar_modal()
        comp = self._esperar_compositor()
        presupuesto = float(_cfg("esperar_libre_segundos", 240))
        if not self._esperar_libre(presupuesto):
            if not self._esperar_libre(presupuesto):
                self.parar()
                self.pagina.wait_for_timeout(2500)
                comp = self._esperar_compositor()

        print(f"[puente] prompt: {len(texto)} caracteres · marca: {marca[:48]}", flush=True)
        if not self._escribir(comp, texto):
            raise RuntimeError("el compositor quedó vacío tras escribir el prompt")

        # Confirmación dura: la cabecera tiene que estar DENTRO del compositor.
        if marca and marca not in (self._texto_compositor(comp) or ""):
            print("[puente] la cabecera no está en el compositor; reescribo", flush=True)
            self._escribir(comp, texto)

        if CFG.get("enviar_con_enter", True):
            self.pagina.keyboard.press("Enter")
        if not self._confirmar_envio(comp):
            self._pulsar_enviar(comp)
            self._confirmar_envio(comp)
        return self._esperar_marca(marca)

    def _confirmar_envio(self, comp: Any) -> bool:
        limite = time.time() + _ESPERA_ENVIO
        while time.time() < limite:
            if not self._texto_compositor(comp):
                return True
            self.pagina.wait_for_timeout(250)
        return False

    def _pulsar_enviar(self, comp: Any) -> None:
        boton = self._localizar("selector_enviar", obligatorio=False)
        if boton is not None:
            try:
                boton.click()
                return
            except Exception:  # noqa: BLE001
                pass
        with contextlib.suppress(Exception):
            comp.press("Enter")

    def _esperar_marca(self, marca: str) -> str:
        if not marca:
            return self._esperar_eco()
        limite = time.time() + _ESPERA_ENVIO_TOTAL
        while time.time() < limite:
            if self.hay_texto(marca):
                return self.texto()
            self.pagina.wait_for_timeout(250)
        return self.texto()

    def _esperar_eco(self) -> str:
        base = self.texto()
        limite = time.time() + _ESPERA_ECO
        while time.time() < limite:
            actual = self.texto()
            if len(actual) > len(base) + 5:
                return actual
            self.pagina.wait_for_timeout(250)
        return self.texto()

    # ------------------------------------------------------------------ esperar
    @staticmethod
    def _tras_marca(marca: str, texto: str) -> tuple[str, bool]:
        """(texto posterior a la última cabecera, ¿se pudo anclar?)."""
        if not marca:
            return texto, False
        posicion = texto.rfind(marca)
        if posicion < 0:
            return texto, False
        return texto[posicion + len(marca):], True

    def esperar_fase(
        self,
        marca: str,
        tope: float = 0.0,
        tick: Callable[[float, float, int], None] | None = None,
        fin: str = MARCA_OK,
        parar_en_bloqueo: bool = True,
        fin_previos: int | None = None,
        peso: int = 1,
        cancelar: Callable[[], bool] | None = None,
    ) -> tuple[str, str]:
        """('ok' | 'bloqueado' | 'timeout' | 'sin_marca' | 'cancelado', respuesta).

        Endurecido:
          * `peso` = fases del lote: `sin_marca` escala con el trabajo encargado.
          * Mientras el botón de parar siga visible NO se declara `sin_marca`: el agente
            está trabajando aunque el texto no cambie (tool calls largas, lag de la página).
          * El reloj de timeout no corre mientras la pestaña no responde.
          * `fin_previos` = veces que ya aparecía el terminador antes de enviar.
        """
        if tope <= 0:
            tope = float(_cfg("timeout_lote_segundos", 43200))
        peso = max(1, int(peso))
        idle = float(_cfg("idle_segundos", 20))
        por_fase = float(_cfg("segundos_por_fase", 12))
        sin_marca_seg = max(float(_cfg("espera_marca_sin", 600)), peso * por_fase * 0.5)
        tras_modal = max(60.0, idle * 4)

        arranque = time.time()
        perdido = 0.0
        en_fallo = 0.0
        ultimo = ""
        ultimo_cambio = arranque
        ultimo_modal = 0.0
        hubo_modal = False
        polls = 0

        while True:
            ahora = time.time()

            if cancelar is not None:
                with contextlib.suppress(Exception):
                    if cancelar():
                        respuesta, _ = self._tras_marca(marca, ultimo)
                        return "cancelado", respuesta

            actual, leible = self._leer()
            if leible:
                if en_fallo:
                    perdido += ahora - en_fallo
                    en_fallo = 0.0
                if actual != ultimo:
                    ultimo, ultimo_cambio = actual, ahora
            elif not en_fallo:
                en_fallo = ahora

            respuesta, anclado = self._tras_marca(marca, ultimo)

            if tick is not None:
                with contextlib.suppress(Exception):
                    tick(
                        (ahora - perdido) - arranque,
                        (ahora - ultimo_cambio) if leible else -1.0,
                        len(respuesta.strip()),
                    )

            polls += 1
            if leible and polls % 15 == 0:
                self.scroll_fin()

            if not leible:
                if (ahora - perdido) - arranque > tope:
                    return "timeout", respuesta
                time.sleep(_POLL)
                continue

            if (
                CFG.get("cerrar_modal", True)
                and len(respuesta.strip()) > _MIN_RESPUESTA
                and (ahora - ultimo_modal) > 6
                and self.hay_modal()
            ):
                self.cerrar_modal()
                hubo_modal = True
                ultimo_modal = time.time()
                continue

            quieto = (ahora - ultimo_cambio) > idle
            if quieto and len(respuesta.strip()) > _MIN_RESPUESTA:
                cola = respuesta[-_COLA:]
                terminado = fin in cola
                if not terminado and not anclado and fin_previos is not None:
                    terminado = respuesta.count(fin) > fin_previos
                if terminado:
                    return "ok", respuesta
                if parar_en_bloqueo and any(m in cola for m in MARCAS_BLOQUEO):
                    return "bloqueado", respuesta
                if hubo_modal and (ahora - ultimo_cambio) > tras_modal:
                    return "ok", respuesta
                if (ahora - ultimo_cambio) > sin_marca_seg:
                    # El botón de parar es la verdad: si sigue ahí, el agente trabaja.
                    if self.agente_libre():
                        return "sin_marca", respuesta
                    if (ahora - ultimo_cambio) > sin_marca_seg * 3:
                        return "sin_marca", respuesta

            if (ahora - perdido) - arranque > tope:
                return "timeout", respuesta
            time.sleep(_POLL)

    def detener(self) -> bool:
        boton = self._localizar("selector_detener", obligatorio=False) or self._localizar(
            "selector_enviar", obligatorio=False
        )
        if boton is None:
            return False
        try:
            boton.click()
            return True
        except Exception:  # noqa: BLE001
            return False

    def reiniciar_charla(self) -> None:
        """Recarga DURA: navega otra vez a arena.ai."""
        with contextlib.suppress(Exception):
            self.pagina.evaluate("window.stop()")
        try:
            self.pagina.goto(CFG["url_arena"], wait_until="domcontentloaded", timeout=60000)
        except Exception:  # noqa: BLE001
            self.pagina.reload(wait_until="domcontentloaded", timeout=60000)
        self.pagina.wait_for_timeout(2000)
        self.cerrar_modal()
        self._esperar_compositor()