; Desinstalar também tira o Orbit da inicialização do Windows (a entrada é criada pelo próprio app).
!macro customUnInstall
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "Orbit.Beta"
!macroend
