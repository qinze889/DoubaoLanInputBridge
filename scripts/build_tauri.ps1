param(
    [switch]$SkipNpmInstall
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DesktopRoot = Join-Path $ProjectRoot "desktop"
$TauriRoot = Join-Path $DesktopRoot "src-tauri"
$PythonExe = "C:\Users\0\AppData\Local\Programs\Python\Python312\python.exe"
$TargetTriple = "x86_64-pc-windows-msvc"
$SidecarName = "bridge-service"
$SidecarDist = Join-Path $DesktopRoot "sidecar-dist"
$SidecarBuild = Join-Path $DesktopRoot "sidecar-build"
$SidecarTarget = Join-Path $TauriRoot "binaries\$SidecarName-$TargetTriple.exe"
$Assets = Join-Path $ProjectRoot "assets"
$ServiceEntry = Join-Path $ProjectRoot "src\gui_app.py"

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Python 3.12 not found: $PythonExe"
}

New-Item -ItemType Directory -Path (Split-Path -Parent $SidecarTarget) -Force | Out-Null

& $PythonExe -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --console `
    --name $SidecarName `
    --distpath $SidecarDist `
    --workpath $SidecarBuild `
    --specpath $SidecarBuild `
    --add-data "$Assets;assets" `
    $ServiceEntry

if ($LASTEXITCODE -ne 0) {
    throw "Sidecar build failed with exit code $LASTEXITCODE"
}

Copy-Item -LiteralPath (Join-Path $SidecarDist "$SidecarName.exe") -Destination $SidecarTarget -Force

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
