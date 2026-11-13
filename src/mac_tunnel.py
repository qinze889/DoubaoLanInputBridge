"""App-owned Cloudflare Quick Tunnel with a restricted public gateway."""
import http.client
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

STARTUP_TIMEOUT = 90
PROBE_TIMEOUT = 8
PROBE_INTERVAL = 15
RETRY_INTERVAL = 2

GET_PATHS = {'/', '/health', '/files/shared', '/files/download', '/prompt/library'}
POST_PATHS = {'/peer/pair', '/peer/ping', '/peer/endpoint', '/peer/files/start', '/peer/files/chunk', '/peer/files/finish', '/send', '/files/clipboard', '/files/paste', '/files/share', '/prompt/enrich'}


class PublicGateway(ThreadingHTTPServer):
    def __init__(self, origin_port):
        self.origin_port = origin_port
        self.probe_id = secrets.token_hex(16)
        super().__init__(('127.0.0.1', 0), PublicHandler)


class PublicHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Pairing links must never be logged.

    def do_GET(self):
        self.forward(GET_PATHS)

    def do_POST(self):
        self.forward(POST_PATHS)

    def public_health(self):
        # Check the origin, but never expose its PID, executable, state or paths.
        conn = http.client.HTTPConnection('127.0.0.1', self.server.origin_port, timeout=3)
        try:
            conn.request('GET', '/health')
            response = conn.getresponse()
            raw = response.read(16385)
            body = json.loads(raw) if len(raw) <= 16384 else None
            if response.status != 200 or not isinstance(body, dict) or body.get('ok') is not True:
                raise ValueError('unhealthy origin')
        except (OSError, ValueError, http.client.HTTPException):
            self.send_error(502, 'Local service is unavailable')
            return
        finally:
            conn.close()
        payload = json.dumps({'ok': True, 'name': 'Shengjian', 'probe_id': self.server.probe_id}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def forward(self, allowed):
        path = urlsplit(self.path).path or '/'
        if path not in allowed:
            self.send_error(403, 'This endpoint is not available publicly')
            return
        if path == '/health':
            self.public_health()
            return
        conn = http.client.HTTPConnection('127.0.0.1', self.server.origin_port, timeout=90)
        response_started = False
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
            response_started = True
            for key, value in response.getheaders():
                if key.lower() not in {'connection', 'server', 'date', 'transfer-encoding'}:
                    self.send_header(key, value)
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            while chunk := response.read(1024 * 1024):
                self.wfile.write(chunk)
        except (OSError, ValueError, http.client.HTTPException) as exc:
            if not response_started:
                self.send_error(504 if isinstance(exc, TimeoutError) else 502, 'Local service is unavailable')
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


def redact_log(value):
    """Keep diagnostic reasons without exporting pairing links or credentials."""
    value = re.sub(r'(?i)(authorization\s*[:=]\s*)(?:Bearer|Basic)\s+[^\s,;]+',
                   r'\1[redacted]', str(value))
    value = re.sub(r'''(?i)(["'](?:key|token|secret|password|access_key|authorization)["']\s*:\s*)(["'])(.*?)\2''',
                   lambda match: match.group(1) + match.group(2) + '[redacted]' + match.group(2), value)
    value = re.sub(r'https://[a-z0-9-]+\.trycloudflare\.com\b',
                   'https://<tunnel>.trycloudflare.com', str(value), flags=re.I)
    value = re.sub(r'(?i)([?&](?:key|token|access_token|secret|password)=)[^&\s\"\']+',
                   r'\1[redacted]', value)
    value = re.sub(r'(?i)((?:authorization|token|secret|password|access_key)\s*[=:]\s*)(?:\"[^\"]*\"|\'[^\']*\'|[^\s,;]+)',
                   r'\1[redacted]', value)
    return value[:2048].rstrip()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class TunnelManager:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.process = None
        self.origin_port = 0
        self.gateway = None
        self.url = ''
        self.phase = 'off'
        self.stage = 'off'
        self.error = ''
        self.last_error = ''
        self.binary_path = ''
        self.protocol = 'http2'
        self.connections = set()
        self.probe_epoch = 0
        self.verified_at = 0
        self.attempt_started = 0
        self.elapsed_seconds = 0
        self.deadline_at = None
        self.generation = 0
        self.cancel = threading.Event()
        self.lock = threading.RLock()
        self.logs = deque(maxlen=40)
        self.log_file = self.data_dir/'cloudflare.log'

    def status(self):
        with self.lock:
            if self.process is not None and self.process.poll() is not None:
                self._fail(self.generation, self._failure_message('Cloudflare 进程已退出'))
            ready = self.phase == 'ready'
            managed = self.process is not None and self.process.poll() is None
            elapsed = int(time.monotonic() - self.attempt_started) if self.attempt_started and self.phase == 'starting' else self.elapsed_seconds
            return {'phase': self.phase, 'stage': self.stage, 'ready': ready,
                    'running': self.phase in {'starting', 'ready'}, 'managed': managed,
                    'owned_pid': self.process.pid if managed else 0,
                    'public_url': self.url if ready else '', 'error': self.error,
                    'last_error': self.last_error, 'elapsed_seconds': max(0, elapsed),
                    'protocol': self.protocol, 'binary_path': self.binary_path,
                    'verified_at': self.verified_at, 'log_tail': '\n'.join(self.logs),
                    'cloudflared_available': bool(self.binary_path or find_binary()), 'mode': 'quick'}

    def start(self, origin_port, configured=''):
        with self.lock:
            if self.phase in {'starting', 'ready'} and self.process is not None and self.process.poll() is None:
                return self.status()
            self.stop()
            binary = find_binary(configured)
            if not binary:
                raise RuntimeError('未找到 cloudflared，请使用包含 Cloudflare 的完整安装包。')
            self.binary_path = str(Path(binary).resolve())
            self.origin_port = int(origin_port)
            self.data_dir.mkdir(parents=True, exist_ok=True)
            empty = self.data_dir/'quick-tunnel-config.yml'
            # A comment-only YAML file produces a misleading ERR in cloudflared.
            empty.write_text('{}\n', encoding='utf-8')
            self.log_file.write_text('', encoding='utf-8')
            self.logs.clear()
            self.gateway = PublicGateway(self.origin_port)
            threading.Thread(target=self.gateway.serve_forever, daemon=True).start()
            # Keep the explicit TCP transport while diagnosing connectivity.
            # HTTP/2 tunnels use TCP 7844, not the browser's HTTPS 443 route.
            command = [self.binary_path, 'tunnel', '--config', str(empty), '--no-autoupdate',
                       '--url', f'http://127.0.0.1:{self.gateway.server_port}',
                       '--metrics', '127.0.0.1:0', '--protocol', self.protocol, '--loglevel', 'info']
            try:
                self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding='utf-8', errors='replace', bufsize=1, close_fds=True,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), cwd=str(self.data_dir))
            except Exception:
                self.gateway.shutdown()
                self.gateway.server_close()
                self.gateway = None
                raise
            self.phase, self.stage, self.url, self.error = 'starting', 'allocating', '', ''
            self.last_error = ''
            self.attempt_started = time.monotonic()
            self.deadline_at = self.attempt_started + STARTUP_TIMEOUT
            self.elapsed_seconds = 0
            self.verified_at = 0
            self.connections.clear()
            self.probe_epoch += 1
            self.generation += 1
            generation = self.generation
            self.cancel = threading.Event()
            threading.Thread(target=self._monitor, args=(self.process, generation), daemon=True).start()
            threading.Thread(target=self._verify, args=(generation, self.cancel), daemon=True).start()
            threading.Thread(target=self._deadline, args=(generation, self.cancel), daemon=True).start()
            return self.status()

    def _handle_line(self, line, generation):
        with self.lock:
            if generation != self.generation or self.phase not in {'starting', 'ready'}:
                return
            self.logs.append(redact_log(line))
            found = quick_url(line)
            if found and found != self.url:
                self.url = found
                self.probe_epoch += 1
                self.phase = 'starting'
                self.stage = 'verifying' if self.connections else 'connecting'
            match = re.search(r'\bconnIndex=(\d+)\b', line)
            index = match.group(1) if match else '0'
            if 'Registered tunnel connection' in line:
                self.connections.add(index)
                if self.phase != 'ready':
                    self.stage = 'verifying' if self.url else 'allocating'
            elif any(message in line for message in (
                'Connection terminated', 'Unregistered tunnel connection',
                'Serve tunnel error', 'Retrying connection', 'Failed to serve tunnel')):
                if match:
                    self.connections.discard(index)
                else:
                    self.connections.clear()
                if not self.connections:
                    self.probe_epoch += 1
                    if self.phase == 'ready':
                        self.attempt_started = time.monotonic()
                        self.deadline_at = self.attempt_started + STARTUP_TIMEOUT
                    self.phase = 'starting'
                    self.stage = 'reconnecting' if self.verified_at else ('connecting' if self.url else 'allocating')
            # Background QUIC/management prechecks also log ERR in HTTP/2 mode.
            # Preserve them in the log, but do not treat every ERR as a root cause.
            lower = line.lower()
            is_error = line.startswith('ERR ') or ' ERR ' in line or 'level=error' in line
            diagnostic_only = any(word in lower for word in ('precheck', 'pre-check', 'connectivity check', 'management', 'quic', 'configuration file'))
            if is_error and not diagnostic_only:
                self.last_error = redact_log(line)[-600:]

    def _monitor(self, process, generation):
        try:
            log = self.log_file.open('a', encoding='utf-8')
        except OSError:
            log = None
        try:
            for line in process.stdout:
                with self.lock:
                    if generation != self.generation:
                        break
                    self._handle_line(line, generation)
                    if log is not None:
                        try:
                            log.write(redact_log(line) + '\n')
                            log.flush()
                        except OSError:
                            log.close()
                            log = None
        finally:
            process.stdout.close()
            if log is not None:
                log.close()
        with self.lock:
            if generation == self.generation and self.phase != 'off':
                self._fail(generation, self._failure_message('Cloudflare 连接失败或中断'))

    def _probe_public(self, url, gateway):
        if quick_url(url) != url or gateway is None:
            return False, '公网地址尚未准备好'
        # Use a fresh query and instance identity: cached health responses, a
        # gateway for an old attempt, and an unreachable origin must all fail.
        request = Request(url + '/health?probe=' + secrets.token_hex(8),
                          headers={'Cache-Control': 'no-cache', 'User-Agent': 'Shengjian-Tunnel-Probe'})
        try:
            opener = build_opener(ProxyHandler({}), NoRedirect())
            with opener.open(request, timeout=PROBE_TIMEOUT) as response:
                raw = response.read(4097)
                body = json.loads(raw) if len(raw) <= 4096 else None
                if response.status != 200 or not isinstance(body, dict) or body.get('ok') is not True or body.get('probe_id') != gateway.probe_id:
                    return False, '公网响应未通过本次应用实例校验'
                return True, ''
        except HTTPError as exc:
            code = exc.code
            exc.close()
            return False, f'公网验证返回 HTTP {code}'
        except (OSError, ValueError, URLError, http.client.HTTPException) as exc:
            return False, '公网验证失败：' + redact_log(str(exc))[:400]

    def _apply_probe(self, generation, epoch, ok, reason):
        with self.lock:
            if generation != self.generation or epoch != self.probe_epoch or not self.connections or self.phase not in {'starting', 'ready'}:
                return
            if self.deadline_at is not None and time.monotonic() >= self.deadline_at:
                self._fail(generation, self._failure_message('连接超时'))
                return
            if ok:
                self.phase, self.stage, self.error = 'ready', 'ready', ''
                self.last_error = ''
                self.verified_at = time.time()
                self.elapsed_seconds = max(0, int(time.monotonic() - self.attempt_started)) if self.attempt_started else 0
                self.deadline_at = None
            else:
                if self.phase == 'ready':
                    self.attempt_started = time.monotonic()
                    self.deadline_at = self.attempt_started + STARTUP_TIMEOUT
                self.phase, self.stage = 'starting', 'verifying'
                self.last_error = redact_log(reason)

    def _verify(self, generation, cancel):
        next_probe = 0
        while not cancel.is_set():
            with self.lock:
                if generation != self.generation or self.phase not in {'starting', 'ready'}:
                    return
                now = time.monotonic()
                if self.deadline_at is not None and now >= self.deadline_at:
                    self._fail(generation, self._failure_message('连接超时'))
                    return
                url, gateway, epoch = self.url, self.gateway, self.probe_epoch
                should_probe = bool(url and self.connections and now >= next_probe)
            if should_probe:
                ok, reason = self._probe_public(url, gateway)
                self._apply_probe(generation, epoch, ok, reason)
                next_probe = time.monotonic() + (PROBE_INTERVAL if ok else RETRY_INTERVAL)
            cancel.wait(RETRY_INTERVAL)

    def _deadline(self, generation, cancel):
        # DNS resolution can outlive a socket timeout. Keep the lifecycle bound
        # independent of the probe thread, and reject any result after stop().
        while not cancel.wait(RETRY_INTERVAL):
            with self.lock:
                if generation != self.generation or self.phase not in {'starting', 'ready'}:
                    return
                if self.deadline_at is not None and time.monotonic() >= self.deadline_at:
                    self._fail(generation, self._failure_message('连接超时'))
                    return

    def _failure_message(self, prefix):
        detail = {
            'allocating': '未能申请 Cloudflare 临时地址',
            'connecting': '未连通 Cloudflare 边缘（HTTP/2，TCP 7844）',
            'reconnecting': 'Cloudflare 边缘连接中断后未能恢复（TCP 7844）',
            'verifying': 'Cloudflare 已注册连接，但本机未能验证公网地址及本地服务',
        }.get(self.stage, '公网连接未通过验证')
        return f'{prefix}：{detail}。' + (f'最近错误：{self.last_error}' if self.last_error else '请展开连接诊断查看日志。')

    def _fail(self, generation, message):
        with self.lock:
            if generation != self.generation:
                return
            stage, reason = self.stage, self.last_error
            elapsed = max(0, int(time.monotonic() - self.attempt_started)) if self.attempt_started else 0
            self.stop()
            self.phase, self.stage, self.error = 'error', stage, message
            self.last_error, self.elapsed_seconds = reason, elapsed

    def stop(self):
        with self.lock:
            self.cancel.set()
            self.generation += 1
            self.probe_epoch += 1
            process, self.process = self.process, None
            self.phase, self.stage, self.url, self.error = 'off', 'off', '', ''
            self.last_error = ''
            self.connections.clear()
            self.deadline_at = None
            self.attempt_started = 0
            self.elapsed_seconds = 0
            self.verified_at = 0
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

