@echo off
rem Un clic. Modo nube puro: NO clona, NO npm ci, NO preflight con clon.
rem   arrancar-nube.bat
rem   arrancar-nube.bat LeoAra03/MiRepo main 4
setlocal EnableExtensions
cd /d "%~dp0"
set "ARENA=%~dp0"
set "AUTONOMA_MODO=nube"

set "REPO=%~1"
if "%REPO%"=="" set "REPO=LeoAra03/Fire-ash-modifier"
set "RAMA=%~2"
if "%RAMA%"=="" set "RAMA=main"
set "PESTANAS=%~3"
if "%PESTANAS%"=="" set "PESTANAS=1"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY ( echo Falta Python 3.10+. & pause & exit /b 127 )

rem Nada de netstat: se comprueba de verdad si el puerto de depuracion responde.
rem Si no responde, esperar_cdp.py lanza Brave y espera.
%PY% "%ARENA%esperar_cdp.py" --tope 90
if errorlevel 1 ( echo. & pause & exit /b 1 )

if exist "%ARENA%STOP" del "%ARENA%STOP" >nul 2>nul

%PY% "%ARENA%reparar_config.py" --revisar
%PY% "%ARENA%repo_url.py" --url "%REPO%" --branch "%RAMA%" --modo nube
if errorlevel 1 ( echo [FALLO] no pude anotar el remoto. & pause & exit /b 1 )

%PY% "%ARENA%nube.py" --repo "%REPO%" --branch "%RAMA%" --pestanas %PESTANAS% ^
  --fases-por-prompt 5 --merge-cada 20 --latido 30
pause
exit /b 0