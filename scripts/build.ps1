param(
    [switch]$ReplaceRunningApp,
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"

if (-not $Python) { $Python = (Get-Command python -ErrorAction Stop).Source }
$Root = Split-Path -Parent $PSScriptRoot
$ToolDir = Join-Path $Root "tools\pyinstaller"
$QrToolDir = Join-Path $Root "tools\qrcode"
$PySideToolDir = Join-Path $Root "tools\pyside6"
$Src = Join-Path $Root "src\qt_app.py"
$Dist = Join-Path $Root "dist"
$Build = Join-Path $Root "build"
$TargetExe = [System.IO.Path]::GetFullPath((Join-Path $Dist "DoubaoLanInputBridge_zh2en.exe"))
$BuildName = "DoubaoLanInputBridge_zh2en"

if (Test-Path -LiteralPath $TargetExe) {
    $RunningApp = Get-Process -Name "DoubaoLanInputBridge_zh2en" -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $TargetExe }
    if ($RunningApp) {
        if ($ReplaceRunningApp) {
            $RunningApp | Stop-Process
            $RunningApp | Wait-Process -Timeout 10
        } else {
            $BuildName = "DoubaoLanInputBridge_zh2en_update"
            $TargetExe = [System.IO.Path]::GetFullPath((Join-Path $Dist "$BuildName.exe"))
        }
    }
}

if (!(Test-Path -LiteralPath $ToolDir)) {
    & $Python -m pip install --target $ToolDir pyinstaller
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if (!(Test-Path -LiteralPath $QrToolDir)) {
    & $Python -m pip install --target $QrToolDir qrcode
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if (!(Test-Path -LiteralPath $PySideToolDir)) {
    & $Python -m pip install --target $PySideToolDir PySide6
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$env:PYTHONPATH = "$PySideToolDir;$QrToolDir;$ToolDir;$Root\src"

& $Python -m pytest (Join-Path $Root "tests")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python -m py_compile $Src `
    (Join-Path $Root "src\gui_app.py") `
    (Join-Path $Root "tests\test_html_translate.py") `
    (Join-Path $Root "tests\test_update_check.py") `
    (Join-Path $Root "tests\test_prompt_enrichment.py") `
    (Join-Path $Root "tests\test_file_clipboard.py") `
    (Join-Path $Root "tests\test_build_script.py") `
    (Join-Path $Root "tests\test_local_update_source.py") `
    (Join-Path $Root "scripts\import_prompts_chat.py") `
    (Join-Path $Root "scripts\generate_app_icon.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $Python -m PyInstaller `
    --onefile `
    --noconsole `
    --name $BuildName `
    --icon "$Root\assets\app.ico" `
    --add-data "$Root\assets\paper000.jpg;assets" `
    --add-data "$Root\assets\app.ico;assets" `
    --distpath $Dist `
    --workpath $Build `
    --specpath $Build `
    $Src
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Get-Item -LiteralPath $TargetExe
