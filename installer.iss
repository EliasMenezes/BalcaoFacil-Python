; Inno Setup 6 – gera output\BalcaoFacil-Setup.exe (não exige administrador)
#define AppName "Balcão Fácil"
#define AppVersion "1.0.0"

[Setup]
AppId={{B7C2D1A4-5E3F-4A6B-9C1D-2F8E7A0B4C11}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\BalcaoFacil
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=output
OutputBaseFilename=BalcaoFacil-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#AppName}
InfoAfterFile=LEIA-ME-INSTALADO.txt

[Languages]
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"
Name: "startup"; Description: "Iniciar o servidor junto com o Windows"; Flags: unchecked

[Files]
Source: "dist\balcaofacil.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autodesktop}\Balcão Fácil"; Filename: "{app}\balcaofacil.exe"; WorkingDir: "{app}"; Flags: runminimized; Tasks: desktopicon
Name: "{autoprograms}\Balcão Fácil"; Filename: "{app}\balcaofacil.exe"; WorkingDir: "{app}"; Flags: runminimized
Name: "{userstartup}\Balcão Fácil (servidor)"; Filename: "{app}\balcaofacil.exe"; Parameters: "--servidor"; WorkingDir: "{app}"; Flags: runminimized; Tasks: startup

[Run]
Filename: "{app}\balcaofacil.exe"; Parameters: "vendor"; StatusMsg: "Baixando recursos para uso offline..."; Flags: runhidden
Filename: "{app}\balcaofacil.exe"; Description: "Abrir o Balcão Fácil agora"; Flags: postinstall nowait skipifsilent unchecked
; (opcional) o Setup.exe é só um empacotamento do executável único. O administrador é criado no primeiro acesso, no navegador.
; Os dados em %LOCALAPPDATA%\BalcaoFacil\data NÃO são apagados ao desinstalar.
