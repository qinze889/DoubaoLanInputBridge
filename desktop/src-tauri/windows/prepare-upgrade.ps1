param([Parameter(Mandatory=$true)][string]$InstallDir)

$ErrorActionPreference = 'Stop'
$root = [System.IO.Path]::GetFullPath($InstallDir).TrimEnd('\')
$executables = @((Join-Path $root 'doubao-lan-input-bridge.exe'), (Join-Path $root 'bridge-service.exe'))

# An abruptly closed older Tauri app can leave both PyInstaller processes alive.
# Match full paths so another application's similarly named service is untouched.
$processes = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -in $executables })
foreach ($process in $processes) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
}
for ($attempt = 0; $attempt -lt 50; $attempt++) {
    $remaining = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -in $executables })
    if (-not $remaining.Count) { break }
    Start-Sleep -Milliseconds 100
}
if ($remaining.Count) { throw 'The previous application could not be stopped.' }

$service = Join-Path $root 'bridge-service.exe'
if (Test-Path -LiteralPath $service) {
    # Keep the old executable until the new installer has copied its payload.
    Move-Item -LiteralPath $service -Destination ($service + '.pre-upgrade') -Force
}
