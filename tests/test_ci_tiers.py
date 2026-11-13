"""CI must be cheap for drafts and strict for releasable source commits."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"
FULL_IF = "if: github.event_name != 'pull_request' || github.event.pull_request.draft == false"


def workflow(name):
    return (WF / name).read_text(encoding="utf-8")


def test_draft_pr_runs_fast_checks_without_packaging():
    fast = workflow("fast-checks.yml")
    assert "pull_request:" in fast
    assert "ready_for_review" in fast
    assert "npm run lint" in fast
    assert "npm run build" in fast
    assert "python -m compileall -q src server" in fast
    assert "tests/test_release_assets.py" in fast
    assert "tests/test_tauri_desktop_ui.py" in fast
    assert "scripts/build_tauri.ps1" not in fast
    assert "scripts/build_macos.sh" not in fast
    assert "upload-artifact" not in fast


def test_ready_pr_and_main_keep_full_windows_and_apple_gates():
    windows = workflow("windows-client.yml")
    apple = workflow("apple-clients.yml")
    for content, expected_jobs in ((windows, 2), (apple, 2)):
        assert "types: [opened, synchronize, reopened, ready_for_review]" in content
        assert content.count(FULL_IF) == expected_jobs
        assert "branches: [main]" in content
        assert "workflow_dispatch:" in content
        assert "retention-days: ${{ github.event_name == 'pull_request' && 7 || 30 }}" in content

    assert "npm run test:ui" in windows
    assert "smoke_windows_installer.py" in windows
    assert "smoke_packaged_rtc.py" in windows
    assert "Verify mobile Web at small viewport sizes" not in windows or "smoke_mobile_web_ui.cjs" in windows
    assert "verify_macos_package.py" in apple
    assert "Build iOS simulator app" in apple


def test_release_requires_exact_main_commit_full_ci_and_two_installers():
    publisher = workflow("release-on-request.yml")
    staging = (ROOT / "scripts" / "release_assets.py").read_text(encoding="utf-8")
    assert 'windows-client.yml apple-clients.yml' in publisher
    assert "head_sha=$SHA&branch=main&event=push&status=success" in publisher
    assert "scripts/release_assets.py" in publisher
    assert "Shengjian-windows-x64-setup.exe" in staging
    assert "Shengjian-mac-arm64.dmg" in staging
    assert "stage_public_installers" in staging
