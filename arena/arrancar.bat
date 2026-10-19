@echo off
rem Doble clic, o:  arrancar.bat https://github.com/LeoAra03/Fire-ash-modifier main
rem Acepta URL de GitHub, "owner/repo" o una carpeta local ya clonada.
rem
rem MODO NUBE:  set AUTONOMA_MODO=nube   (no clona, no npm ci, usa arena\tareas.txt)
setlocal EnableExtensions
cd /d "%~dp0.."
set "ARENA=%~dp0"
set "PF86=%ProgramFiles(x86)%"
if "%AUTONOMA_MODO%"=="" set "AUTONOMA_MODO=local"

rem --- repositorio (argumento o pregunta) ---
set "ENTRADA=%~1"
if not "%ENTRADA%"=="" goto repo_listo
echo.
echo   Pega la URL del repo de GitHub (o owner/repo, o una carpeta local).
echo   Ejemplo: https://github.com/LeoAra03/Fire-ash-modifier
set /p "_r=Repositorio: "
if not "%_r%"=="" set "ENTRADA=%_r%"
:repo_listo
if "%ENTRADA%"=="" ( echo No indicaste repositorio. & pause & exit /b 1 )

rem --- rama (por defecto main) ---
set "BRANCH=%~2"
if "%BRANCH%"=="" set "BRANCH=main"

rem --- Python ---
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY ( echo Falta Python 3.10+. https://www.python.org/downloads/ & pause & exit /b 127 )

rem --- dependencias (una sola vez) ---
%PY% -c "import playwright" >nul 2>nul
if not errorlevel 1 goto deps_ok

echo === Instalando dependencias (una sola vez) ===
if exist "%ARENA%requirements.txt" (
  %PY% -m pip install -r "%ARENA%requirements.txt"
) else (
  echo   [aviso] no hay arena\requirements.txt: instalo playwright directo
  %PY% -m pip install "playwright>=1.40"
)
if errorlevel 1 (
  echo   reintento con --user ...
  %PY% -m pip install --user "playwright>=1.40"
)
%PY% -c "import playwright" >nul 2>nul
if errorlevel 1 (
  echo.
  echo No pude instalar playwright. Prueba a mano en una consola:
  echo    %PY% -m pip install --upgrade pip
  echo    %PY% -m pip install playwright
  pause & exit /b 1
)
:deps_ok

rem ============================ BRAVE (siempre) ============================
netstat -ano | findstr ":9222" >nul 2>nul
if not errorlevel 1 goto brave_listo

set "BRAVE="
for %%P in (
  "%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe"
  "%PF86%\BraveSoftware\Brave-Browser\Application\brave.exe"
  "%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe"
) do if not defined BRAVE if exist "%%~P" set "BRAVE=%%~P"
if not defined BRAVE ( echo No encuentro brave.exe. Edita este .bat con la ruta. & pause & exit /b 1 )

echo === Abriendo Brave con depuracion (inicia sesion en arena.ai si te lo pide) ===
start "" "%BRAVE%" --remote-debugging-port=9222 --remote-allow-origins=* ^
  --user-data-dir="%USERPROFILE%\.brave-autonoma" ^
  --disable-background-timer-throttling --disable-renderer-backgrounding ^
  --disable-backgrounding-occluded-windows ^
  --disable-features=CalculateNativeWinOcclusion https://arena.ai/agent
echo Esperando a que Brave abra el puerto 9222...
call :espera_cdp
:brave_listo

if exist "%ARENA%STOP" del "%ARENA%STOP" >nul 2>nul

rem ============================ MODO NUBE ============================
if /I "%AUTONOMA_MODO%"=="nube" goto modo_nube
goto modo_local

rem ---------------------------------------------------------------------
:modo_nube
echo.
echo === MODO NUBE: sin clon, sin npm ci ===
%PY% "%ARENA%repo_url.py" --url "%ENTRADA%" --branch "%BRANCH%" --modo nube
if errorlevel 1 ( echo. & echo [FALLO] no pude anotar el remoto. & pause & exit /b 1 )

echo.
echo === Bucle nube ===
echo (para pararlo: crea el archivo "%ARENA%STOP", o cierra esta ventana)
%PY% "%ARENA%nube.py" --repo "%ENTRADA%" --branch "%BRANCH%"
echo.
echo Terminado.
pause
exit /b 0

rem ---------------------------------------------------------------------
:modo_local
echo.
echo === Preparando el repositorio (clon local) ===
set "REPO="
for /f "delims=" %%i in ('%PY% "%ARENA%repo_url.py" --url "%ENTRADA%" --branch "%BRANCH%" --quiet') do set "REPO=%%i"
if not defined REPO (
  echo.
  echo [FALLO] No pude resolver el repositorio. Revisa la URL y que git este instalado.
  pause & exit /b 1
)
echo   clon local : %REPO%
echo   rama       : %BRANCH%
echo   repo       : %ENTRADA%

if not exist "%REPO%\package.json" goto sin_npm
if exist "%REPO%\node_modules" goto sin_npm
where npm >nul 2>nul
if errorlevel 1 ( echo   [aviso] npm no esta en el PATH: instala node_modules a mano antes de verificar. & goto sin_npm )
echo === Instalando dependencias del repo (npm ci, una sola vez) ===
pushd "%REPO%" && call npm ci && popd
:sin_npm

set "ARGS=--repo "%REPO%" --branch "%BRANCH%""

echo.
echo === Preflight ===
%PY% "%ARENA%revisar_fases.py" --repo "%REPO%"
if errorlevel 1 ( echo. & echo Corrige lo de arriba y vuelve a intentarlo. & pause & exit /b 1 )

echo.
echo === Bucle ===
echo (para pararlo: crea el archivo "%ARENA%STOP", o cierra esta ventana)
%PY% "%ARENA%vigilante.py" %ARGS%
echo.
echo Terminado.
pause
exit /b 0

:espera_cdp
set /a _t=0
:ec_loop
netstat -ano | findstr ":9222" >nul 2>nul
if not errorlevel 1 ( echo   CDP listo. & exit /b 0 )
set /a _t+=1
if %_t% geq 40 ( echo   Aviso: el puerto 9222 no responde todavia; sigo igual. & exit /b 0 )
timeout /t 1 >nul
goto ec_loop