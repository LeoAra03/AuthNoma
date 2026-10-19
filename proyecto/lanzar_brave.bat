@echo off
setlocal enableextensions
title Autonoma - Brave de depuracion

rem ======== PEGA AQUI LA RUTA REAL ========
set "BRAVE=C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
rem ========================================

if not exist "%BRAVE%" (
  echo [X] Esa ruta no existe: %BRAVE%
  echo     Compruebala y vuelve a intentarlo.
  pause
  exit /b 1
)
echo [OK] Brave: %BRAVE%

netstat -ano | findstr ":9222" | findstr /i "LISTENING" >nul 2>&1
if not errorlevel 1 (
  echo [i] El puerto 9222 ya escucha. Si "no pasa nada" al relanzar, es esto:
  echo     cierra TODAS las ventanas de Brave y vuelve a correr este archivo.
  goto :verificar
)

set "PERFIL=%LOCALAPPDATA%\autonoma-brave"
echo [i] Perfil del bot: %PERFIL%

start "" "%BRAVE%" ^
  --remote-debugging-port=9222 ^
  --remote-allow-origins=* ^
  --user-data-dir="%PERFIL%" ^
  --no-first-run ^
  --no-default-browser-check ^
  --disable-background-timer-throttling ^
  --disable-renderer-backgrounding ^
  --disable-backgrounding-occluded-windows ^
  --disable-features=CalculateNativeWinOcclusion ^
  "https://arena.ai/agent"

:verificar
echo.
echo Esperando al puerto 9222...
set /a intentos=0
:espera
set /a intentos+=1
timeout /t 1 /nobreak >nul
netstat -ano | findstr ":9222" | findstr /i "LISTENING" >nul 2>&1
if not errorlevel 1 goto :listo
if %intentos% lss 20 goto :espera
echo [X] Brave abrio pero SIN depuracion. Causa: ya tenias Brave con ESE perfil.
echo     Cierra todas las ventanas de Brave y reintenta.
pause
exit /b 1

:listo
echo [OK] Puerto 9222 abierto.
echo      Compruebalo: http://127.0.0.1:9222/json/version
pause
exit /b 0w