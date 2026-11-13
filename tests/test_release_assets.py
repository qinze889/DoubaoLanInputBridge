"""Release guards must reject stale, incomplete and tampered CI artifacts."""
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('release_assets', Path(__file__).resolve().parents[1]/'scripts/release_assets.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def run_info():
    return {'id': 123, 'repository': {'full_name': 'owner/repo'},
            'path': '.github/workflows/apple-clients.yml', 'status': 'completed',
            'conclusion': 'success', 'head_sha': 'a'*40}


def test_accept_successful_run_of_exact_tagged_commit():
    release.verify_run(run_info(), 'apple-clients.yml', 'a'*40, 'owner/repo', '123')


@pytest.mark.parametrize(('field', 'value'), [('head_sha', 'b'*40), ('conclusion', 'failure'),
    ('status', 'in_progress'), ('path', '.github/workflows/other.yml'), ('id', 124),
    ('repository', {'full_name': 'other/repo'})])
def test_reject_stale_failed_or_wrong_workflow(field, value):
    run = run_info()
    run[field] = value
    with pytest.raises(AssertionError):
        release.verify_run(run, 'apple-clients.yml', 'a'*40, 'owner/repo', '123')


def artifact(tmp_path):
    (tmp_path/'app.dmg').write_bytes(b'package data')
    (tmp_path/'Mac-build.json').write_text(json.dumps({'version': '1.4.0', 'source_commit': 'a'*40, 'workflow_run': '123'}))
    (tmp_path/'SHA256SUMS.txt').write_text(''.join(
        f'{release.sha256(tmp_path/name)}  {name}\n' for name in ['app.dmg', 'Mac-build.json']))
    return tmp_path


def verify(root):
    return release.verify_artifact(root, {'app.dmg'}, 'Mac-build.json', '1.4.0', 'a'*40, 123)


def test_verified_artifact_has_complete_matching_checksums(tmp_path):
    assert verify(artifact(tmp_path))['version'] == '1.4.0'


@pytest.mark.parametrize('corruption', ['bytes', 'unlisted', 'missing_checksum', 'path_traversal', 'duplicate', 'source', 'version', 'run'])
def test_reject_tampered_or_misidentified_artifact(tmp_path, corruption):
    root = artifact(tmp_path)
    manifest = root/'SHA256SUMS.txt'
    if corruption == 'bytes':
        (root/'app.dmg').write_bytes(b'tampered')
    elif corruption == 'unlisted':
        (root/'relay.json').write_text('private runtime state')
    elif corruption == 'missing_checksum':
        manifest.write_text(manifest.read_text().splitlines()[0]+'\n')
    elif corruption == 'path_traversal':
        manifest.write_text('a'*64+'  ../app.dmg\n')
    elif corruption == 'duplicate':
        manifest.write_text(manifest.read_text()+manifest.read_text())
    else:
        meta_path = root/'Mac-build.json'
        meta = json.loads(meta_path.read_text())
        meta[{'source': 'source_commit', 'version': 'version', 'run': 'workflow_run'}[corruption]] = 'wrong'
        meta_path.write_text(json.dumps(meta))
        manifest.write_text(''.join(f'{release.sha256(root/name)}  {name}\n' for name in ['app.dmg', 'Mac-build.json']))
    with pytest.raises(AssertionError):
        verify(root)


def test_stages_only_windows_setup_and_mac_dmg(tmp_path):
    windows, macos, output = (tmp_path / name for name in ('win-ci', 'mac-ci', 'release'))
    windows.mkdir()
    macos.mkdir()
    (windows / 'Shengjian-windows-x64-setup.exe').write_bytes(b'W' * 1_000_001)
    (macos / 'Shengjian-mac-arm64.dmg').write_bytes(b'M' * 1_000_001)
    # Files used to validate a build stay in the CI artifact, not the user-facing Release.
    (windows / 'Windows-build.json').write_text('{}')
    (macos / 'Shengjian-mac-arm64.zip').write_bytes(b'private verification artifact')
    result = release.stage_public_installers(windows, macos, output, '1.4.2')
    assert set(result) == {'Shengjian-1.4.2-windows-x64-setup.exe', 'Shengjian-1.4.2-mac-arm64.dmg'}
    assert {p.name for p in output.iterdir()} == set(result)


def test_missing_or_small_public_installer_fails_closed(tmp_path):
    windows, macos = tmp_path / 'windows', tmp_path / 'macos'
    windows.mkdir()
    macos.mkdir()
    (windows / 'Shengjian-windows-x64-setup.exe').write_bytes(b'not a real installer')
    (macos / 'Shengjian-mac-arm64.dmg').write_bytes(b'M' * 1_000_001)
    with pytest.raises(AssertionError):
        release.stage_public_installers(windows, macos, tmp_path / 'release', '1.4.2')

def draft_record(commit='a'*40):
    return {'id': 444, 'tag_name': 'v1.4.2', 'target_commitish': commit,
            'draft': True, 'prerelease': False, 'published_at': None, 'immutable': False,
            'author': {'login': 'github-actions[bot]'}, 'name': '声笺 1.4.2',
            'body': release.release_body(commit), 'assets': []}


def test_recovers_only_unpublished_ancestor_draft(monkeypatch):
    calls = []
    monkeypatch.setattr(release.subprocess, 'run', lambda args, **kw: calls.append((args, kw)))
    assert release.recoverable_draft_id([draft_record()], 'v1.4.2', 'b'*40) == 444
    assert calls == [(['git', 'merge-base', '--is-ancestor', 'a'*40, 'b'*40], {'check': True})]
    assert release.recoverable_draft_id([], 'v1.4.2', 'b'*40) is None


@pytest.mark.parametrize(('field', 'value'), [
    ('draft', False), ('published_at', '2026-11-13T12:00:00Z'), ('prerelease', True),
    ('immutable', True), ('author', {'login': 'someone-else'}), ('name', 'Manual draft'),
    ('target_commitish', 'main'), ('body', 'User-written release notes'), ('id', -1),
    ('assets', [{'name': 'private-config.json'}]),
])
def test_refuses_to_replace_published_or_unrecognized_draft(monkeypatch, field, value):
    monkeypatch.setattr(release.subprocess, 'run', lambda *a, **kw: pytest.fail('Unsafe draft reached git check'))
    draft = draft_record()
    draft[field] = value
    with pytest.raises(AssertionError):
        release.recoverable_draft_id([draft], 'v1.4.2', 'b'*40)


def test_refuses_duplicate_or_nonancestor_draft(monkeypatch):
    with pytest.raises(AssertionError):
        release.recoverable_draft_id([draft_record(), draft_record()], 'v1.4.2', 'b'*40)
    def reject(*args, **kwargs):
        raise release.subprocess.CalledProcessError(1, args[0])
    monkeypatch.setattr(release.subprocess, 'run', reject)
    with pytest.raises(release.subprocess.CalledProcessError):
        release.recoverable_draft_id([draft_record()], 'v1.4.2', 'b'*40)


def uploaded_release(tmp_path):
    draft = draft_record()
    for name, data in [('Shengjian-1.4.2-windows-x64-setup.exe', b'Windows installer'),
                       ('Shengjian-1.4.2-mac-arm64.dmg', b'Mac installer')]:
        path = tmp_path / name
        path.write_bytes(data)
        draft['assets'].append({'name': name, 'state': 'uploaded', 'size': len(data),
                                'digest': 'sha256:' + release.sha256(path)})
    return draft


def test_uploaded_installers_match_verified_bytes(tmp_path):
    release.verify_uploaded_installers(uploaded_release(tmp_path), 'v1.4.2', 'a'*40, tmp_path)


@pytest.mark.parametrize('corruption', ['digest', 'size', 'state', 'extra', 'missing', 'source', 'published'])
def test_rejects_changed_or_incomplete_upload(tmp_path, corruption):
    draft = uploaded_release(tmp_path)
    if corruption in ('digest', 'size', 'state'):
        draft['assets'][0][corruption] = {'digest': 'sha256:'+'0'*64, 'size': 0, 'state': 'new'}[corruption]
    elif corruption == 'extra':
        draft['assets'].append(dict(draft['assets'][0]))
    elif corruption == 'missing':
        draft['assets'].pop()
    elif corruption == 'source':
        draft['target_commitish'] = 'b'*40
    else:
        draft['draft'] = False
    with pytest.raises(AssertionError):
        release.verify_uploaded_installers(draft, 'v1.4.2', 'a'*40, tmp_path)
