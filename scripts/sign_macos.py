"""Separate development identities; fail closed for Developer ID distribution."""
import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_ID = 'com.doubaolaninputbridge.mac'


def configuration(environ=None):
    env = os.environ if environ is None else environ
    mode = env.get('SHENGJIAN_BUILD_MODE', 'development')
    if mode not in {'development', 'production'}:
        raise ValueError('SHENGJIAN_BUILD_MODE must be development or production')
    identity = env.get('SHENGJIAN_SIGNING_IDENTITY', '')
    profile = env.get('SHENGJIAN_NOTARY_PROFILE', '')
    if mode == 'production' and (not identity.startswith('Developer ID Application:') or not profile):
        raise ValueError('Production requires SHENGJIAN_SIGNING_IDENTITY (Developer ID Application) and SHENGJIAN_NOTARY_PROFILE; no ad-hoc fallback')
    return mode, identity, profile


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True)


def macho(path):
    if path.is_symlink() or not path.is_file():
        return False
    with path.open('rb') as stream:
        return stream.read(4) in {b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca'}


def sign(app):
    mode, identity, profile = configuration()
    ident = PRODUCTION_ID if mode == 'production' else PRODUCTION_ID+'.development'
    for bundle, suffix in [(app, ''), (app/'Contents/PlugIns/ShengjianShare.appex', '.share')]:
        info_path = bundle/'Contents/Info.plist'
        info = plistlib.loads(info_path.read_bytes())
        info['CFBundleIdentifier'] = ident+suffix
        info['CFBundleDisplayName'] = '声笺' if mode == 'production' else '声笺开发版'
        info['SHENGJIANDistributionMode'] = mode
        info_path.write_bytes(plistlib.dumps(info))
    options = ['--force', '--sign', identity if mode == 'production' else '-']
    if mode == 'production':
        options += ['--timestamp', '--options', 'runtime']
    for binary in sorted((p for p in app.rglob('*') if macho(p)), key=lambda p: len(p.parts), reverse=True):
        run('codesign', *options, str(binary))
    for framework in sorted(app.rglob('*.framework'), key=lambda p: len(p.parts), reverse=True):
        run('codesign', *options, str(framework))
    run('codesign', *options, '--entitlements', str(ROOT/'native/ShareExtension/Entitlements.plist'), str(app/'Contents/PlugIns/ShengjianShare.appex'))
    run('codesign', *options, str(app))
    run('codesign', '--verify', '--deep', '--strict', str(app))
    if mode == 'production':
        details = run('codesign', '-dv', '--verbose=4', str(app)).stderr
        if 'Signature=adhoc' in details or 'TeamIdentifier=not set' in details:
            raise RuntimeError('Production signature has no stable team identity')
        with tempfile.TemporaryDirectory(prefix='shengjian-notarize-') as folder:
            archive = Path(folder)/'application.zip'
            run('ditto', '-c', '-k', '--keepParent', str(app), str(archive))
            arguments = ['xcrun', 'notarytool', 'submit', str(archive), '--keychain-profile', profile, '--wait']
            if os.environ.get('SHENGJIAN_NOTARY_KEYCHAIN'):
                arguments += ['--keychain', os.environ['SHENGJIAN_NOTARY_KEYCHAIN']]
            run(*arguments)
        run('xcrun', 'stapler', 'staple', str(app))
        run('xcrun', 'stapler', 'validate', str(app))
        run('spctl', '--assess', '--type', 'execute', '--verbose=2', str(app))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('app', type=Path, nargs='?')
    args = parser.parse_args()
    try:
        configuration()
        if args.app:
            sign(args.app)
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        # Do not echo credential-bearing command arguments or notary diagnostics.
        raise SystemExit(str(exc) if isinstance(exc, (ValueError, RuntimeError)) else 'Apple signing/notarization failed; distribution stopped')
