' Inicia o Orbit escondido (sem janela de console). Usado no logon.
Set sh = CreateObject("WScript.Shell")
dir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir
sh.Run """" & dir & "\node_modules\electron\dist\electron.exe"" """ & dir & """", 0, False
