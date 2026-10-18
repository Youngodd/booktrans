; Inno Setup script for Book Translator (Windows). Build: iscc /DAppVersion=0.1.0 packaging\installer.iss
; Per-user install, no administrator rights. User data (%APPDATA%\BookTranslator: jobs, resume caches,
; logs) is kept on uninstall so a reinstall does not lose a half-translated book.
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{7B1C2D8E-5A3F-4E6B-9C47-2F0A1D6E8B35}
AppName=Book Translator
AppVersion={#AppVersion}
AppPublisher=Youngodd
DefaultDirName={localappdata}\Programs\BookTranslator
DefaultGroupName=Book Translator
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\installer
OutputBaseFilename=BookTranslator-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
UninstallDisplayName=Book Translator
UninstallDisplayIcon={app}\BookTranslator.exe

[Files]
Source: "..\dist\BookTranslator\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Book Translator"; Filename: "{app}\BookTranslator.exe"
Name: "{autodesktop}\Book Translator"; Filename: "{app}\BookTranslator.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\BookTranslator.exe"; Description: "Start Book Translator"; Flags: nowait postinstall skipifsilent
