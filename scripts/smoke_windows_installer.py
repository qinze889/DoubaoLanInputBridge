"""Exercise the actual NSIS payload and an upgrade with an orphan service."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from smoke_packaged_peers import Service


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--installer', type=Path, required=True)
    parser.add_argument('--expected-service', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'nt':
        raise RuntimeError('This integration check requires Windows')
    installer = args.installer.resolve()
    expected = hashlib.sha256(args.expected_service.read_bytes()).digest()
    with tempfile.TemporaryDirectory(prefix='shengjian-installer-check-') as scratch:
        root = Path(scratch)
        install = root / 'installed'
        install.mkdir()
        service = install / 'bridge-service.exe'
        service.write_bytes(b'outdated service must be replaced')

        def install_package():
            print("Installing NSIS package", flush=True)
            # NSIS requires /D last, without quotes even when its path has spaces.
            subprocess.run(f'"{installer}" /S /D={install}', check=True, timeout=120)
            assert hashlib.sha256(service.read_bytes()).digest() == expected, 'Installed service does not match the built payload'
            assert (install / 'VERSION').read_text().strip() == '1.4.0'

        install_package()
        previous = Service(service, root / 'previous-data')
        try:
            install_package()
            print('Checking that the orphan service exited', flush=True)
            # PyInstaller's bootloader can wait for its child to unwind after termination.
            previous.process.wait(timeout=45)
        finally:
            previous.close()
        subprocess.run([sys.executable, str(Path(__file__).with_name('smoke_packaged_peers.py')),
                        '--service', str(service)], check=True, timeout=120)
    print('NSIS installation and upgrade: service replaced, orphan stopped, installed two-way transfer verified.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        raise SystemExit(f'Installer check failed ({type(error).__name__}): {error}') from None
