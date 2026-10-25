"""Run two packaged Windows services with synthetic data, no user data."""
import argparse
import hashlib
import hmac
import http.client
import json
import os
import queue
import secrets
import threading
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode


class Service:
    def __init__(self, executable, folder):
        self.folder = folder
        env = {**os.environ, 'DOUBAO_BRIDGE_DATA_DIR': str(folder)}
        env.pop('DOUBAO_BRIDGE_PUBLIC_URL', None)
        self.process = subprocess.Popen([str(executable), '--server-only', '--port', '0'],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            lines = queue.Queue()
            threading.Thread(target=lambda: lines.put(self.process.stdout.readline()), daemon=True).start()
            info = json.loads(lines.get(timeout=120))
            assert info.get('service') == 'shengjian.bridge' and info.get('protocol') == 1
            assert info['pid'] == self.process.pid or (os.name == 'nt' and info.get('parent_pid') == self.process.pid)
            self.port = info['port']; self.instance_id = info['instance_id']
            self.key = (folder/'access_key.txt').read_text().strip()
            # The endpoint closure reads this supported config on demand. No
            # pre-bind/release race or guessed port is needed for a test peer.
            (folder/'public_url.txt').write_text(f'http://127.0.0.1:{self.port}', encoding='utf-8')
            nonce = secrets.token_hex(16)
            connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
            try:
                connection.request('GET', '/health', headers={'X-Shengjian-Challenge': nonce})
                response = connection.getresponse(); health = json.loads(response.read())
                message = f'shengjian-local-v1\n{nonce}\n{self.instance_id}\n{info["pid"]}\n{self.port}'
                proof = hmac.new(self.key.encode(), message.encode(), hashlib.sha256).hexdigest()
                assert response.status == 200 and hmac.compare_digest(health.get('proof', ''), proof)
            finally:
                connection.close()
            assert self.call('/desktop/state')['version'] == '1.4.0'
        except Exception:
            self.close(); raise

    def call(self, path, data=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        try:
            headers = {"X-Shengjian-Instance": self.instance_id} if hasattr(self, "instance_id") else {}
            if data is None:
                connection.request('GET', path + '?' + urlencode({'key': self.key}), headers=headers)
            else:
                connection.request('POST', path, json.dumps({**data, 'key': self.key}).encode(), {**headers, 'Content-Type': 'application/json'})
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
            source = Path(scratch) / 'synthetic-中文.bin'
            source.write_bytes(bytes(range(256)) * 4096 + b'multiple-chunks')
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
