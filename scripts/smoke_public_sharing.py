"""Opt-in: three bundled services, real Quick Tunnels, synthetic files only.

Run after build_macos.sh: .venv/bin/python scripts/smoke_public_sharing.py
Creates temporary pairing credentials, closes owned services/tunnels on exit.
Never prints pairing URLs, keys, invitations, or response bodies.
"""
import hashlib
import http.client
import json
import os
import selectors
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit


def request(base, path, data=None):
    parsed = urlsplit(base)
    connection = (http.client.HTTPSConnection if parsed.scheme == 'https' else http.client.HTTPConnection)(parsed.hostname, parsed.port, timeout=30)
    try:
        connection.request('GET' if data is None else 'POST', path,
                           None if data is None else json.dumps(data).encode(),
                           {'Content-Type': 'application/json'})
        response = connection.getresponse()
        body = response.read()
        try:
            result = json.loads(body)
        except ValueError:
            result = {}
        return response.status, result
    finally:
        connection.close()


class Machine:
    def __init__(self, binary, folder):
        self.folder = folder
        self.child = subprocess.Popen([str(binary)], env={**os.environ, 'DOUBAO_BRIDGE_DATA_DIR': str(folder)},
                                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(self.child.stdout, selectors.EVENT_READ)
                if not selector.select(20):
                    raise RuntimeError('service startup timed out')
            info = json.loads(self.child.stdout.readline())
            self.base = f'http://127.0.0.1:{info["port"]}'
            self.key = (folder / 'access_key.txt').read_text().strip()
        except Exception:
            self.close()
            raise RuntimeError('bundled service startup failed') from None

    def call(self, path, data=None):
        if data is None:
            status, result = request(self.base, path + '?' + urlencode({'key': self.key}))
        else:
            status, result = request(self.base, path, {**data, 'key': self.key})
        if status != 200 or not result.get('ok'):
            raise RuntimeError('local API failed')
        return result

    def close(self):
        if self.child.poll() is None:
            self.child.terminate()
            try:
                self.child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.wait()
        self.child.stdout.close()


def main():
    root = Path(__file__).resolve().parents[1]
    binary = root / 'dist/声笺.app/Contents/Resources/bridge-service/bridge-service'
    machines = []
    with tempfile.TemporaryDirectory(prefix='shengjian-public-check-') as scratch:
        try:
            for i in range(3):
                machines.append(Machine(binary, Path(scratch) / str(i)))
            print('3 bundled services started.', flush=True)
            for machine in machines:
                assert machine.call('/desktop/state')['version'] == '1.2.0'
                machine.call('/desktop/tunnel/start', {})
            print('Public tunnel startup requested.', flush=True)
            deadline = time.monotonic() + 65
            pending = list(machines)
            while pending and time.monotonic() < deadline:
                for machine in pending[:]:
                    state = machine.call('/desktop/state')['tunnel']
                    if state['phase'] == 'ready':
                        try:
                            status, health = request(state['public_url'], '/health')
                            print(f'Public health status: {status}.', flush=True)
                            if status == 200 and health.get('ok'):
                                assert request(state['public_url'], '/desktop/state')[0] == 403
                                pending.remove(machine)
                        except (OSError, ValueError, http.client.HTTPException):
                            pass
                if pending:
                    time.sleep(1)
            assert not pending, 'public tunnel readiness failed'
            print('3 public tunnels ready; desktop routes blocked.', flush=True)
            a, b, c = machines
            for other in (b, c):
                invitation = other.call('/desktop/peers/invite', {})['invitation']
                a.call('/desktop/peers/join', {'invitation': invitation})
            source = Path(scratch) / 'synthetic-transfer.bin'
            source.write_bytes(bytes(range(256)) * 2048)
            expected = hashlib.sha256(source.read_bytes()).digest()
            for sender, receiver in ((a, b), (b, a), (a, c), (c, a)):
                receiver_id = receiver.call('/desktop/peers')['device']['id']
                job_id = sender.call('/desktop/peers/send', {'id': receiver_id, 'paths': [str(source)]})['job_id']
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    job = next(row for row in sender.call('/desktop/peers')['jobs'] if row['id'] == job_id)
                    if job['status'] in ('complete', 'error'):
                        break
                    time.sleep(.5)
                assert job['status'] == 'complete', 'public transfer failed'
                targets = list((receiver.folder / 'received').glob('*/synthetic-transfer.bin'))
                assert targets and all(hashlib.sha256(target.read_bytes()).digest() == expected for target in targets)
            print('4 bidirectional public transfers across 3 machines passed SHA256 verification.', flush=True)
        finally:
            for machine in reversed(machines):
                machine.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        raise SystemExit(f'Public sharing smoke check failed ({type(error).__name__}); credentials and responses withheld.') from None
