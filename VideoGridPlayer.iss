; VideoGridPlayer.iss
; Inno Setup installer script for Video Grid Player.
;
; Prerequisites: PyInstaller must have already built dist\VideoGridPlayer\
;   pyinstaller VideoGridPlayer.spec
;
; Build the installer:
;   iscc VideoGridPlayer.iss
;
; Output: installer\VideoGridPlayer-Setup-1.2.0.exe
;
; Version bump checklist:
;   1. AppVersion below
;   2. OutputBaseFilename below
;   3. APP_VERSION in video_grid.py
;   4. CFBundleShortVersionString/CFBundleVersion in VideoGridPlayer.spec

#define AppName     "Video Grid Player"
#define AppVersion  "1.2.0"
#define AppExeName  "VideoGridPlayer.exe"
#define AppURL      "https://github.com/your-org/Video-Grid-Player"

; ---------------------------------------------------------------------------
[Setup]
; ---- Identity ----
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Video Grid Player
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}

; ---- Install location ----
; {autopf} resolves to Program Files (x86) on 32-bit, Program Files on 64-bit
DefaultDirName={autopf}\VideoGridPlayer
DefaultGroupName={#AppName}
AllowNoIcons=yes

; ---- Output ----
OutputDir=installer
OutputBaseFilename=VideoGridPlayer-Windows-Setup-{#AppVersion}

; ---- Compression ----
Compression=lzma2/ultra64
SolidCompression=yes

; ---- UI ----
WizardStyle=modern
SetupIconFile=assets\icon.ico
WizardImageFile=compiler:WizModernImage.bmp
WizardSmallImageFile=compiler:WizModernSmallImage.bmp

; ---- Misc ----
; Require Windows 10 or newer
MinVersion=10.0.17763
; Allow the user to install per-user or machine-wide from the command line
PrivilegesRequiredOverridesAllowed=commandline
; Show the uninstall entry in Add/Remove Programs with the app icon
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}

; ---------------------------------------------------------------------------
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

; ---------------------------------------------------------------------------
[Tasks]
Name: "desktopicon"; \
  Description: "Create a &desktop shortcut"; \
  GroupDescription: "Additional icons:"; \
  Flags: unchecked

; ---------------------------------------------------------------------------
[Files]
; Copy the entire PyInstaller one-folder output.
; recursesubdirs + createallsubdirs preserves the plugins/ hierarchy.
Source: "dist\VideoGridPlayer\*"; \
  DestDir: "{app}"; \
  Flags: ignoreversion recursesubdirs createallsubdirs

; ---------------------------------------------------------------------------
[Icons]
; Start Menu group
Name: "{group}\{#AppName}";         Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"

; Desktop shortcut (opt-in — unchecked by default in [Tasks])
Name: "{commondesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; \
  Tasks: desktopicon

; ---------------------------------------------------------------------------
[Run]
; Offer to launch the app immediately after the installer finishes.
Filename: "{app}\{#AppExeName}"; \
  Description: "Launch {#AppName}"; \
  Flags: nowait postinstall skipifsilent
