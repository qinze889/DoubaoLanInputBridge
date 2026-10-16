from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLISH_SCRIPT = ROOT / "scripts" / "publish_local_update.ps1"


def test_publish_local_update_script_generates_manifest_and_can_configure_user():
    script = PUBLISH_SCRIPT.read_text(encoding="utf-8")

    assert "[switch]$ConfigureCurrentUser" in script
    assert "[string]$UpdateHost" in script
    assert "[int]$UpdatePort" in script
    assert "local_update_source" in script
    assert "Get-FileHash" in script
    assert "ConvertTo-Json" in script
    assert "Set-Content -LiteralPath $ManifestPath -Encoding UTF8" in script
    assert 'DoubaoLanInputBridge\\local_update_source' in script
    assert "mirror_source" in script
    assert "update.json" in script
    assert "update_url.txt" in script
    assert "__updates__/update.json" in script
    assert "__updates__/$PackageName" in script
    assert "sha256" in script
    assert "Get-LanIPv4Address" in script
    assert "DoubaoLanInputBridge_zh2en_update.exe" in script
    assert '[string]$UpdateHost = "192.168.1.63"' in script
    assert "192\\.168\\." in script
