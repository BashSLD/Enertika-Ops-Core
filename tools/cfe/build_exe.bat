@echo off
setlocal
REM Build endurecido del lanzador CFE.
REM Requiere Python 3.12 y clave Ed25519.
REM Authenticode es opcional para despliegues internos sin presupuesto.

cd /d "%~dp0"

if not defined CFE_LAUNCHER_VERSION (
    echo ERROR: Define CFE_LAUNCHER_VERSION, por ejemplo 2026.07.30.
    exit /b 1
)
if not defined CFE_SIGNING_PRIVATE_KEY_FILE (
    echo ERROR: Define CFE_SIGNING_PRIVATE_KEY_FILE.
    exit /b 1
)
if not defined CFE_AUTHENTICODE_CERT_SHA1 (
    if /I not "%CFE_ALLOW_UNSIGNED%"=="1" (
        echo ERROR: Define CFE_AUTHENTICODE_CERT_SHA1 para firmar con Authenticode.
        echo        Para un build interno sin Authenticode, define CFE_ALLOW_UNSIGNED=1.
        exit /b 1
    )
) else (
    where signtool >nul 2>nul
    if errorlevel 1 (
        echo ERROR: SignTool no esta disponible en PATH.
        exit /b 1
    )
)

set "PYTHON_CMD=py -3.12"
if defined CFE_BUILD_PYTHON set "PYTHON_CMD=%CFE_BUILD_PYTHON%"
set "BUILD_VENV=%~dp0.cfe-build-venv"
set "EXE_PATH=%~dp0dist\RenovarSesionCFE.exe"
set "MANIFEST_PATH=%~dp0dist\RenovarSesionCFE.exe.manifest.json"
set "TIMESTAMP_URL=https://timestamp.digicert.com"
if defined CFE_TIMESTAMP_URL set "TIMESTAMP_URL=%CFE_TIMESTAMP_URL%"

echo [1/6] Validando Python 3.12...
%PYTHON_CMD% -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)"
if errorlevel 1 (
    echo ERROR: El build requiere Python 3.12.
    exit /b 1
)

echo [2/6] Creando entorno aislado...
%PYTHON_CMD% -m venv --clear "%BUILD_VENV%"
if errorlevel 1 exit /b 1

echo [3/6] Instalando dependencias fijadas...
"%BUILD_VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check --no-cache-dir -r requirements-build.txt
if errorlevel 1 exit /b 1

echo [4/6] Compilando sin UPX...
"%BUILD_VENV%\Scripts\python.exe" -m PyInstaller --clean --noconfirm --onefile --console --noupx --name RenovarSesionCFE --collect-all playwright renovar_sesion.py
if errorlevel 1 exit /b 1
if not exist "%EXE_PATH%" (
    echo ERROR: PyInstaller no genero %EXE_PATH%.
    exit /b 1
)

if defined CFE_AUTHENTICODE_CERT_SHA1 (
    echo [5/6] Firmando Authenticode...
    signtool sign /sha1 "%CFE_AUTHENTICODE_CERT_SHA1%" /fd SHA256 /tr "%TIMESTAMP_URL%" /td SHA256 "%EXE_PATH%"
    if errorlevel 1 exit /b 1
    signtool verify /pa /all "%EXE_PATH%"
    if errorlevel 1 exit /b 1
) else (
    echo [5/6] Authenticode omitido por CFE_ALLOW_UNSIGNED=1.
    echo ADVERTENCIA: Windows mostrara "Editor desconocido".
)

echo [6/6] Generando manifest Ed25519...
"%BUILD_VENV%\Scripts\python.exe" sign_release.py sign --exe "%EXE_PATH%" --private-key "%CFE_SIGNING_PRIVATE_KEY_FILE%" --version "%CFE_LAUNCHER_VERSION%" --output "%MANIFEST_PATH%"
if errorlevel 1 exit /b 1

echo.
echo Build verificado:
echo   %EXE_PATH%
echo   %MANIFEST_PATH%
echo Sube ambos archivos en Admin ^> Configuracion Global ^> Recibos CFE.
endlocal
