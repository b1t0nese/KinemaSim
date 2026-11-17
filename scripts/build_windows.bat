@echo off
REM Onefile-сборка KinemaSim.exe для Windows (PyInstaller).
REM Результат: dist\KinemaSim.exe — одиночный файл.
REM Запускать на Windows: scripts\build_windows.bat

setlocal
cd /d "%~dp0.."

echo ============================================
echo Prepare environment for build...

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
python -m venv build_env

echo.
echo Installing requirements...

build_env\Scripts\python -m pip install --upgrade pip --quiet
build_env\Scripts\python -m pip install -r requirements-dev.txt --quiet

echo.
echo ============================================
echo PyInstaller onefile build...

build_env\Scripts\pyinstaller ^
    --noconfirm --clean --onefile --windowed ^
    --name KinemaSim ^
    --add-data "src\interface_module\uis;interface_module\uis" ^
    --add-data "src\resources;resources" ^
    src\main.py

echo.
echo Done: %cd%\dist\KinemaSim.exe
endlocal
