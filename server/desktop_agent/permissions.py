"""Persist an explicit device-owner permission choice without changing the app signature."""
import json
import os
from pathlib import Path

MODES = {'workspace-write', 'danger-full-access'}


def install_policy(directory, mode):
    if mode not in MODES:
        raise ValueError('invalid_permission_mode')
    home = Path(directory)/'home'
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    patch = home/'cordis.patch.yml'
    rows = json.loads(patch.read_text()) if patch.exists() else []
    if not isinstance(rows, list):
        raise ValueError('permission_patch_requires_list')
    plugin = home/'shengjian-permissions.mjs'
    plugin.write_bytes(Path(__file__).with_name('dsh_permissions.mjs').read_bytes())
    os.chmod(plugin, 0o600)
    ident = 'shengjian-owner-permissions'
    row = {'id': ident, 'name': str(plugin), 'config': {'mode': mode}}
    for entry in rows:
        if isinstance(entry, dict) and isinstance(entry.get('insert'), list):
            for i, old in enumerate(entry['insert']):
                if isinstance(old, dict) and old.get('id') == ident:
                    entry['insert'][i] = row
                    break
            else:
                continue
            break
    else:
        rows.append({'insert': [row]})
    temporary = patch.with_suffix('.next')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as output:
        json.dump(rows, output, ensure_ascii=False)
    temporary.replace(patch)
