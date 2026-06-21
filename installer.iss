; Lexio Study Player — Inno Setup Script
; Gera: installer/LexioStudyPlayer-<versao>-Setup.exe
;
; A versão é LIDA de version.txt (fonte de verdade = APP_VERSION, que o build.sh
; sincroniza para version.txt). NUNCA hardcodar a versão aqui — já aconteceu o
; instalador sair com um número stale (3.9.6) enquanto o código era mais recente.

#define MyAppName "Lexio Study Player"
#define VerHandle = FileOpen("version.txt")
#define MyAppVersion = Trim(FileRead(VerHandle))
#expr FileClose(VerHandle)
#if MyAppVersion == ""
  #error version.txt vazio — nao consegui ler a versao
#endif
#define MyAppPublisher "Lexio"
#define MyAppURL "https://lexio.app"
#define MyAppExeName "LexioStudyPlayer.exe"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\Lexio Study Player
DisableDirPage=yes
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=LexioStudyPlayer-{#MyAppVersion}-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "pt"; MessagesFile: "compiler:Languages\Portuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: checkedonce

[Files]
Source: "dist\LexioStudyPlayer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Lexio Study Player"; Filename: "{app}\LexioStudyPlayer.exe"
Name: "{autodesktop}\Lexio Study Player"; Filename: "{app}\LexioStudyPlayer.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LexioStudyPlayer.exe"; Description: "Launch Lexio Study Player"; Flags: postinstall nowait skipifsilent shellexec
