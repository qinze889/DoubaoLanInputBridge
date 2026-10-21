"""Run two packaged Windows services with synthetic data, no user data."""
import argparse
import hashlib
import http.client
import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode


class Service:
    def __init__(self, executable, folder):
        self.folder = folder
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); self.port = listener.getsockname()[1]
        self.process = subprocess.Popen([str(executable), '--server-only', '--port', str(self.port)],
            env={**os.environ, 'DOUBAO_BRIDGE_DATA_DIR': str(folder),
                 'DOUBAO_BRIDGE_PUBLIC_URL': f'http://127.0.0.1:{self.port}'},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(120):
                if self.process.poll() is not None: raise RuntimeError('packaged service exited')
                key = folder / 'access_key.txt'
                if key.exists():
                    self.key = key.read_text().strip()
                    try:
                        if self.call('/desktop/state')['version'] == '1.3.0': return
                    except (OSError, ValueError, RuntimeError): pass
                time.sleep(.25)
            raise RuntimeError('packaged service readiness timeout')
        except Exception:
            self.close(); raise

    def call(self, path, data=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        try:
            if data is None:
                connection.request('GET', path + '?' + urlencode({'key': self.key}))
            else:
                connection.request('POST', path, json.dumps({**data, 'key': self.key}).encode(), {'Content-Type': 'application/json'})
            response = connection.getresponse(); result = json.loads(response.read())
            if response.status != 200 or not result.get('ok'): raise RuntimeError('packaged API rejected request')
            return result
        finally:
            connection.close()

    def close(self):
        if self.process.poll() is not None: return
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(self.process.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            self.process.terminate()
        try: self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill(); self.process.wait()


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--service', type=Path, required=True)
    executable = parser.parse_args().service.resolve()
    services = []
    with tempfile.TemporaryDirectory(prefix='shengjian-packaged-check-') as scratch:
        try:
            for index in range(2): services.append(Service(executable, Path(scratch) / str(index)))
            a, b = services
            assert all(s.call('/desktop/peers')['network']['tunnel']['cloudflared_available'] for s in services)
            a.call('/desktop/peers/join', {'invitation': b.call('/desktop/peers/invite', {})['invitation']})
            source = Path(scratch) / 'synthetic-中文.bin'; source.write_bytes(bytes(range(256)) * 1024)
            expected = hashlib.sha256(source.read_bytes()).digest()
            for sender, receiver in ((a, b), (b, a)):
                receiver_id = receiver.call('/desktop/peers')['device']['id']
                job_id = sender.call('/desktop/peers/send', {'id': receiver_id, 'paths': [str(source)]})['job_id']
                for _ in range(100):
                    job = next(row for row in sender.call('/desktop/peers')['jobs'] if row['id'] == job_id)
                    if job['status'] in ('complete', 'error'): break
                    time.sleep(.1)
                assert job['status'] == 'complete'
                targets = list((receiver.folder / 'received').glob('*/synthetic-中文.bin'))
                assert targets and all(hashlib.sha256(path.read_bytes()).digest() == expected for path in targets)
            print('Packaged services: bundled cloudflared found, pairing and two-way SHA256 transfer passed.')
        finally:
            for service in reversed(services): service.close()


if __name__ == '__main__':
    try: main()
    except Exception as error:
        raise SystemExit(f'Packaged peer check failed ({type(error).__name__}); credentials withheld.') from None
