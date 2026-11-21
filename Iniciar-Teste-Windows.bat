@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul && (py server.py & goto fim)
where python >nul 2>nul && (python server.py & goto fim)
echo Python nao encontrado. Instale a versao 3.10 ou superior em https://www.python.org/downloads/
echo (marque a opcao "Add python.exe to PATH") e execute este arquivo de novo.
:fim
pause
