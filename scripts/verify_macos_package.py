"""Verify the actual Mac downloads without installing or requesting UI permission."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_app(app, version):
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    info = plistlib.loads((app/'Contents/Info.plist').read_bytes())
    assert info['CFBundleShortVersionString'] == version, 'Bundle version mismatch'
    assert info['CFBundleIdentifier'] == 'com.doubaolaninputbridge.mac'
    native = app/'Contents/MacOS/Shengjian'
    service = app/'Contents/Resources/bridge-service/bridge-service'
    cloudflared = service.parent/'cloudflared'
    extension = app/'Contents/PlugIns/ShengjianShare.appex'
    extension_info = plistlib.loads((extension/'Contents/Info.plist').read_bytes())
    assert extension_info['NSExtension']['NSExtensionPointIdentifier'] == 'com.apple.share-services'
    assert extension_info['CFBundleShortVersionString'] == version
    extension_binary = extension/'Contents/MacOS/ShengjianShare'
    subprocess.run(['codesign', '--verify', '--strict', str(extension)], check=True)
    entitlements = subprocess.check_output(['codesign', '-d', '--entitlements', ':-', str(extension)], stderr=subprocess.DEVNULL)
    assert plistlib.loads(entitlements)['com.apple.security.app-sandbox'] is True
    for binary in (native, service, cloudflared, extension_binary):
        subprocess.run(['lipo', str(binary), '-verify_arch', 'arm64'], check=True)
    subprocess.run([str(cloudflared), '--version'], check=True)
    private_names = {'relay.json', 'access_key.txt', 'paired-devices.json', 'device.json',
                     'minimax_api_key.txt', 'service.log'}
    assert not any(p.name in private_names for p in app.rglob('*')), 'Private state in package'
    return sha256(native), sha256(service), sha256(extension_binary)


def main():
    version = (ROOT/'VERSION').read_text().strip()
    dmg = ROOT/'dist/Shengjian-mac-arm64.dmg'
    archive = ROOT/'dist/Shengjian-mac-arm64.zip'
    subprocess.run(['hdiutil', 'verify', str(dmg)], check=True)
    with tempfile.TemporaryDirectory(prefix='shengjian-package-') as scratch:
        scratch = Path(scratch)
        extracted, mount = scratch/'zip', scratch/'mounted'
        subprocess.run(['ditto', '-x', '-k', str(archive), str(extracted)], check=True)
        zip_hashes = verify_app(extracted/'声笺.app', version)
        mount.mkdir()
        subprocess.run(['hdiutil', 'attach', '-readonly', '-nobrowse', '-mountpoint', str(mount), str(dmg)], check=True)
        try:
            app = mount/'声笺.app'
            assert (mount/'Applications').is_symlink()
            assert os.readlink(mount/'Applications') == '/Applications'
            assert (mount/'安装说明.txt').is_file()
            assert verify_app(app, version) == zip_hashes, 'DMG and ZIP apps differ'
            subprocess.run([sys.executable, str(ROOT/'scripts/smoke_packaged_rtc.py'),
                            '--service', str(app/'Contents/Resources/bridge-service/bridge-service')],
                           check=True, timeout=300)
        finally:
            subprocess.run(['hdiutil', 'detach', str(mount)], check=True)
    output = ROOT/'dist/macos'
    output.mkdir(exist_ok=True)
    for path in (dmg, archive):
        shutil.copy2(path, output/path.name)
    shutil.copy2(ROOT/'docs/INSTALL-macOS.txt', output/'INSTALL-macOS.txt')
    shutil.copy2(ROOT/'docs/cloudflared-LICENSE', output/'cloudflared-LICENSE.txt')
    metadata = {'version': version, 'source_commit': subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'workflow_run': os.environ.get('GITHUB_RUN_ID'), 'architecture': 'arm64',
        'signing': 'ad-hoc', 'notarized': False,
        'dmg_zip_signature_and_frozen_p2p_verified': True}
    (output/'Mac-build.json').write_text(json.dumps(metadata, indent=2)+'\n')
    files = sorted(p for p in output.iterdir() if p.name != 'SHA256SUMS.txt')
    (output/'SHA256SUMS.txt').write_text(''.join(f'{sha256(p)}  {p.name}\n' for p in files))
    print('Mac DMG/ZIP: signatures, versions, architecture and frozen two-way P2P SHA256 verified.')


if __name__ == '__main__':
    main()
