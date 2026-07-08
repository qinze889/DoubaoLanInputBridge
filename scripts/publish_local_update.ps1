param(
    [string]$Version = "",
    [string]$Notes = "",
    [string]$SourceExe = "",
    [string]$OutputDir = "",
    [string]$UpdateHost = "192.168.1.63",
    [int]$UpdatePort = 8765,
    [switch]$ConfigureCurrentUser
)

$ErrorActionPreference = "Stop"

function Get-LanIPv4Address {
    $addresses = @()
    try {
        $addresses += [System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) |
            Where-Object { $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork } |
            ForEach-Object { $_.IPAddressToString }
    } catch {
    }
    try {
        $socket = [System.Net.Sockets.Socket]::new(
            [System.Net.Sockets.AddressFamily]::InterNetwork,
            [System.Net.Sockets.SocketType]::Dgram,
            [System.Net.Sockets.ProtocolType]::Udp
        )
        $socket.Connect("8.8.8.8", 80)
        $addresses += $socket.LocalEndPoint.Address.IPAddressToString
        $socket.Close()
    } catch {
    }
    $addresses = $addresses | Where-Object { $_ -match '^192\.168\.' } | Select-Object -Unique
    if ($addresses.Count -gt 0) {
        return $addresses[0]
    }
    return "127.0.0.1"
}

$Root = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = (Get-Content -LiteralPath (Join-Path $Root "VERSION") -Encoding UTF8 -Raw).Trim()
}
if ([string]::IsNullOrWhiteSpace($Notes)) {
    $Notes = "Local update source version $Version"
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
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $Root "local_update_source"
}

$SourceExe = [System.IO.Path]::GetFullPath($SourceExe)
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
if ([string]::IsNullOrWhiteSpace($UpdateHost)) {
    $UpdateHost = Get-LanIPv4Address
}
if (!(Test-Path -LiteralPath $SourceExe)) {
    throw "Source exe not found: $SourceExe"
}
if (!(Test-Path -LiteralPath $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
}

$safeVersion = $Version -replace '[^0-9A-Za-z._-]', '_'
if ([string]::IsNullOrWhiteSpace($safeVersion)) {
    $safeVersion = "local"
}
$PackageName = "DoubaoLanInputBridge_zh2en-$safeVersion.exe"
$PackagePath = Join-Path $OutputDir $PackageName
$ManifestPath = Join-Path $OutputDir "update.json"

Copy-Item -LiteralPath $SourceExe -Destination $PackagePath -Force
$Hash = (Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256).Hash.ToLowerInvariant()
$PackageUrl = "http://${UpdateHost}:${UpdatePort}/__updates__/$PackageName"

$Manifest = [ordered]@{
    version = $Version
    url = $PackageUrl
    sha256 = $Hash
    notes = $Notes
}
$Manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ManifestPath -Encoding ASCII

$ManifestUrl = "http://${UpdateHost}:${UpdatePort}/__updates__/update.json"
if ($ConfigureCurrentUser) {
    $LocalAppData = $env:LOCALAPPDATA
    if ([string]::IsNullOrWhiteSpace($LocalAppData)) {
        $LocalAppData = [Environment]::GetFolderPath("LocalApplicationData")
    }
    $AppDataDir = Join-Path $LocalAppData "DoubaoLanInputBridge"
    if (!(Test-Path -LiteralPath $AppDataDir)) {
        New-Item -ItemType Directory -Path $AppDataDir | Out-Null
    }
    Set-Content -LiteralPath (Join-Path $AppDataDir "update_url.txt") -Encoding ASCII -Value $ManifestUrl
}

[ordered]@{
    manifest = $ManifestPath
    manifest_url = $ManifestUrl
    package = $PackagePath
    update_host = $UpdateHost
    update_port = $UpdatePort
    sha256 = $Hash
    configured_current_user = [bool]$ConfigureCurrentUser
} | ConvertTo-Json -Depth 5
