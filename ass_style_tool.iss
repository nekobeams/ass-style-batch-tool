; -- ASS 字幕樣式批次工具 Inno Setup Script --
; AppId 一經發佈絕不可再更改(否則使用者升級會被視為全新安裝,留下舊版殘留)

#define MyAppName "ASS 字幕樣式批次工具"
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
Source: "installer_payload\ffmpeg\LICENSE*"; DestDir: "{app}\licenses\ffmpeg"; Components: ffmpeg; Flags: ignoreversion
#endif
#if DirExists("installer_payload\mkvtoolnix")
Source: "installer_payload\mkvtoolnix\*.exe"; DestDir: "{app}\tools"; Components: mkvtoolnix; Flags: ignoreversion
Source: "installer_payload\mkvtoolnix\LICENSE*"; DestDir: "{app}\licenses\mkvtoolnix"; Components: mkvtoolnix; Flags: ignoreversion
#endif

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\解除安裝 {#MyAppName}"; Filename: "{uninstallexe}"

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
  Result := IsToolOnPath('ffmpeg.exe');
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

procedure InitializeWizard();
begin
  if ComponentsParamGiven then
    Exit;
  UncheckComponentIfDetected('ffmpeg(影片解析度偵測用)', IsFfmpegInstalled);
  UncheckComponentIfDetected('MKVToolNix(MKV 字幕封裝/處理用)', IsMkvToolNixInstalled);
end;
