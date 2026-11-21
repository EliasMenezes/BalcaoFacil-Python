@echo off
rem Gera dist\balcaofacil.exe (executavel unico). Precisa de Python 3.10+ no Windows.
py -m pip install pyinstaller || exit /b 1
py -m PyInstaller balcaofacil.spec --noconfirm --clean || exit /b 1
echo.
echo Pronto: dist\balcaofacil.exe
pause
