"""Carga la config SIN depender de que esté completa.

Un config.json recortado (o con una clave mal escrita) ya no puede tumbar la autónoma:
se parte de DEFECTOS y se superpone lo que exista en el archivo. Lo que falte, se rellena.
Lo que esté, MANDA.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

AQUI = Path(__file__).resolve().parent
CONFIG = AQUI / "config.json"
CONFIG_BAK = AQUI / "config.json.bak"

DEFECTOS: dict[str, Any] = {
    "cdp": "http://127.0.0.1:9222",
    "url_arena": "https://arena.ai/agent",
    "patron_pestana": "arena.ai",
    "traer_al_frente": True,
    "cerrar_pestanas_extras": True,

    "esperar_cdp_segundos": 90,
    "lanzar_brave": True,
    "perfil_brave": "",

    "metodo_envio": "enter",
    "enviar_con_enter": True,
    "cerrar_modal": True,
    "archivar_en_ui": True,
    "nueva_charla_por_boton": True,

    # 200 fases = ~26.000 caracteres por prompt. 12 lotes = 2400 fases = 1 sesión.
    "fases_por_prompt": 1,
    "merge_cada": 100,
    "trozo_escritura": 2000,

    "esperar_compositor_segundos": 30,
    "esperar_libre_segundos": 240,
    "idle_segundos": 20,
    "espera_marca_sin": 600,
    "segundos_por_fase": 12,
    "timeout_lote_segundos": 43200,
    "timeout_fase_segundos": 900,

    "empujones_max": 2,
    "reintentos_suaves": 2,
    "recargas_max": 1,
    "max_intentos": 3,

    "latido_segundos": 30,
    "minutos_reclamo": 60,
    "pausa": 2.0,
    "prompt_mostrar_rama": True,

    "agente": {
        "activo": True,
        "repositorio": "LeoAra03/Fire-ash-modifier",
        "branch": "main",
        "pasos": [
            {"accion": "esperar", "segundos": 2},
            {"accion": "esperar_texto", "texto": "Agent", "segundos": 10},
            {"accion": "clic_texto", "texto": "Select a repository", "opcional": True},
            {"accion": "clic_texto", "texto": "Repositorio", "opcional": True},
            {"accion": "clic_texto", "texto": "Repository", "opcional": True},
            {"accion": "esperar", "segundos": 1},
            {"accion": "clic_texto", "texto": "{{repositorio}}", "opcional": True},
            {"accion": "esperar", "segundos": 1},
            {"accion": "clic_texto", "texto": "{{repo_busqueda}}", "opcional": True},
            {"accion": "esperar", "segundos": 1},
            {"accion": "clic_texto", "texto": "{{branch}}", "opcional": True},
            {"accion": "esperar", "segundos": 0.5},
            {"accion": "tecla", "tecla": "Escape"},
        ],
    },

    "selectores": {
        "compositor": [
            "div[contenteditable='true']",
            "textarea",
            "form textarea",
            "[role='textbox']",
        ],
        "enviar": [
            "button[type='submit']",
            "button[aria-label*='Send']",
            "button[aria-label*='Enviar']",
        ],
        "detener": [
            "button[aria-label*='Stop']",
            "button[aria-label*='Detener']",
            "button[aria-label*='Parar']",
        ],
    },
    "selector_compositor": ["div[contenteditable='true']", "textarea"],
    "selector_enviar": [
        "button[aria-label='Send message']",
        "button[aria-label='Send']",
        "button[type='submit']",
    ],
    "selector_detener": ["button[aria-label='Stop']", "button[aria-label='Stop generating']"],

    "github": {
        "activo": True,
        "prefijo_rama": "autonoma/",
        "base": "main",
        "metodo_merge": "squash",
        "borrar_rama": True,
        "crear_pr_si_falta": True,
        "barrer_al_arrancar": True,
    },
    "ramas_protegidas": ["main", "master", "develop", "dev", "gh-pages", "staging"],

    "comandos_verificacion": [["npm", "test"]],
    "ntfy": "https://ntfy.sh/pokemod-leo-ara03",

    "pulir_prompts": False,
    "pulir_timeout": 90,
    "pulir_pensar": False,
    "pulir_buscar": False,
    "pulir_min_caracteres": 400,
    "pulir_max_caracteres": 12000,
    "promptsloth_url": "https://promptsloth.com/api/demo-improve",
    "promptsloth_instruccion": "",

    # 0 = sin tope. NUNCA se recorta a un rango estrecho.
    "max_caracteres_prompt": 0,
}

_ENTEROS = {
    "fases_por_prompt": (200, 1),
    "merge_cada": (2400, 0),
    "trozo_escritura": (2000, 500),
    "esperar_cdp_segundos": (90, 10),
    "esperar_compositor_segundos": (30, 5),
    "esperar_libre_segundos": (240, 10),
    "idle_segundos": (20, 5),
    "espera_marca_sin": (600, 30),
    "timeout_lote_segundos": (43200, 60),
    "timeout_fase_segundos": (900, 30),
    "empujones_max": (2, 0),
    "reintentos_suaves": (2, 0),
    "recargas_max": (1, 0),
    "max_intentos": (3, 1),
    "latido_segundos": (30, 5),
    "minutos_reclamo": (60, 1),
    "max_caracteres_prompt": (0, 0),
}
_FLOTANTES = {
    "segundos_por_fase": (12.0, 1.0),
    "pausa": (2.0, 0.0),
    "pulir_timeout": (90.0, 5.0),
}


def _fusion(base: dict, encima: dict) -> dict:
    """Fusión profunda: `encima` gana. Las listas se reemplazan enteras."""
    salida = copy.deepcopy(base)
    for clave, valor in (encima or {}).items():
        actual = salida.get(clave)
        if isinstance(actual, dict) and isinstance(valor, dict):
            salida[clave] = _fusion(actual, valor)
        elif valor is not None:
            salida[clave] = copy.deepcopy(valor)
    return salida


def _entero(valor: Any, defecto: int, minimo: int = 1) -> int:
    try:
        numero = int(float(str(valor).strip().replace(",", ".")))
    except Exception:  # noqa: BLE001
        return defecto
    return numero if numero >= minimo else defecto


def _flotante(valor: Any, defecto: float, minimo: float = 0.0) -> float:
    try:
        numero = float(str(valor).strip().replace(",", "."))
    except Exception:  # noqa: BLE001
        return defecto
    return numero if numero >= minimo else defecto


def _sano(cfg: dict) -> dict:
    for clave, (defecto, minimo) in _ENTEROS.items():
        cfg[clave] = _entero(cfg.get(clave), defecto, minimo)
    for clave, (defecto, minimo) in _FLOTANTES.items():
        cfg[clave] = _flotante(cfg.get(clave), defecto, minimo)
    if not isinstance(cfg.get("agente"), dict):
        cfg["agente"] = copy.deepcopy(DEFECTOS["agente"])
    if not isinstance(cfg.get("github"), dict):
        cfg["github"] = copy.deepcopy(DEFECTOS["github"])
    return cfg


def leer_crudo() -> dict:
    """Lee config.json tal cual. {} si no existe o no es un objeto."""
    if not CONFIG.is_file():
        return {}
    try:
        datos = json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return datos if isinstance(datos, dict) else {}


def cargar() -> dict:
    """Config lista para usar. Nunca lanza: si el archivo está roto, usa los defectos."""
    return _sano(_fusion(DEFECTOS, leer_crudo()))


if __name__ == "__main__":
    import json as _json

    print(_json.dumps(cargar(), indent=2, ensure_ascii=False))