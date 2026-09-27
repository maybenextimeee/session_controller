; Установщик Session Controller (Inno Setup 6: https://jrsoftware.org/isinfo.php).
;
; Сначала собери exe (packaging/SessionController.spec), потом из корня репозитория:
;     ISCC.exe /DAppVersion=0.4.0 packaging\installer.iss
; Результат: dist\SessionController-Setup-<версия>.exe
;
; Ставится для текущего пользователя в %LOCALAPPDATA%\Programs — права
; администратора не нужны, у каждого пользователя Windows своя копия.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "Session Controller"
#define AppExe "SessionController.exe"
#define RunKey "Software\Microsoft\Windows\CurrentVersion\Run"

[Setup]
AppId={{8B37DFCD-D8ED-4958-9572-DE8152E25885}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=maybenextimeee
AppPublisherURL=https://github.com/maybenextimeee/session_controller
AppSupportURL=https://github.com/maybenextimeee/session_controller/issues
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=SessionController-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Программа создаёт этот мьютекс, пока работает (APP_MUTEX в app.py). Если она
; запущена, установщик попросит её закрыть. Закрывать её сам установщик не должен:
; для программы это выглядело бы как выключение Windows, и она завершила бы сессию.
AppMutex=SessionControllerMutex
CloseApplications=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
russian.AutoStart=Запускать Session Controller вместе с Windows (рекомендуется)
english.AutoStart=Start Session Controller with Windows (recommended)
russian.SessionActive=Сейчас идёт сессия Session Controller.%n%nЕсли удалить программу сейчас, всё, что появилось за сессию, останется на компьютере. Лучше сначала завершить сессию в программе.%n%nВсё равно удалить?
english.SessionActive=A Session Controller session is in progress.%n%nIf you uninstall now, everything from this session will stay on the computer. It is better to end the session in the app first.%n%nUninstall anyway?

[Tasks]
Name: "autostart"; Description: "{cm:AutoStart}"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\SessionController\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; При обновлении убираем файлы прошлой версии, чтобы не смешивались библиотеки.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; То же значение программа меняет галочкой «Запускать вместе с Windows» (autostart.py).
Root: HKCU; Subkey: "{#RunKey}"; ValueType: string; ValueName: "SessionController"; ValueData: """{app}\{#AppExe}"" --minimized"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeUninstall(): Boolean;
begin
  Result := True;
  if FileExists(ExpandConstant('{localappdata}\SessionController\session.json')) then
    Result := MsgBox(CustomMessage('SessionActive'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  { Автозапуск могли включить галочкой в самой программе, а не в установщике. }
  if CurUninstallStep = usPostUninstall then
    RegDeleteValue(HKEY_CURRENT_USER, '{#RunKey}', 'SessionController');
end;
