import json
import pytest
from server.desktop_agent.permissions import install_policy


def test_explicit_permission_mode_persists_without_overwriting_other_profile_rows(tmp_path):
    home=tmp_path/'home';home.mkdir();other={'id':'other-setting','config':{'value':True}}
    patch=home/'cordis.patch.yml';patch.write_text(json.dumps([other]))
    install_policy(tmp_path,'danger-full-access')
    rows=json.loads(patch.read_text());assert rows[0]==other
    assert rows[1]['insert'][0]['config']['mode']=='danger-full-access'
    assert patch.stat().st_mode&0o077==0
    assert (home/'shengjian-permissions.mjs').is_file()
    install_policy(tmp_path,'workspace-write')
    rows=json.loads(patch.read_text());assert len(rows)==2 and rows[1]['insert'][0]['config']['mode']=='workspace-write'
    with pytest.raises(ValueError):install_policy(tmp_path,'unrecognized-mode')
    assert json.loads(patch.read_text())==rows


def test_unknown_existing_patch_is_preserved(tmp_path):
    home=tmp_path/'home';home.mkdir();patch=home/'cordis.patch.yml';text='existing: YAML user configuration\n';patch.write_text(text)
    with pytest.raises(ValueError):install_policy(tmp_path,'danger-full-access')
    assert patch.read_text()==text
