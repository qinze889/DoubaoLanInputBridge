from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "scripts" / "build.ps1"
RELEASE_SCRIPT = ROOT / "scripts" / "make_release.ps1"
GITIGNORE = ROOT / ".gitignore"


def test_build_script_preserves_running_app_by_default_and_can_replace_explicitly():
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert "param(" in script
    assert "[switch]$ReplaceRunningApp" in script
    assert "$TargetExe" in script
    assert "$BuildName" in script
    assert "Stop-Process" in script
    assert 'DoubaoLanInputBridge_zh2en_update' in script
    assert "if ($ReplaceRunningApp)" in script
    assert "Start-Process -FilePath $TargetExe" not in script


def test_build_script_limits_process_stop_to_project_dist_exe():
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert "$_.Path -eq $TargetExe" in script


def test_build_script_bundles_paper_background_asset():
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert "--add-data" in script
    assert "assets\\paper000.jpg;assets" in script


def test_build_script_sets_custom_app_icon():
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert '--icon "$Root\\assets\\app.ico"' in script
    assert 'assets\\app.ico;assets' in script


def test_build_script_installs_qrcode_dependency_for_qr_panel():
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert "$QrToolDir" in script
    assert "pip install --target $QrToolDir qrcode" in script
    assert "$PySideToolDir;$QrToolDir;$ToolDir;$Root\\src" in script


def test_build_script_uses_qt_entrypoint_and_installs_pyside6():
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert '$Src = Join-Path $Root "src\\qt_app.py"' in script
    assert "$PySideToolDir" in script
    assert "pip install --target $PySideToolDir PySide6" in script
    assert '(Join-Path $Root "src\\gui_app.py")' in script


def test_release_script_creates_distribution_folder_without_private_data():
    script = RELEASE_SCRIPT.read_text(encoding="utf-8")

    assert "release" in script
    assert "DoubaoLanInputBridge-$Version" in script
    assert "DoubaoLanInputBridge_zh2en.exe" in script
    assert "index.html" in script
    assert "README-FIRST-RUN.txt" in script
    assert "release-manifest.json" in script
    assert "DoubaoLanInputBridge-$Version-windows.zip" in script
    assert "Compress-Archive" in script
    assert "Copy-Item -LiteralPath $SourceExe" in script
    assert "DoubaoLanInputBridge_zh2en_update.exe" in script
    assert "LOCALAPPDATA" not in script
    assert "access_key.txt" not in script
    assert "minimax_api_key.txt" not in script
    assert "uploads" not in script
    assert "service.log" not in script


def test_release_script_has_human_readable_html_guide():
    script = RELEASE_SCRIPT.read_text(encoding="utf-8")

    assert "How to use DoubaoLanInputBridge" in script
    assert "Scan the QR code" in script
    assert "MiniMax API Key" in script
    assert "Copy diagnostics" in script
    assert "Troubleshooting" in script
    assert "same Wi-Fi" in script


def test_gitignore_excludes_release_temporary_artifacts():
    content = GITIGNORE.read_text(encoding="utf-8")

    assert "backups/" in content
    assert "dist/*_update.exe" in content
    assert "docs/git-version-report.html" in content
