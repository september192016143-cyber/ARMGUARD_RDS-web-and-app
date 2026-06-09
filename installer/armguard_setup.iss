; =============================================================================
; ARMGUARD RDS — Inno Setup Installer Script
; =============================================================================
; Prerequisites:
;   1. Build the PyInstaller bundle first:
;        pyinstaller desktop_app.spec
;   2. Install Inno Setup 6 (https://jrsoftware.org/isinfo.php)
;   3. Compile this script in Inno Setup IDE or via ISCC.exe:
;        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\armguard_setup.iss
;
; Output: installer\Output\ARMGUARD_RDS_Setup.exe
; =============================================================================

#define AppName      "ARMGUARD RDS"
#define AppVersion   "2.0"
#define AppPublisher "Philippine Air Force — Armory Management"
#define AppExeName   "ARMGUARD_RDS.exe"
#define BuildDir     "..\dist\ARMGUARD_RDS"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputDir=Output
OutputBaseFilename=ARMGUARD_RDS_Setup
SetupIconFile=..\project\armguard\static\images\favicon.ico
Compression=lzma2/ultra64
SolidCompression=yes
; Allow installation without admin if user chooses user-mode dir
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
; Minimum Windows 10
MinVersion=10.0
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &Desktop shortcut"; GroupDescription: "Additional icons:"; Flags: checked

[Files]
; Copy the entire PyInstaller output folder
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start Menu
Name: "{group}\{#AppName}";   FileName: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{group}\Uninstall {#AppName}"; FileName: "{uninstallexe}"
; Desktop (if task selected)
Name: "{autodesktop}\{#AppName}"; FileName: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
; After install: offer to open the .env placement folder
Filename: "{app}"; Description: "Open installation folder (to place your .env file)"; \
  Flags: postinstall skipifsilent shellexec

[Code]
// Show a custom info page reminding the user to place the .env file
procedure CurStepChanged(CurStep: TSetupStep);
var
  InfoMsg: string;
begin
  if CurStep = ssPostInstall then
  begin
    InfoMsg :=
      'ARMGUARD RDS has been installed.' + #13#10 + #13#10 +
      'IMPORTANT — Before launching the app:' + #13#10 +
      '  1. Download the .env file from your ARMGUARD server' + #13#10 +
      '     (Settings > Desktop App Setup > Download .env).' + #13#10 +
      '  2. Place the .env file in the installation folder:' + #13#10 +
      '     ' + ExpandConstant('{app}') + #13#10 + #13#10 +
      'The app will NOT sync with the server until the .env is in place.';
    MsgBox(InfoMsg, mbInformation, MB_OK);
  end;
end;
