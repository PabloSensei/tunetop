; Inno Setup script for Tunetop. Requires dist\Tunetop.exe to already exist
; (run build-exe.bat first). Build with:
;
;   iscc /DMyAppVersion=1.2.0 installer\Tunetop.iss
;
; MyAppVersion defaults to 0.0.0-dev when built without /D, for local testing.
;
; AppId is fixed forever so upgrades replace the previous install instead of
; creating a second Add/Remove Programs entry — never regenerate it.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif

#define MyAppName "Tunetop"
#define MyAppPublisher "Pawel Januszko"
#define MyAppURL "https://github.com/PabloSensei/tunetop"
#define MyAppExeName "Tunetop.exe"

[Setup]
AppId={{B127C747-16EB-4839-A467-67004BFB481D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
; Per-user install under %LocalAppData%, same as VS Code/Discord — no UAC
; prompt, matching Tunetop's own per-user %APPDATA% settings folder.
DefaultDirName={localappdata}\Programs\{#MyAppName}
PrivilegesRequired=lowest
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputBaseFilename=TunetopSetup-{#MyAppVersion}
OutputDir=..\dist
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\Tunetop.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.ru.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\CHANGELOG.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Settings/skins/locales under %APPDATA%\Tunetop are left in place on purpose
; (matches most Windows apps) — only the install folder itself is removed.
Type: filesandordirs; Name: "{app}"
