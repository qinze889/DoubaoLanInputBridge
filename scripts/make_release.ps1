param(
    [string]$Version = "",
    [string]$SourceExe = "",
    [string]$OutputRoot = ""
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = (Get-Content -LiteralPath (Join-Path $Root "VERSION") -Encoding UTF8 -Raw).Trim()
}
if ([string]::IsNullOrWhiteSpace($SourceExe)) {
    $DefaultExe = Join-Path $Root "dist\DoubaoLanInputBridge_zh2en.exe"
    $UpdateExe = Join-Path $Root "dist\DoubaoLanInputBridge_zh2en_update.exe"
    if ((Test-Path -LiteralPath $UpdateExe) -and (!(Test-Path -LiteralPath $DefaultExe) -or ((Get-Item -LiteralPath $UpdateExe).LastWriteTime -gt (Get-Item -LiteralPath $DefaultExe).LastWriteTime))) {
        $SourceExe = $UpdateExe
    } else {
        $SourceExe = $DefaultExe
    }
}
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $Root "release"
}

$SourceExe = [System.IO.Path]::GetFullPath($SourceExe)
$OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
$ReleaseDir = Join-Path $OutputRoot "DoubaoLanInputBridge-$Version"
$ZipPath = Join-Path $OutputRoot "DoubaoLanInputBridge-$Version-windows.zip"
$ReleaseExe = Join-Path $ReleaseDir "DoubaoLanInputBridge_zh2en.exe"
$FirstRunReadme = Join-Path $ReleaseDir "README-FIRST-RUN.txt"
$HtmlGuide = Join-Path $ReleaseDir "index.html"
$ManifestPath = Join-Path $ReleaseDir "release-manifest.json"

if (!(Test-Path -LiteralPath $SourceExe)) {
    throw "Source exe not found: $SourceExe"
}
if (!(Test-Path -LiteralPath $ReleaseDir)) {
    New-Item -ItemType Directory -Path $ReleaseDir | Out-Null
}

Copy-Item -LiteralPath $SourceExe -Destination $ReleaseExe -Force
$Hash = (Get-FileHash -LiteralPath $ReleaseExe -Algorithm SHA256).Hash.ToLowerInvariant()

$FirstRunText = @(
    "DoubaoLanInputBridge $Version",
    "",
    "First run:",
    "1. Double-click DoubaoLanInputBridge_zh2en.exe.",
    "2. The desktop app starts the LAN service and shows a QR code.",
    "3. Connect phone and PC to the same Wi-Fi, then scan the QR code.",
    "4. For prompt enrichment, click Config in the desktop app and set a MiniMax API Key.",
    "5. If something fails, click Copy diagnostics and send it to the maintainer.",
    "",
    "Distribution notes:",
    "- This folder contains only distributable files.",
    "- Each PC creates its own runtime key, config, logs, and temporary files.",
    "- Do not distribute the maintainer's runtime data directory."
) -join [Environment]::NewLine
Set-Content -LiteralPath $FirstRunReadme -Encoding UTF8 -Value $FirstRunText

$HtmlText = @(
    "<!doctype html>",
    "<html lang=""en"">",
    "<head>",
    "  <meta charset=""utf-8"">",
    "  <meta name=""viewport"" content=""width=device-width, initial-scale=1"">",
    "  <title>How to use DoubaoLanInputBridge</title>",
    "  <style>",
    "    body { margin: 0; font-family: Segoe UI, Arial, sans-serif; background: #f4f7f8; color: #132329; }",
    "    main { max-width: 880px; margin: 0 auto; padding: 40px 24px 56px; }",
    "    h1 { font-size: 36px; margin: 0 0 10px; }",
    "    h2 { margin-top: 30px; font-size: 22px; }",
    "    .lead { color: #52646d; font-size: 17px; line-height: 1.7; }",
    "    .panel { background: white; border: 1px solid #d9e5e5; border-radius: 8px; padding: 22px; margin: 18px 0; }",
    "    .steps { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; }",
    "    .step { background: #f8fbfb; border: 1px solid #d9e5e5; border-radius: 8px; padding: 16px; }",
    "    code { background: #eef5f5; padding: 2px 6px; border-radius: 4px; }",
    "    li { margin: 8px 0; line-height: 1.55; }",
    "  </style>",
    "</head>",
    "<body>",
    "  <main>",
    "    <h1>How to use DoubaoLanInputBridge</h1>",
    "    <p class=""lead"">Send text, images, and small files between your phone and this Windows PC through the local network.</p>",
    "    <section class=""panel"">",
    "      <h2>First run</h2>",
    "      <div class=""steps"">",
    "        <div class=""step""><strong>1. Start the app</strong><br>Double-click <code>DoubaoLanInputBridge_zh2en.exe</code>.</div>",
    "        <div class=""step""><strong>2. Scan the QR code</strong><br>Keep phone and PC on the same Wi-Fi, then scan the QR code in the desktop app.</div>",
    "        <div class=""step""><strong>3. Send content</strong><br>Use the phone page to send text, images, PDFs, Word files, and other small files.</div>",
    "      </div>",
    "    </section>",
    "    <section class=""panel"">",
    "      <h2>Optional MiniMax API Key</h2>",
    "      <p>Prompt enrichment needs a MiniMax API Key. In the desktop app, click <strong>Config</strong>, paste the key, and confirm. The key stays on this PC.</p>",
    "    </section>",
    "    <section class=""panel"">",
    "      <h2>Troubleshooting</h2>",
    "      <ul>",
    "        <li>If the phone cannot open the page, confirm phone and PC are on the same Wi-Fi.</li>",
    "        <li>If Windows Firewall prompts, allow private network access.</li>",
    "        <li>If the port is occupied, the app automatically tries the next port.</li>",
    "        <li>Click <strong>Copy diagnostics</strong> and send the copied text to the maintainer when asking for help.</li>",
    "      </ul>",
    "    </section>",
    "  </main>",
    "</body>",
    "</html>"
) -join [Environment]::NewLine
Set-Content -LiteralPath $HtmlGuide -Encoding UTF8 -Value $HtmlText

$Manifest = [ordered]@{
    name = "DoubaoLanInputBridge"
    version = $Version
    exe = "DoubaoLanInputBridge_zh2en.exe"
    sha256 = $Hash
    guide = "index.html"
    zip = "DoubaoLanInputBridge-$Version-windows.zip"
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    includes_private_runtime_data = $false
}
$Manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ManifestPath -Encoding ASCII

Compress-Archive -LiteralPath $ReleaseDir -DestinationPath $ZipPath -Force
$ZipHash = (Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()

[ordered]@{
    release_dir = $ReleaseDir
    zip = $ZipPath
    exe = $ReleaseExe
    readme = $FirstRunReadme
    guide = $HtmlGuide
    manifest = $ManifestPath
    sha256 = $Hash
    zip_sha256 = $ZipHash
} | ConvertTo-Json -Depth 5
