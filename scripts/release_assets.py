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
    win_files = {'Shengjian-windows-x64-setup.exe', 'Shengjian-windows-x64.exe',
                 'cloudflared-LICENSE.txt', 'INSTALL-Windows.txt'}
    mac_files = {'Shengjian-mac-arm64.dmg', 'Shengjian-mac-arm64.zip',
                 'cloudflared-LICENSE.txt', 'INSTALL-macOS.txt'}
    windows = verify_artifact(args.windows, win_files, 'Windows-build.json', version, commit, args.windows_run_id)
    mac = verify_artifact(args.macos, mac_files, 'Mac-build.json', version, commit, args.apple_run_id)
    assert windows['installed_upgrade_and_transfer_verified'] is True
    assert windows['frozen_p2p_verified'] is True
    assert mac['dmg_zip_signature_and_frozen_p2p_verified'] is True
    assert windows['architecture'] == 'x64' and mac['architecture'] == 'arm64'
    assert mac['signing'] == 'developer-id' and mac['notarized'] is True, 'Stable releases require Developer ID and notarization'
    assert mac.get('distribution_mode') == 'production', 'Development builds cannot be released as production'
    args.output.mkdir()  # Never silently combine artifacts from different builds.
    for root, names, metadata in ((args.windows, win_files, 'Windows-build.json'),
                                   (args.macos, mac_files, 'Mac-build.json')):
        for name in sorted(names | {metadata}):
            target = name.replace('Shengjian-', f'Shengjian-{version}-', 1) if name.startswith('Shengjian-') else name
            path = root/name
            if path.suffix in {'.exe', '.zip', '.dmg'}:
                assert path.stat().st_size > 1_000_000, 'Package is unexpectedly small'
            shutil.copy2(path, args.output/target)
    for archive_format, suffix in (('zip', 'zip'), ('tar.gz', 'tar.gz')):
        subprocess.run(['git', 'archive', f'--format={archive_format}', f'--prefix=Shengjian-{version}/',
                        '-o', str(args.output/f'Shengjian-{version}-source.{suffix}'), 'HEAD'], check=True)
    metadata = {'version': version, 'release_commit': commit,
                'windows_workflow_run': int(args.windows_run_id), 'apple_workflow_run': int(args.apple_run_id),
                'windows_workflow_url': f'https://github.com/{args.repository}/actions/runs/{args.windows_run_id}',
                'apple_workflow_url': f'https://github.com/{args.repository}/actions/runs/{args.apple_run_id}'}
    (args.output/'Release-build.json').write_text(json.dumps(metadata, indent=2)+'\n')
    files = sorted(args.output.iterdir())
    (args.output/'SHA256SUMS.txt').write_text(''.join(f'{sha256(p)}  {p.name}\n' for p in files))
    print(f'Verified Mac, Windows and source assets for {args.tag} at {commit}.')


if __name__ == '__main__':
    main()
