; Preserve the existing install directory when upgrading from the former brand.
!define SHENGJIAN_HOOK_DIR "${__FILEDIR__}"
!macro NSIS_HOOK_PREINSTALL
  ReadRegStr $0 HKCU "Software\qinze\豆包语音输入桥" ""
  ${If} $0 != ""
    StrCpy $INSTDIR $0
    SetOutPath $INSTDIR
  ${EndIf}
  InitPluginsDir
  File "/oname=$PLUGINSDIR\prepare-upgrade.ps1" "${SHENGJIAN_HOOK_DIR}\prepare-upgrade.ps1"
  nsExec::ExecToStack '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\prepare-upgrade.ps1" -InstallDir "$INSTDIR"'
  Pop $0
  Pop $1
  ${If} $0 != 0
    SetErrorLevel 1
    Abort "Unable to stop the previous Shengjian service. Close the app and retry."
  ${EndIf}
  SetOverwrite on
!macroend

; Remove obsolete branding metadata and shortcuts after the new app is registered.
!macro NSIS_HOOK_POSTINSTALL
  IfFileExists "$INSTDIR\bridge-service.exe" +3 0
    SetErrorLevel 1
    Abort "Shengjian service was not installed."
  Delete "$INSTDIR\bridge-service.exe.pre-upgrade"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\豆包语音输入桥"
  DeleteRegKey HKCU "Software\qinze\豆包语音输入桥"
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "豆包语音输入桥"
  Delete "$DESKTOP\豆包语音输入桥.lnk"
  Delete "$SMPROGRAMS\豆包语音输入桥.lnk"
!macroend
