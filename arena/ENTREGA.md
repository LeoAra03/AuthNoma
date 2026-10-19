\# Entrega — bot Autonoma (arena/)



\## Que es

Conduce tu propio Brave (por CDP, sin tocar tu sesion) hacia arena.ai y ejecuta

`proyecto/fases.jsonl` fase a fase: envia el prompt, espera `@@FASE\_OK@@`, lee los

bloques de archivo, los escribe, corre las verificaciones y hace commit.



\## Requisitos

\- Windows + Python 3.10 o superior (`py`) y `pip install playwright`

\- Brave con depuracion remota y sesion iniciada en arena.ai

\- El repo con git inicializado



\## Uso

1\. Doble clic en `arrancar.bat`, o a mano:

&#x20;  - Brave: `brave.exe --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\\AutonomaBrave"`

&#x20;  - `py arena\\verificar.py`   (debe terminar en LISTO)

&#x20;  - `py arena\\orquestador.py`

2\. Para que se relance solo si se cae: `py arena\\vigilante.py`



\## Archivos

| Archivo | Para que |

|---|---|

| config.json | CDP, selectores, tiempos, ntfy |

| puente.py | escribe en el compositor y envia con Enter; espera @@FASE\_OK@@ |

| contrato.py | lee los bloques ```lang path=ruta y los aplica |

| fases.py | lee y escribe proyecto/fases.jsonl |

| orquestador.py | bucle de fases, reintentos, verificacion, commit |

| vigilante.py | relanza el orquestador si se cae |

| notificar.py | avisos por ntfy (opcional) |

| verificar.py | comprobacion previa |

| protocolo.md | reglas que se le envian al modelo |

| arrancar.bat | todo en un clic |



\## Ajustes utiles (config.json)

\- `metodo\_envio`: `"enter"` (probado, por defecto) o `"boton"`.

\- `idle\_segundos`: segundos de silencio antes de dar la respuesta por terminada.

\- `timeout\_fase\_segundos`: corte por fase.

\- `max\_intentos`: reintentos por fase antes de marcarla `bloqueada`.

\- `comandos\_verificacion`: lo que debe pasar para dar la fase por buena.

\- `ntfy.topico`: cambialo si quieres tus propios avisos.



\## Si algo falla

\- "No pude conectar a ...9222": Brave cerrado sin la bandera. Cierralo y relanzalo con `--remote-debugging-port=9222`.

\- "Ningun selector visible": la UI de arena.ai cambio; ajusta `selectores` en config.json.

\- Fase `bloqueada`: mira `critica` en `proyecto/fases.jsonl`, corrige y borra `"estado"`/`"critica"` para reintentar.

\- Nada de esto toca tu sesion: el bot escribe en la pestana abierta.



\## .gitignore recomendado

&#x20;   \_\_pycache\_\_/

&#x20;   \*.pyc

&#x20;   .venv/

