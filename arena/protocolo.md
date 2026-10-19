# Protocolo de trabajo

Programas este repo fase a fase. Recibes una fase con su objetivo y su criterio
de aceptacion, y devuelves el codigo.

## Como entregas archivos

Cada archivo va COMPLETO en un bloque con la ruta en el info string:

```python path=arena/ejemplo.py
def hola():
    return "mundo"
Reglas:

La ruta va SIEMPRE en el info string, en formato path=RUTA.
Escribe el archivo ENTERO. Nunca uses ... ni "aqui va el resto".
Para borrar un archivo escribe una linea suelta: BORRAR: ruta/del/archivo.py.
Si un archivo no cambia, no lo reenvies.
Poco texto: bloques y alguna linea de explicacion.
Como terminas
Fase resuelta: escribe @@FASE_OK@@ solo, en su propia linea, al final.
Si te falta informacion: escribe @@BLOQUEADO: motivo@@.
---

## 10. `arena/arrancar.bat`

```bat
@echo off
setlocal
cd /d "%~dp0"

set "PY=py"
where py >nul 2>&1 || set "PY=python"
where %PY% >nul 2>&1 || (echo [x] No encuentro Python en el PATH. & pause & exit /b 1)

set "BRAVE="
for %%R in (
  "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
  "C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe"
  "%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"
) do if exist %%R set "BRAVE=%%~R"

netstat -ano | findstr /c:":9222" | findstr /i "LISTENING" >nul
if errorlevel 1 (
  if defined BRAVE (
    echo [i] Brave no escucha en 9222. Lo abro con depuracion remota...
    start "" "%BRAVE%" --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\AutonomaBrave" https://arena.ai/
    echo [i] Espera a que cargue y, la primera vez, inicia sesion en arena.ai.
    timeout /t 10 /nobreak >nul
  ) else (
    echo [!] No encuentro brave.exe. Abrelo a mano con: --remote-debugging-port=9222
  )
) else (
  echo [i] Ya hay algo escuchando en 9222.
)

%PY% "%~dp0verificar.py"
if errorlevel 1 (
  echo.
  echo [x] La comprobacion fallo. Arregla lo de arriba y vuelve a lanzar.
  pause
  exit /b 1
)

echo.
echo === Lanzando orquestador ===
%PY% "%~dp0orquestador.py"
echo.
echo [i] Terminado con codigo %errorlevel%.
pause