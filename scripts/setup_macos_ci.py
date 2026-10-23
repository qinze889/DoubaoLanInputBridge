"""Import CI-only Apple credentials without printing their values."""
import base64
import os
from pathlib import Path
import secrets
import subprocess
import tempfile

NAMES = ['MACOS_SIGNING_P12','MACOS_SIGNING_PASSWORD','MACOS_SIGNING_IDENTITY','APPLE_NOTARY_KEY','APPLE_NOTARY_KEY_ID','APPLE_NOTARY_ISSUER_ID']


def run(*args):
    subprocess.run(args,check=True,capture_output=True)


def main():
    if any(not os.environ.get(name) for name in NAMES):
        raise SystemExit('Production signing secrets are incomplete; development fallback is forbidden')
    folder=Path(tempfile.mkdtemp(prefix='shengjian-signing-'))
    folder.chmod(0o700)
    keychain=folder/'build.keychain-db'
    password=secrets.token_urlsafe(32)
    certificate=folder/'certificate.p12';key=folder/'notary.p8'
    try:
        for path,value in [(certificate,os.environ['MACOS_SIGNING_P12']),(key,os.environ['APPLE_NOTARY_KEY'])]:
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as stream:stream.write(base64.b64decode(value,validate=True))
        run('security','create-keychain','-p',password,str(keychain))
        run('security','set-keychain-settings','-lut','21600',str(keychain))
        run('security','unlock-keychain','-p',password,str(keychain))
        run('security','import',str(certificate),'-P',os.environ['MACOS_SIGNING_PASSWORD'],'-k',str(keychain),'-T','/usr/bin/codesign')
        run('security','set-key-partition-list','-S','apple-tool:,apple:','-s','-k',password,str(keychain))
        # Keep the login keychain available for ordinary system operations.
        run('security','list-keychains','-d','user','-s',str(keychain),str(Path.home()/'Library/Keychains/login.keychain-db'))
        run('xcrun','notarytool','store-credentials','shengjian-release','--key',str(key),'--key-id',os.environ['APPLE_NOTARY_KEY_ID'],'--issuer',os.environ['APPLE_NOTARY_ISSUER_ID'],'--keychain',str(keychain))
        with open(os.environ['GITHUB_ENV'],'a') as stream:
            stream.write('SHENGJIAN_SIGNING_IDENTITY='+os.environ['MACOS_SIGNING_IDENTITY']+'\nSHENGJIAN_NOTARY_PROFILE=shengjian-release\nSHENGJIAN_NOTARY_KEYCHAIN='+str(keychain)+'\n')
    except (ValueError,subprocess.CalledProcessError):
        raise SystemExit('Apple credential setup failed; no secret details emitted') from None
    finally:
        certificate.unlink(missing_ok=True);key.unlink(missing_ok=True)


if __name__=='__main__':main()
