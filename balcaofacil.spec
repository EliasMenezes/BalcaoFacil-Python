# PyInstaller – gera UM único arquivo: dist/balcaofacil.exe (Windows) ou dist/balcaofacil (Linux).
# Rode no próprio sistema de destino:  pyinstaller balcaofacil.spec --noconfirm --clean
a = Analysis(['server.py'],
             datas=[('public', 'public'), ('pages', 'pages'), ('sync.js', '.')],
             excludes=['tkinter', 'unittest', 'pydoc', 'test'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='balcaofacil', console=True, upx=False)
