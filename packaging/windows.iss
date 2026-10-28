#define AppVersion "0.5.0"
[Setup]
AppId={{C2AC846B-24F0-4ABE-9FB7-750C1E49DE03}
AppName=LabelDesk
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\LabelDesk
DefaultGroupName=LabelDesk
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=LabelDesk-0.5.0-Windows-x64-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\LabelDesk.exe
CloseApplications=yes
[Files]
Source: "..\dist\LabelDesk\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\LabelDesk"; Filename: "{app}\LabelDesk.exe"
Name: "{autodesktop}\LabelDesk"; Filename: "{app}\LabelDesk.exe"
[Run]
Filename: "{app}\LabelDesk.exe"; Description: "Launch LabelDesk"; Flags: nowait postinstall skipifsilent
