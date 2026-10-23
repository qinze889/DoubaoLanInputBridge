import importlib.util
from pathlib import Path
import plistlib
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('sign_macos',ROOT/'scripts/sign_macos.py')
signing=importlib.util.module_from_spec(spec);spec.loader.exec_module(signing)


def test_production_never_falls_back_to_ad_hoc():
    for env in [{'SHENGJIAN_BUILD_MODE':'production'}, {'SHENGJIAN_BUILD_MODE':'production','SHENGJIAN_SIGNING_IDENTITY':'-','SHENGJIAN_NOTARY_PROFILE':'profile'}]:
        with pytest.raises(ValueError,match='no ad-hoc fallback'):signing.configuration(env)


def test_development_has_distinct_bundle_and_does_not_notarize(tmp_path,monkeypatch):
    monkeypatch.setenv('SHENGJIAN_BUILD_MODE','development')
    app=tmp_path/'Development.app'
    for bundle in [app,app/'Contents/PlugIns/ShengjianShare.appex']:
        (bundle/'Contents').mkdir(parents=True)
        (bundle/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'old'}))
    calls=[]
    monkeypatch.setattr(signing,'run',lambda *args:calls.append(args))
    signing.sign(app)
    assert plistlib.loads((app/'Contents/Info.plist').read_bytes())['CFBundleIdentifier']==signing.PRODUCTION_ID+'.development'
    assert plistlib.loads((app/'Contents/PlugIns/ShengjianShare.appex/Contents/Info.plist').read_bytes())['CFBundleIdentifier']==signing.PRODUCTION_ID+'.development.share'
    assert not any('notarytool' in call for call in calls)


def test_unknown_distribution_mode_is_rejected():
    with pytest.raises(ValueError):signing.configuration({'SHENGJIAN_BUILD_MODE':'temporary'})
