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
