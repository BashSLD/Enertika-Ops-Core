@echo off
REM Genera renovar_sesion.exe con PyInstaller.
REM
REM Requisitos (ejecutar una sola vez):
REM   pip install pyinstaller playwright
REM   playwright install msedge
REM
REM Resultado: tools\cfe\dist\renovar_sesion.exe
REM Subelo en Admin > Configuracion Global > Recibos CFE > Ejecutable del lanzador.

cd /d "%~dp0"

echo [1/2] Compilando con PyInstaller...
python -m PyInstaller --onefile --console --name renovar_sesion --collect-all playwright renovar_sesion.py

echo.
if exist dist\renovar_sesion.exe (
    echo [2/2] Listo: dist\renovar_sesion.exe
    echo Sube este archivo en Admin ^> Configuracion CFE ^> Ejecutable del lanzador.
) else (
    echo Error: no se genero el ejecutable. Revisa la salida de PyInstaller.
    exit /b 1
)
