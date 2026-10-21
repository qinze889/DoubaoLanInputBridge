param(
    [switch]$SkipNpmInstall,
    [string]$PythonExe = "",
    [string]$Cloudflared = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DesktopRoot = Join-Path $ProjectRoot "desktop"
$TauriRoot = Join-Path $DesktopRoot "src-tauri"
if (-not $PythonExe) { $PythonExe = (Get-Command python -ErrorAction Stop).Source }
$TargetTriple = "x86_64-pc-windows-msvc"
$SidecarName = "bridge-service"
$SidecarDist = Join-Path $DesktopRoot "sidecar-dist"
$SidecarBuild = Join-Path $DesktopRoot "sidecar-build"
$SidecarTarget = Join-Path $TauriRoot "binaries\$SidecarName-$TargetTriple.exe"
$Assets = Join-Path $ProjectRoot "assets"
$ServiceEntry = Join-Path $ProjectRoot "src\gui_app.py"
if (-not $Cloudflared) { $Cloudflared = Join-Path $ProjectRoot "tools\cloudflared\cloudflared.exe" }
if (-not (Test-Path -LiteralPath $Cloudflared)) { throw "Build requires cloudflared.exe from the official Cloudflare release." }

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Python 3.12 not found: $PythonExe"
}

New-Item -ItemType Directory -Path (Split-Path -Parent $SidecarTarget) -Force | Out-Null

& $PythonExe -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --console `
    --exclude-module qt_app `
    --exclude-module qt_peers `
    --exclude-module PySide6 `
    --name $SidecarName `
    --distpath $SidecarDist `
    --workpath $SidecarBuild `
    --specpath $SidecarBuild `
    --add-data "$Assets;assets" `
    --add-data "$ProjectRoot\docs\cloudflared-LICENSE;." `
    --add-binary "$Cloudflared;." `
    $ServiceEntry

if ($LASTEXITCODE -ne 0) {
    throw "Sidecar build failed with exit code $LASTEXITCODE"
}

Copy-Item -LiteralPath (Join-Path $SidecarDist "$SidecarName.exe") -Destination $SidecarTarget -Force

# Also provide a Qt portable executable with the same sharing protocol.
& $PythonExe -m PyInstaller --noconfirm --clean --onefile --noconsole `
    --name "Shengjian-windows-x64" --distpath (Join-Path $ProjectRoot "dist") `
    --workpath (Join-Path $ProjectRoot "build\windows-qt") `
    --specpath (Join-Path $ProjectRoot "build\windows-qt") `
    --icon "$Assets\app.ico" --add-data "$Assets;assets" --add-binary "$Cloudflared;." `
    --add-data "$ProjectRoot\docs\cloudflared-LICENSE;." `
    (Join-Path $ProjectRoot "src\qt_app.py")
if ($LASTEXITCODE -ne 0) { throw "Portable app build failed." }

Push-Location $DesktopRoot
try {
    if (-not $SkipNpmInstall) {
        npm install
        if ($LASTEXITCODE -ne 0) {
            throw "npm install failed with exit code $LASTEXITCODE"
        }
    }
    npm run tauri build
    if ($LASTEXITCODE -ne 0) {
        throw "Tauri build failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

$InstallerDir = Join-Path $TauriRoot "target\release\bundle\nsis"
Get-ChildItem -LiteralPath $InstallerDir -Filter "*.exe" | Select-Object FullName, Length, LastWriteTime
