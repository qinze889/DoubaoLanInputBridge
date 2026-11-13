"""Stage a release only from successful CI runs of the exact tagged commit."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_run(run, workflow, commit, repository, run_id):
    assert run['id'] == int(run_id), 'Workflow run ID mismatch'
    assert run['repository']['full_name'] == repository, 'Workflow repository mismatch'
    assert run['path'] == f'.github/workflows/{workflow}', 'Wrong workflow'
    assert run['status'] == 'completed' and run['conclusion'] == 'success', 'CI has not passed'
    assert run['head_sha'] == commit, 'CI did not test the tagged commit'


def verify_artifact(root, expected_names, metadata_name, version, commit, run_id):
    expected_names = set(expected_names) | {metadata_name}
    assert {p.name for p in root.iterdir()} == expected_names | {'SHA256SUMS.txt'}, 'Unexpected or missing artifact files'
    checked = set()
    for line in (root/'SHA256SUMS.txt').read_text(encoding='utf-8-sig').splitlines():
        digest, name = line.split(None, 1)
        name = name.strip()
        assert name in expected_names and name not in checked, 'Invalid checksum filename'
        assert re.fullmatch(r'[0-9a-fA-F]{64}', digest), 'Invalid SHA256'
        path = root/name
        assert path.is_file() and not path.is_symlink(), 'Invalid artifact file'
        assert sha256(path) == digest.lower(), 'Artifact checksum mismatch'
        checked.add(name)
    assert checked == expected_names, 'Checksum manifest is incomplete'
    metadata = json.loads((root/metadata_name).read_text(encoding='utf-8-sig'))
    assert metadata['version'] == version, 'Artifact version mismatch'
    assert metadata['source_commit'] == commit, 'Artifact built from another commit'
    assert str(metadata['workflow_run']) == str(run_id), 'Artifact run mismatch'
    return metadata



def stage_public_installers(windows_root, macos_root, output, version):
    """Only two public downloads; checksums/metadata stay in private CI artifacts."""
    output.mkdir()  # Never combine files from unrelated builds.
    public_assets = (
        (windows_root / 'Shengjian-windows-x64-setup.exe', f'Shengjian-{version}-windows-x64-setup.exe'),
        (macos_root / 'Shengjian-mac-arm64.dmg', f'Shengjian-{version}-mac-arm64.dmg'),
    )
    for source, name in public_assets:
        assert source.is_file() and not source.is_symlink(), 'Missing or invalid public installer'
        assert source.stat().st_size > 1_000_000, 'Installer is unexpectedly small'
        shutil.copy2(source, output / name)
    assert {p.name for p in output.iterdir()} == {name for _, name in public_assets}, 'Release must contain exactly two installers'
    return [name for _, name in public_assets]

def release_body(commit):
    return (f'Windows / macOS verified CI release. Source SHA: {commit}. '
            'Windows update: open 声笺 → 设置 → 检查更新.')


def recoverable_draft_id(releases, tag, commit):
    """Permit recovery only of this workflow's unpublished draft on an ancestor."""
    assert re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', tag), 'Invalid release tag'
    assert re.fullmatch(r'[0-9a-f]{40}', commit), 'Invalid requested commit'
    matches = [release for release in releases if release.get('tag_name') == tag]
    assert len(matches) <= 1, 'Multiple releases use the requested tag'
    if not matches:
        return None
    release = matches[0]
    assert release.get('draft') is True and release.get('published_at') is None, 'Never replace a published release'
    assert release.get('prerelease') is False and not release.get('immutable'), 'Unexpected release state'
    assert release.get('author', {}).get('login') == 'github-actions[bot]', 'Draft was not created by this workflow'
    previous = release.get('target_commitish', '')
    assert re.fullmatch(r'[0-9a-f]{40}', previous), 'Draft target must be an exact commit'
    assert release.get('name') == f'声笺 {tag[1:]}', 'Unexpected draft title'
    assert release.get('body') == release_body(previous), 'Draft provenance differs'
    expected = {f'Shengjian-{tag[1:]}-windows-x64-setup.exe', f'Shengjian-{tag[1:]}-mac-arm64.dmg'}
    names = [asset['name'] for asset in release.get('assets', [])]
    assert len(names) == len(set(names)) and set(names) <= expected, 'Unexpected draft assets'
    assert type(release.get('id')) is int and release['id'] > 0, 'Invalid draft ID'
    subprocess.run(['git', 'merge-base', '--is-ancestor', previous, commit], check=True)
    return release['id']


def verify_uploaded_installers(release, tag, commit, staged):
    """Before publication, bind both uploaded bytes to the validated local files."""
    assert release['tag_name'] == tag and release['target_commitish'] == commit, 'Draft source differs'
    assert release['draft'] is True and release['prerelease'] is False, 'Release is not a stable draft'
    assert release.get('published_at') is None, 'Release was already published'
    expected = {f'Shengjian-{tag[1:]}-windows-x64-setup.exe', f'Shengjian-{tag[1:]}-mac-arm64.dmg'}
    assets = release['assets']
    assert len(assets) == 2 and {asset['name'] for asset in assets} == expected, 'Release must contain exactly two installers'
    for asset in assets:
        path = staged / asset['name']
        assert path.is_file() and not path.is_symlink(), 'Missing staged installer'
        assert asset['state'] == 'uploaded' and asset['size'] == path.stat().st_size, 'Upload is incomplete'
        assert asset.get('digest') == 'sha256:' + sha256(path), 'Uploaded installer checksum differs'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tag', required=True)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--windows-run', type=Path, required=True)
    parser.add_argument('--apple-run', type=Path, required=True)
    parser.add_argument('--windows-run-id', required=True)
    parser.add_argument('--apple-run-id', required=True)
    parser.add_argument('--windows', type=Path, required=True)
    parser.add_argument('--macos', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', args.tag), 'Invalid release tag'
    version = Path('VERSION').read_text().strip()
    assert args.tag == 'v'+version, 'Tag and VERSION differ'
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    for run_path, workflow, run_id in ((args.windows_run, 'windows-client.yml', args.windows_run_id),
                                       (args.apple_run, 'apple-clients.yml', args.apple_run_id)):
        verify_run(json.loads(run_path.read_text()), workflow, commit, args.repository, run_id)
    # CI keeps metadata and checksums, while public Releases offer one installer per desktop OS.
    win_files = {'Shengjian-windows-x64-setup.exe',
                 'cloudflared-LICENSE.txt', 'INSTALL-Windows.txt'}
    mac_files = {'Shengjian-mac-arm64.dmg', 'Shengjian-mac-arm64.zip',
                 'cloudflared-LICENSE.txt', 'INSTALL-macOS.txt'}
    windows = verify_artifact(args.windows, win_files, 'Windows-build.json', version, commit, args.windows_run_id)
    mac = verify_artifact(args.macos, mac_files, 'Mac-build.json', version, commit, args.apple_run_id)
    assert windows['installed_upgrade_and_transfer_verified'] is True
    assert windows['frozen_p2p_verified'] is True
    assert mac['dmg_zip_signature_and_frozen_p2p_verified'] is True
    assert windows.get('cloudflare_public_e2e_verified') is True, 'Windows public Cloudflare E2E was not verified'
    assert mac.get('cloudflare_public_e2e_verified') is True, 'macOS public Cloudflare E2E was not verified'
    assert windows['architecture'] == 'x64' and mac['architecture'] == 'arm64'
    assert mac['signing'] == 'ad-hoc' and mac['notarized'] is False
    stage_public_installers(args.windows, args.macos, args.output, version)
    print(f'Verified Windows installer and Mac DMG for {args.tag} at {commit}.')


if __name__ == '__main__':
    main()
