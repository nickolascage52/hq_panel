# Запуск AI Delivery Team через WSL
# Использование: powershell -ExecutionPolicy Bypass -File 10_TMUX/scripts/start_team_from_powershell.ps1
# Или: .\start_team_from_powershell.ps1

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "../..")

# Конвертируем Windows-путь в WSL-путь (C:\... -> /mnt/c/...)
$path = $ProjectRoot.Path -replace '\\', '/'
if ($path -match '^([A-Za-z]):') {
    $WslPath = '/mnt/' + $matches[1].ToLower() + $path.Substring(2)
} else {
    $WslPath = $path
}

Write-Host "Проект: $ProjectRoot"
Write-Host "WSL путь: $WslPath"
Write-Host ""
Write-Host "Запуск tmux в WSL..."
Write-Host ""

wsl -e bash -c "cd '$WslPath' && bash 10_TMUX/scripts/start_team.sh"
