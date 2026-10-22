param([Parameter(Mandatory=$true)][string]$InstallDir)

$ErrorActionPreference = 'Stop'
Add-Type @'
using System.Runtime.InteropServices;
using System.Text;
public static class ShengjianUpgradePath {
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    public static extern uint GetLongPathName(string path, StringBuilder buffer, uint length);
}
'@
function Resolve-ExecutablePath([string]$Path) {
    if (-not $Path) { return '' }
    $buffer = [System.Text.StringBuilder]::new(32768)
    if ([ShengjianUpgradePath]::GetLongPathName($Path, $buffer, $buffer.Capacity) -gt 0) {
        return $buffer.ToString().TrimEnd('\')
    }
    return [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
}
$root = Resolve-ExecutablePath $InstallDir
$executables = @((Join-Path $root 'doubao-lan-input-bridge.exe'), (Join-Path $root 'bridge-service.exe'))

# An abruptly closed older Tauri app can leave both PyInstaller processes alive.
# Match full paths so another application's similarly named service is untouched.
$processes = @(Get-Process | Where-Object { (Resolve-ExecutablePath $_.Path) -in $executables })
foreach ($process in $processes) {
    if (Get-Process -Id $process.Id -ErrorAction SilentlyContinue) {
        Start-Process -FilePath "$env:SystemRoot\System32\taskkill.exe" -ArgumentList @('/PID', [string]$process.Id, '/T', '/F') -NoNewWindow -Wait
    }
}
for ($attempt = 0; $attempt -lt 50; $attempt++) {
    $remaining = @(Get-Process | Where-Object { (Resolve-ExecutablePath $_.Path) -in $executables })
    if (-not $remaining.Count) { break }
    Start-Sleep -Milliseconds 100
}
if ($remaining.Count) { throw 'The previous application could not be stopped.' }

$service = Join-Path $root 'bridge-service.exe'
if (Test-Path -LiteralPath $service) {
    # Keep the old executable until the new installer has copied its payload.
    Move-Item -LiteralPath $service -Destination ($service + '.pre-upgrade') -Force
}
