#!/bin/bash
# Onefile-сборка KinemaSim.app для macOS (PyInstaller).
# Результат: dist/KinemaSim.app — одиночный файл, запускается двойным кликом.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

echo "============================================"
echo "Prepare environment for build..."

rm -rf build dist
python3 -m venv build_env

echo
echo "Installing requirements..."

build_env/bin/python -m pip install --upgrade pip --quiet
build_env/bin/python -m pip install -r requirements-dev.txt --quiet

echo
echo "============================================"
echo "PyInstaller onefile build..."

build_env/bin/pyinstaller \
    --noconfirm --clean --onefile --windowed \
    --name KinemaSim \
    --add-data "src/interface_module/uis:interface_module/uis" \
    --add-data "src/resources:resources" \
    src/main.py

echo
echo "Packing dmg..."

hdiutil create -volname "KinemaSim" -srcfolder dist/KinemaSim.app \
    -ov -format UDZO dist/KinemaSim.dmg

echo
echo "✓ Готово: $(cd dist && pwd)/KinemaSim.app и dist/KinemaSim.dmg"
