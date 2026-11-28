; Bo cai iPhone Farm cho Windows (Inno Setup 6). Dung boi packaging/build.sh:
;   ISCC /DIpfVer=<ban> /DIpfStage=<thu muc da gom> /DIpfOutDir=<thu muc ra> /DIpfOutName=<ten tep> installer.iss
; (ten bien co tien to Ipf: "Ver" la bien co san cua bo tien xu ly Inno Setup, dat de len la hong)
; Cai vao %LOCALAPPDATA%\iPhoneFarm (khong can quyen admin; app ghi du lieu vao app\data ngay trong thu muc cai).
; Chu trong tep nay viet khong dau de khong phu thuoc bang ma cua may dung.

#ifndef IpfVer
  #define IpfVer "dev"
#endif
#ifndef IpfStage
  #define IpfStage "..\..\build\stage"
#endif
#ifndef IpfOutDir
  #define IpfOutDir "..\..\dist"
#endif
#ifndef IpfOutName
  #define IpfOutName "iPhoneFarm-Setup"
#endif

[Setup]
AppId={{6C0E5F0B-5D3A-4E0B-9C55-1F7B1E6F2A41}
AppName=iPhone Farm
AppVersion={#IpfVer}
AppPublisher=Delify Solutions
DefaultDirName={localappdata}\iPhoneFarm
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#IpfOutDir}
OutputBaseFilename={#IpfOutName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=iPhone Farm {#IpfVer}
CloseApplications=yes
SetupLogging=yes

[InstallDelete]
; moi truong cu duoc dung lai tu dau; du lieu nguoi dung (app\data) KHONG bi dong toi
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\wheels"
Type: filesandordirs; Name: "{app}\models"

[Files]
Source: "{#IpfStage}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\iPhone Farm"; Filename: "{app}\run.bat"; WorkingDir: "{app}"; Comment: "iPhone Farm Manager"
Name: "{autodesktop}\iPhone Farm"; Filename: "{app}\run.bat"; WorkingDir: "{app}"; Comment: "iPhone Farm Manager"

[Run]
Filename: "{app}\run.bat"; WorkingDir: "{app}"; Description: "Mo iPhone Farm"; Flags: postinstall nowait skipifsilent shellexec; Check: EnvOk

[UninstallDelete]
; .venv tao luc cai (khong nam trong danh sach tep cua bo cai). app\data (du lieu nguoi dung) duoc giu lai.
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\wheels"
Type: files; Name: "{app}\install.log"

[Code]
var
  EnvFailed: Boolean;

procedure CurStepChanged(CurStep: TSetupStep);
var
  rc: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    WizardForm.StatusLabel.Caption := 'Dang cai moi truong Python va thu vien (1-3 phut, khong can mang)...';
    WizardForm.FilenameLabel.Caption := '';
    rc := -1;
    if (not Exec(ExpandConstant('{cmd}'), '/c ""' + ExpandConstant('{app}\install-env.bat') + '""', ExpandConstant('{app}'),
                 SW_HIDE, ewWaitUntilTerminated, rc)) or (rc <> 0) or (not FileExists(ExpandConstant('{app}\.venv\ipf-ok'))) then
    begin
      EnvFailed := True;
      Log('install-env.bat that bai, ma ' + IntToStr(rc));
      { SuppressibleMsgBox: khi cai im lang (/SUPPRESSMSGBOXES) khong hien hop thoai, khong treo }
      SuppressibleMsgBox('Cai moi truong Python KHONG thanh cong - app chua chay duoc.' + #13#10 + #13#10 +
             'Xem chi tiet trong tep:' + #13#10 + ExpandConstant('{app}\install.log'), mbError, MB_OK, IDOK);
    end;
  end;
end;

function EnvOk: Boolean;
begin
  Result := not EnvFailed;
end;

function GetCustomSetupExitCode: Integer;
begin
  if EnvFailed then
    Result := 3
  else
    Result := 0;
end;
