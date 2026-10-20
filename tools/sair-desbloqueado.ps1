# Sai da Área de Trabalho Remota deixando o PC DESBLOQUEADO no monitor de casa (em vez da tela de bloqueio).
# Use no lugar de "desconectar". Pede administrador (o tscon só funciona assim).
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Start-Process powershell -Verb RunAs -WindowStyle Hidden -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}
$session = (Get-Process -Id $PID).SessionId
& "$env:WINDIR\System32\tscon.exe" $session /dest:console
