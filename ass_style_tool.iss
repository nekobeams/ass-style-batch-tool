; -- Subtitle Style Batch Tool Inno Setup Script --
; AppId 一經發佈絕不可再更改(否則使用者升級會被視為全新安裝,留下舊版殘留)

#define MyAppName "Subtitle Style Batch Tool"
#define MyAppVersion "1.0"
#define MyAppExeName "ass_style_tool.exe"

[Setup]
AppId={{A6F1AE07-C85D-4E18-B33C-08AA18A17BF4}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
OutputDir=installer_dist
OutputBaseFilename=ass-style-tool-setup
SetupIconFile=assets\icon.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}

[Types]
Name: "full"; Description: "完整安裝"
Name: "custom"; Description: "自訂安裝"; Flags: iscustom

[Components]
Name: "core"; Description: "主程式(必要)"; Types: full custom; Flags: fixed
#if DirExists("installer_payload\ffmpeg")
Name: "ffmpeg"; Description: "ffmpeg(影片解析度偵測用)"; Types: full custom
#endif
#if DirExists("installer_payload\mkvtoolnix")
Name: "mkvtoolnix"; Description: "MKVToolNix(MKV 字幕封裝/處理用)"; Types: full custom
#endif

[Files]
Source: "dist\ass_style_tool\*"; DestDir: "{app}"; Components: core; Flags: recursesubdirs ignoreversion
#if DirExists("installer_payload\ffmpeg")
Source: "installer_payload\ffmpeg\*.exe"; DestDir: "{app}\tools"; Components: ffmpeg; Flags: ignoreversion
Source: "installer_payload\ffmpeg\LICENSE*"; DestDir: "{app}\licenses\ffmpeg"; Components: ffmpeg; Flags: ignoreversion skipifsourcedoesntexist
Source: "installer_payload\ffmpeg\COPYING*"; DestDir: "{app}\licenses\ffmpeg"; Components: ffmpeg; Flags: ignoreversion skipifsourcedoesntexist
#endif
#if DirExists("installer_payload\mkvtoolnix")
Source: "installer_payload\mkvtoolnix\*.exe"; DestDir: "{app}\tools"; Components: mkvtoolnix; Flags: ignoreversion
Source: "installer_payload\mkvtoolnix\LICENSE*"; DestDir: "{app}\licenses\mkvtoolnix"; Components: mkvtoolnix; Flags: ignoreversion skipifsourcedoesntexist
Source: "installer_payload\mkvtoolnix\COPYING*"; DestDir: "{app}\licenses\mkvtoolnix"; Components: mkvtoolnix; Flags: ignoreversion skipifsourcedoesntexist
#endif

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[Code]
function IsToolOnPath(const ExeName: String): Boolean;
var
  PathEnv, Dir: String;
  P: Integer;
begin
  Result := False;
  PathEnv := GetEnv('PATH') + ';';
  while Length(PathEnv) > 0 do
  begin
    P := Pos(';', PathEnv);
    if P = 0 then
      P := Length(PathEnv) + 1;
    Dir := Copy(PathEnv, 1, P - 1);
    PathEnv := Copy(PathEnv, P + 1, Length(PathEnv));
    if (Dir <> '') and FileExists(AddBackslash(Dir) + ExeName) then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

function IsMkvToolNixInstalled: Boolean;
begin
  Result := IsToolOnPath('mkvmerge.exe')
    or DirExists(ExpandConstant('{commonpf}\MKVToolNix'))
    or DirExists(ExpandConstant('{commonpf32}\MKVToolNix'));
end;

function IsFfmpegInstalled: Boolean;
begin
  { PATH 之外,也查這個程式自己上一次可能裝過的位置——ffmpeg 沒有官方安裝程式
    慣用的系統路徑可查(不像 MKVToolNix 有 Program Files\MKVToolNix),原本只查
    PATH 導致重裝/升級到同一個目錄時,自己上次裝過的 ffmpeg 偵測不到,勾選框
    每次都要手動取消。 }
  Result := IsToolOnPath('ffmpeg.exe')
    or FileExists(ExpandConstant('{app}\tools\ffmpeg.exe'));
end;

function ComponentsParamGiven: Boolean;
begin
  { 使用者/自動化明確用 /COMPONENTS= 指定過要裝哪些元件時,那個明確選擇必須贏過
    我們的偵測預設值——否則 /COMPONENTS=core,ffmpeg,mkvtoolnix 這種強制全裝的
    自動化安裝寫法會被悄悄蓋掉,變成永遠裝不進已偵測到的工具。 }
  Result := ExpandConstant('{param:COMPONENTS|__NONE__}') <> '__NONE__';
end;

procedure UncheckComponentIfDetected(const Caption: String; Detected: Boolean);
var
  I: Integer;
begin
  if not Detected then
    Exit;
  for I := 0 to WizardForm.ComponentsList.Items.Count - 1 do
  begin
    if WizardForm.ComponentsList.ItemCaption[I] = Caption then
      WizardForm.ComponentsList.Checked[I] := False;
  end;
end;

var
  ComponentsDetectionDone: Boolean;

(* app 常數要到使用者選完安裝目錄(wpSelectDir 頁)之後才會初始化;
   IsFfmpegInstalled 會展開 app 常數,若在 InitializeWizard(精靈剛建立、
   使用者還沒看到任何畫面時)呼叫會直接丟執行期錯誤(Inno Setup 已知限制)。
   改成等精靈要顯示「選擇元件」頁(wpSelectComponents,在 wpSelectDir 之後)
   時才做偵測,且只做一次。 *)
procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpSelectComponents) and not ComponentsDetectionDone then
  begin
    ComponentsDetectionDone := True;
    if not ComponentsParamGiven then
    begin
      UncheckComponentIfDetected('ffmpeg(影片解析度偵測用)', IsFfmpegInstalled);
      UncheckComponentIfDetected('MKVToolNix(MKV 字幕封裝/處理用)', IsMkvToolNixInstalled);
    end;
  end;
end;
