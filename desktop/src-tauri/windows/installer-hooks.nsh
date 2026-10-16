; Preserve the existing install directory when upgrading from the former brand.
!macro NSIS_HOOK_PREINSTALL
  ReadRegStr $0 HKCU "Software\qinze\豆包语音输入桥" ""
  ${If} $0 != ""
    StrCpy $INSTDIR $0
    SetOutPath $INSTDIR
  ${EndIf}
!macroend

; Remove obsolete branding metadata and shortcuts after the new app is registered.
!macro NSIS_HOOK_POSTINSTALL
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\豆包语音输入桥"
  DeleteRegKey HKCU "Software\qinze\豆包语音输入桥"
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "豆包语音输入桥"
  Delete "$DESKTOP\豆包语音输入桥.lnk"
  Delete "$SMPROGRAMS\豆包语音输入桥.lnk"
!macroend
