; J.A.R.V.I.S. Windows 安裝包（Inno Setup 6）
; 用法：scripts\build-installer.ps1（會先跑 PyInstaller 產 dist\JARVIS，再呼叫 ISCC）
;       或手動：ISCC /DAppVersion=0.2.0 installer\JARVIS.iss  → dist\JARVIS-Setup-0.2.0.exe
;
; 設計決定：
; - 預設「只給目前使用者」安裝（PrivilegesRequired=lowest → %LocalAppData%\Programs\JARVIS）：
;   不用管理員、不會被 UAC 擋、安裝目錄可寫。想裝到 Program Files 的人在對話框選「所有使用者」。
; - 金鑰 / 設定在 %USERPROFILE%\.jarvis\.env，解除安裝不刪（重裝不用再登入）；要清掉的人自己刪那個資料夾。
; - 不做 onefile：PyInstaller onedir（JARVIS.exe + _internal\）啟動快、防毒不誤判。

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "J.A.R.V.I.S."
#define AppExe "JARVIS.exe"
#define AppUrl "https://github.com/Venshen885361/jarvis-desktop"

[Setup]
AppId={{6F1A6B0E-3C2B-4E9C-9C0D-1D4E7A2B9F31}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Venshen
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
DefaultDirName={autopf}\JARVIS
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=JARVIS-Setup-{#AppVersion}
SetupIconFile=..\assets\jarvis.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
MinVersion=10.0
LicenseFile=..\LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
; 繁體中文翻譯不在 Inno 內建清單裡：installer\ChineseTraditional.isl 存在才用（build-installer.ps1 會去抓）
#ifexist "ChineseTraditional.isl"
Name: "chinesetraditional"; MessagesFile: "ChineseTraditional.isl"
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startup"; Description: "開機時自動啟動 J.A.R.V.I.S.（登入 Windows 後桌寵就在）"; GroupDescription: "其他："; Flags: unchecked

[Files]
Source: "..\dist\JARVIS\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion createallsubdirs

[Dirs]
; 設定資料夾先建好，開始功能表的捷徑才有地方指
Name: "{%USERPROFILE}\.jarvis"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{group}\{#AppName}（更換 API 金鑰）"; Filename: "{app}\{#AppExe}"; Parameters: "--login"; WorkingDir: "{app}"
Name: "{group}\設定檔資料夾（.jarvis）"; Filename: "{%USERPROFILE}\.jarvis"
Name: "{group}\解除安裝 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: startup

[Run]
Filename: "{app}\{#AppExe}"; Description: "現在啟動 {#AppName}（第一次會要求輸入 API 金鑰）"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; 解除安裝前把還在跑的桌寵關掉，不然 _internal\ 裡的 dll 刪不掉
Filename: "{cmd}"; Parameters: "/C taskkill /IM {#AppExe} /F /T"; Flags: runhidden; RunOnceId: "killjarvis"

[Code]
// 解除安裝結尾提醒：金鑰與設定沒有一起刪
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    MsgBox('J.A.R.V.I.S. 已移除。' + #13#10 +
           '你的 API 金鑰與設定仍在 ' + ExpandConstant('{%USERPROFILE}') + '\.jarvis，' + #13#10 +
           '不想留就手動刪掉那個資料夾。', mbInformation, MB_OK);
end;
