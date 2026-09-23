; Inno Setup script - built by packaging\build.ps1 (which passes /DAppVersion).
; Per-user install: no admin rights needed.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6E0B7C1E-3C4B-4D0A-9D8E-5C2A1F7B9A01}
AppName=ScreenRec
AppVersion={#AppVersion}
AppPublisher=ScreenRec
DefaultDirName={localappdata}\Programs\ScreenRec
DefaultGroupName=ScreenRec
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=ScreenRec-Setup-{#AppVersion}
SetupIconFile=screenrec.ico
UninstallDisplayIcon={app}\ScreenRec.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
; Inno Setup 6 ships no Chinese translation (only an unofficial download), so
; the setup wizard itself is English for now.
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\ScreenRec\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\ScreenRec"; Filename: "{app}\ScreenRec.exe"; AppUserModelID: "ScreenRec.ScreenRecorder"
Name: "{autodesktop}\ScreenRec"; Filename: "{app}\ScreenRec.exe"; Tasks: desktopicon; AppUserModelID: "ScreenRec.ScreenRecorder"

[Run]
Filename: "{app}\ScreenRec.exe"; Description: "{cm:LaunchProgram,ScreenRec}"; Flags: nowait postinstall skipifsilent
