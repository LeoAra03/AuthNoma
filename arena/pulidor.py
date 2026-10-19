"""Pulido opcional de prompts con el mejorador de promptsloth.com.

Se activa con `"pulir_prompts": true` en config.json. No necesita clave ni cuenta: se
llama al mismo endpoint que usa la herramienta gratuita de la web.

    POST https://promptsloth.com/api/demo-improve
    {"text": ..., "action": "improve", "search": false, "think": false,
     "customPrompt": ..., "context": {...}}
    -> {"improvedPrompt": "..."}

Si algo falla, se devuelve el prompt tal cual: pulir nunca rompe una fase.

Ajustes en config.json:
    pulir_prompts            true/false
    promptsloth_url          endpoint (por defecto el de la web)
    promptsloth_instruccion  texto que se manda como customPrompt
                             ("" = deja el mejorador genérico del sitio)
    pulir_pensar             true = el modelo razona antes (mejor, más lento)
    pulir_buscar             true = busca en la web antes de reescribir
    pulir_timeout            segundos
    pulir_min_caracteres     por debajo de esto no se pulir
    pulir_max_caracteres     por encima de esto no se pulir

    py arena\\pulidor.py --probar             prueba con un prompt de ejemplo
    py arena\\pulidor.py --probar "mi texto"  prueba con el texto que le pases
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
_CFG = json.loads((AQUI / "config.json").read_text(encoding="utf-8"))

_URL_POR_DEFECTO = "https://promptsloth.com/api/demo-improve"
_PAGINA = "https://promptsloth.com/free-tools/ai-prompt-enhancer"
_CONTEXTO = {"slug": "ai-prompt-enhancer", "category": "General LLM", "path": "/free-tools/ai-prompt-enhancer"}

_AGENTE = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Va como `customPrompt`: define la personalidad del mejorador. Con esto el resultado
# conserva la estructura del bot (bloques ```path=, marcas @@FASE_OK@@ / @@BLOQUEADO@@)
# en vez de que el mejorador genérico la reescriba a su criterio.
_INSTRUCCION = (
    "Eres un ingeniero de prompts. Recibirás un prompt completo que se enviará a otro "
    "modelo. Devuélvelo reescrito, más claro y preciso, en el MISMO idioma, conservando "
    "todas las reglas de formato, los bloques de ejemplo y las marcas exactas "
    "(@@FASE_OK@@ / @@BLOQUEADO: ...@@).\n"
    "Reglas:\n"
    "- No resumas: el prompt reescrito debe seguir siendo autosuficiente.\n"
    "- No añadas preámbulos ni comentarios.\n"
    "- No envuelvas la respuesta en cercas de código.\n"
    "- Si algo ya está bien, déjalo igual.\n"
    "Responde SÓLO con el prompt reescrito."
)

_ARCHIVOS_CLAVE = ("credenciales.txt", ".env")
_ESPERA_ENTRE_INTENTOS = 3.0

_abridor: urllib.request.OpenerDirector | None = None


def _texto_utf8() -> None:
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def _clave() -> str:
    """Opcional: si algun dia el endpoint pide credencial, ya se manda."""
    valor = (os.environ.get("PROMPTSLOTH_API_KEY") or "").strip()
    if valor and "pega-aqui" not in valor:
        return valor
    for carpeta in (AQUI, AQUI.parent):
        for nombre in _ARCHIVOS_CLAVE:
            ruta = carpeta / nombre
            if not ruta.is_file():
                continue
            for linea in ruta.read_text(encoding="utf-8", errors="replace").splitlines():
                linea = linea.strip()
                if not linea or linea.startswith(("#", ";", "//")):
                    continue
                clave, _, val = linea.partition("=")
                if clave.strip().upper() in {"PROMPTSLOTH_API_KEY", "PROMPTSLOTH_KEY"} and val.strip():
                    return val.strip().strip("\"'")
    return ""


def _opener() -> urllib.request.OpenerDirector:
    """Un solo abridor con cookies: si el sitio deja sesión, se reutiliza entre llamadas."""
    global _abridor
    if _abridor is None:
        _abridor = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
    return _abridor


def activado() -> bool:
    """Para que quien llama pueda preguntar sin repetir la lectura del config."""
    return bool(_CFG.get("pulir_prompts"))


def _instruccion() -> str:
    propia = str(_CFG.get("promptsloth_instruccion") or "").strip()
    return propia or _INSTRUCCION


def _url() -> str:
    return str(_CFG.get("promptsloth_url") or _URL_POR_DEFECTO).strip() or _URL_POR_DEFECTO


def _aceptable(entrada: str, salida: str) -> bool:
    """El resultado sólo se acepta si conserva lo irrenunciable del bot."""
    if len(salida) < 200:
        return False
    if len(salida) < len(entrada) * 0.5:
        return False
    if "@@FASE_OK@@" in entrada and "@@FASE_OK@@" not in salida:
        return False
    if "@@BLOQUEADO" in entrada and "@@BLOQUEADO" not in salida:
        return False
    if "path=" in entrada and "path=" not in salida:
        return False
    return True


def _limpiar(salida: str) -> str:
    """Quita el preámbulo y las cercas que a veces añade el modelo."""
    texto = salida.strip()
    for prefijo in ("Prompt mejorado:", "Improved prompt:", "Prompt reescrito:"):
        if texto.lower().startswith(prefijo.lower()):
            texto = texto[len(prefijo):].strip()
    if texto.startswith("```") and texto.endswith("```") and texto.count("```") == 2:
        lineas = texto.splitlines()
        texto = "\n".join(lineas[1:-1]).strip()
    return texto


def _cuerpo(texto: str) -> dict:
    return {
        "text": texto,
        "action": "improve",
        "search": bool(_CFG.get("pulir_buscar", False)),
        "think": bool(_CFG.get("pulir_pensar", False)),
        "customPrompt": _instruccion(),
        "context": dict(_CONTEXTO),
    }


def _pedir(texto: str, intentos: int = 2) -> str:
    """Devuelve el prompt mejorado, o "" si no se pudo."""
    cuerpo = json.dumps(_cuerpo(texto)).encode("utf-8")
    cabeceras = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://promptsloth.com",
        "Referer": _PAGINA,
        "User-Agent": _AGENTE,
    }
    clave = _clave()
    if clave:
        cabeceras["Authorization"] = f"Bearer {clave}"

    espera = float(_CFG.get("pulir_timeout", 90))
    for intento in range(1, intentos + 1):
        peticion = urllib.request.Request(_url(), data=cuerpo, headers=cabeceras, method="POST")
        try:
            with _opener().open(peticion, timeout=espera) as respuesta:
                datos = json.loads(respuesta.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            cola = exc.read().decode("utf-8", "replace")[:200]
            print(f"[pulidor] HTTP {exc.code}: {cola}", flush=True)
            if exc.code in (429, 402) and intento < intentos:
                time.sleep(_ESPERA_ENTRE_INTENTOS * intento)
                continue
            return ""
        except Exception as exc:  # noqa: BLE001
            print(f"[pulidor] {type(exc).__name__}: {exc}", flush=True)
            if intento < intentos:
                time.sleep(_ESPERA_ENTRE_INTENTOS * intento)
                continue
            return ""

        if isinstance(datos, dict) and datos.get("error"):
            print(f"[pulidor] el sitio dice: {datos['error']}", flush=True)
            return ""
        salida = str((datos or {}).get("improvedPrompt") or "").strip()
        return _limpiar(salida) if salida else ""
    return ""


def pulir(texto: str) -> str:
    """Reescribe el prompt. Nunca lanza: si algo falla devuelve el original."""
    original = str(texto or "")
    if not original.strip():
        return original
    if not activado():
        return original

    minimo = int(_CFG.get("pulir_min_caracteres", 400) or 0)
    maximo = int(_CFG.get("pulir_max_caracteres", 12000) or 0)
    if len(original) < minimo or (maximo and len(original) > maximo):
        return original

    salida = _pedir(original)
    if not salida:
        return original
    if not _aceptable(original, salida):
        print("[pulidor] el resultado no conserva el contrato; me quedo con el original", flush=True)
        return original
    return salida


# Alias por si algún llamador usa otro nombre.
pulir_prompt = pulir
mejorar = pulir


def _main() -> int:
    _texto_utf8()
    ap = argparse.ArgumentParser("pulidor", description="Prueba el mejorador de prompts de promptsloth.com.")
    ap.add_argument("--probar", nargs="?", const="__EJEMPLO__", default=None,
                    help="prueba con este texto (sin valor: usa un ejemplo)")
    ap.add_argument("--pensar", action="store_true", help="fuerza pulir_pensar = true")
    args = ap.parse_args()

    if args.pensar:
        _CFG["pulir_pensar"] = True

    entrada = args.probar
    if entrada is None or entrada == "__EJEMPLO__":
        entrada = (
            "===== FASE 42/900 =====\n"
            "Auditar que la extracción de GBC no invente terreno: si el bit de colisión no está, "
            "la celda se trata como libre y se documenta.\n\n"
            "Trabaja sobre el repositorio conectado, haz commit y termina con @@FASE_OK@@."
        )

    print(f"endpoint   : {_url()}")
    print(f"activado   : {activado()}   pensar: {bool(_CFG.get('pulir_pensar'))}")
    print(f"instruccion: {'propia' if str(_CFG.get('promptsloth_instruccion') or '').strip() else 'la del sitio'}")
    print(f"\n--- ANTES ({len(entrada)} chars) ---\n{entrada}\n")

    arranque = time.time()
    salida = pulir(entrada)
    segundos = time.time() - arranque

    if salida == entrada:
        print(f"--- SIN CAMBIOS ({segundos:.1f}s) --- (revisa el motivo arriba)")
        return 1
    print(f"--- DESPUES ({len(salida)} chars, {segundos:.1f}s) ---\n{salida}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())