import json
import os
from server.desktop_agent.media import install_media_plugin


def test_media_install_preserves_permissions_and_is_idempotent(tmp_path):
    home=tmp_path/'home';home.mkdir()
    original={'insert':[{'id':'shengjian-owner-permissions','config':{'mode':'danger-full-access'}}]}
    patch=home/'cordis.patch.yml';patch.write_text(json.dumps([original]))
    assert install_media_plugin(tmp_path)
    first=json.loads(patch.read_text())
    assert first[0]==original
    assert first[1]['insert'][0]['id']=='shengjian-conversation-media'
    assert install_media_plugin(tmp_path) and json.loads(patch.read_text())==first
    plugin=home/'shengjian-media.mjs'
    assert 'create_image' in plugin.read_text()
    if os.name!='nt':assert plugin.stat().st_mode&0o077==0 and patch.stat().st_mode&0o077==0


def test_unknown_home_format_is_not_overwritten(tmp_path):
    home=tmp_path/'home';home.mkdir();patch=home/'cordis.patch.yml'
    old='user: custom-yaml\n';patch.write_text(old)
    assert not install_media_plugin(tmp_path)
    assert patch.read_text()==old and not (home/'shengjian-media.mjs').exists()
