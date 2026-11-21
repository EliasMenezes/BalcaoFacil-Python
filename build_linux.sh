#!/bin/sh
# Gera dist/balcaofacil (executavel unico). Precisa de Python 3.10+ no Linux.
cd "$(dirname "$0")" || exit 1
python3 -m pip install --user pyinstaller && python3 -m PyInstaller balcaofacil.spec --noconfirm --clean && echo "Pronto: dist/balcaofacil"
