"""App-owned Cloudflare Quick Tunnel with a restricted public gateway."""
import http.client
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

GET_PATHS = {'/', '/health', '/files/shared', '/files/download', '/prompt/library'}
POST_PATHS = {'/peer/pair', '/peer/ping', '/peer/endpoint', '/peer/files/start', '/peer/files/chunk', '/peer/files/finish', '/send', '/files/clipboard', '/files/paste', '/files/share', '/prompt/enrich'}


class PublicGateway(ThreadingHTTPServer):
    def __init__(self, origin_port):
        self.origin_port = origin_port
        super().__init__(('127.0.0.1', 0), PublicHandler)


class PublicHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Pairing links must never be logged.

    def do_GET(self):
        self.forward(GET_PATHS)

    def do_POST(self):
        self.forward(POST_PATHS)

    def forward(self, allowed):
        path = urlsplit(self.path).path or '/'
        if path not in allowed:
            self.send_error(403, 'This endpoint is not available publicly')
            return
        if path == '/health':
            payload = b'{"ok":true,"name":"Shengjian"}'
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        conn = http.client.HTTPConnection('127.0.0.1', self.server.origin_port, timeout=90)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 0 or self.headers.get('Transfer-Encoding'):
                self.send_error(400)
                return
            conn.putrequest(self.command, self.path)
            for key in ['Content-Type', 'Content-Length', 'Range', 'X-Shengjian-Peer', 'X-Shengjian-Time', 'X-Shengjian-Nonce', 'X-Shengjian-SHA256', 'X-Shengjian-Signature']:
                if self.headers.get(key):
                    conn.putheader(key, self.headers[key])
            conn.putheader('X-Bridge-Public', '1')
            conn.endheaders()
            remaining = length
            while remaining:
                chunk = self.rfile.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise OSError('incomplete request')
                conn.send(chunk)
                remaining -= len(chunk)
            response = conn.getresponse()
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in {'connection', 'server', 'date', 'transfer-encoding'}:
                    self.send_header(key, value)
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            while chunk := response.read(1024 * 1024):
                self.wfile.write(chunk)
        except (OSError, ValueError, http.client.HTTPException):
            self.close_connection = True
        finally:
            conn.close()


def find_binary(configured=''):
    filename = 'cloudflared.exe' if os.name == 'nt' else 'cloudflared'
    candidates = [configured, str(Path(sys.executable).parent / filename),
                  str(Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / filename),
                  str(Path(sys.executable).parent / '_internal' / filename),
                  str(Path.home()/'.local/bin'/filename),
                  str(Path.home()/'.local/bin/cloudflared'), '/opt/homebrew/bin/cloudflared',
                  '/usr/local/bin/cloudflared', shutil.which('cloudflared') or '']
    return next((item for item in candidates if item and Path(item).is_file() and os.access(item, os.X_OK)), '')


def quick_url(line):
    match = re.search(r'https://[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com\b(?![a-z0-9.-])', line)
    return match.group(0) if match else ''


class TunnelManager:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.process = None
        self.origin_port = 0
        self.gateway = None
        self.url = ''
        self.phase = 'off'
        self.error = ''
        self.generation = 0
        self.lock = threading.RLock()
        self.log_file = self.data_dir/'cloudflare.log'

    def status(self):
        with self.lock:
            if self.process is not None and self.process.poll() is not None:
                self.phase, self.url = 'error', ''
                self.error = self.error or '公网连接已中断，请重新开启。'
            ready = self.phase == 'ready'
            return {'phase': self.phase, 'ready': ready, 'running': self.phase in {'starting','ready'},
                    'managed': self.process is not None and self.process.poll() is None,
                    'owned_pid': self.process.pid if self.process is not None and self.process.poll() is None else 0,
                    'public_url': self.url if ready else '', 'error': self.error,
                    'cloudflared_available': bool(find_binary()), 'mode': 'quick'}

    def start(self, origin_port, configured=''):
        with self.lock:
            if self.phase in {'starting','ready'} and self.process is not None and self.process.poll() is None:
                return self.status()
            self.stop()
            binary = find_binary(configured)
            if not binary:
                raise RuntimeError('未找到 cloudflared，请使用包含 Cloudflare 的完整安装包。')
            self.origin_port = int(origin_port)
            self.gateway = PublicGateway(self.origin_port)
            threading.Thread(target=self.gateway.serve_forever, daemon=True).start()
            self.data_dir.mkdir(parents=True, exist_ok=True)
            empty = self.data_dir/'quick-tunnel-config.yml'
            empty.write_text('# App-owned Quick Tunnel; no account credentials.\n')
            # Let cloudflared allocate metrics port; never attach to an unrelated connector.
            command = [binary, 'tunnel', '--config', str(empty), '--no-autoupdate',
                       '--url', f'http://127.0.0.1:{self.gateway.server_port}',
                       '--metrics', '127.0.0.1:0', '--protocol', 'http2', '--loglevel', 'info']
            try:
                self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding='utf-8', errors='replace', bufsize=1, close_fds=True,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), cwd=str(self.data_dir))
            except Exception:
                self.gateway.shutdown()
                self.gateway.server_close()
                self.gateway = None
                raise
            self.phase, self.url, self.error = 'starting', '', ''
            self.generation += 1
            generation = self.generation
            threading.Thread(target=self._monitor, args=(self.process,generation), daemon=True).start()
            threading.Thread(target=self._deadline, args=(generation,), daemon=True).start()
            return self.status()

    def _monitor(self, process, generation):
        with self.log_file.open('w', encoding='utf-8') as log:
            for line in process.stdout:
                log.write(line)
                log.flush()
                found = quick_url(line)
                with self.lock:
                    if generation != self.generation:
                        break
                    if found:
                        self.url = found
                    # A hostname is allocated before the edge connection is usable.
                    if self.url and 'Registered tunnel connection' in line:
                        self.phase = 'ready'
            process.stdout.close()
        with self.lock:
            if generation == self.generation and self.phase != 'off':
                self.phase, self.url = 'error', ''
                self.error = 'Cloudflare 连接失败或中断，请检查网络后重试。'

    def _deadline(self, generation):
        time.sleep(60)
        with self.lock:
            if generation == self.generation and self.phase == 'starting':
                self.stop()
                self.phase = 'error'
                self.error = '连接超时，请检查网络后重试。'

    def stop(self):
        with self.lock:
            self.generation += 1
            process, self.process = self.process, None
            self.phase, self.url, self.error = 'off', '', ''
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            if self.gateway is not None:
                self.gateway.shutdown()
                self.gateway.server_close()
                self.gateway = None
            return {'stopped': process is not None, 'reason': 'managed' if process is not None else 'external'}


_managers = {}

def manager(data_dir):
    key = str(Path(data_dir).resolve())
    if key not in _managers:
        _managers[key] = TunnelManager(data_dir)
    return _managers[key]
