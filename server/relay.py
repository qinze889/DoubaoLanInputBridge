#!/usr/bin/env python3
"""Self-hosted Shengjian relay: authenticated devices, bounded transient requests.

No clipboard text or file body is written to disk. A request is consumed once;
there is no automatic replay after a broken connection. Device credentials are
stored in a private 0600 file. Deploy behind HTTPS with access logging disabled.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from relay_client import valid_route, MAX_BYTES

ROOT = Path(__file__).resolve().parent


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Relay(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128

    def __init__(self, address, directory, prefix='/shengjian', timeout=85):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / 'credentials.json'
        self.prefix = prefix.rstrip('/')
        self.timeout = timeout
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        if self.path.exists():
            self.config = json.loads(self.path.read_text())
        else:
            self.config = {'admin_token': secrets.token_urlsafe(32), 'devices': {}}
            self.save()
        self.jobs = {}
        self.seen = {}
        self.capabilities = {}
        self.sessions = {}
        self.failures = {}
        self.total = {'delivered': 0, 'failed': 0}
        super().__init__(address, Handler)

    def save(self):
        temporary = self.path.with_suffix('.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(self.config, stream, ensure_ascii=False)
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)

    def enroll(self, name):
        with self.lock:
            if len(self.config['devices']) >= 32:
                raise ValueError('最多管理 32 台设备')
            ident, token, mobile = secrets.token_hex(12), secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            self.config['devices'][ident] = {'name': str(name)[:80] or '电脑', 'token_hash': digest(token), 'mobile_token': mobile, 'enabled': True}
            self.save()
            return {'device_id': ident, 'token': token, 'mobile_token': mobile}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(100)

    def send(self, status, data, content_type='application/json; charset=utf-8', cookie=None, download=None):
        body = json.dumps(data, ensure_ascii=False).encode() if isinstance(data, (dict, list)) else data
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        if download is not None:
            from urllib.parse import quote
            self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + quote(download, safe=''))
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def error(self, status, message):
        self.send(status, {'ok': False, 'error': message})

    def read_body(self, limit=MAX_BYTES):
        if self.headers.get('Transfer-Encoding'):
            raise ValueError('不支持分块请求')
        length = int(self.headers.get('Content-Length', '0'))
        if length < 0 or length > limit:
            raise ValueError('单个文件上限 16 MiB')
        body = self.rfile.read(length)
        if len(body) != length:
            raise ValueError('上传未完成')
        return body

    def json_body(self):
        return json.loads(self.read_body(MAX_BYTES * 2))

    def cookies(self):
        try:
            cookies = SimpleCookie(self.headers.get('Cookie', ''))
            return {k: v.value for k, v in cookies.items()}
        except Exception:
            return {}

    def admin(self):
        token = self.cookies().get('sj_admin', '')
        with self.server.lock:
            expiry = self.server.sessions.get(token, 0)
        return expiry > time.time()

    def device(self, ident, connector=False):
        with self.server.lock:
            row = self.server.config['devices'].get(ident, {})
            if not row.get('enabled'):
                return False
            if connector:
                auth = self.headers.get('Authorization', '').removeprefix('Bearer ')
                return hmac.compare_digest(digest(auth), row['token_hash'])
            return hmac.compare_digest(self.cookies().get('sj_phone_' + ident, ''), row['mobile_token'])

    def do_GET(self):
        self.dispatch('GET')

    def do_POST(self):
        self.dispatch('POST')

    def dispatch(self, method):
        try:
            self.route(method)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            self.error(400, '请求格式错误或内容超过限制')
        except (OSError, TimeoutError):
            self.error(502, '连接中断，请检查设备状态')

    def route(self, method):
        prefix = self.server.prefix
        path = urlsplit(self.path).path
        if not path.startswith(prefix + '/'):
            self.error(404, '不存在的入口')
            return
        path = path[len(prefix):]
        if path == '/health' and method == 'GET':
            self.send(200, {'ok': True, 'service': 'Shengjian relay', 'version': '1.3.0'})
            return
        if path == '/' and method == 'GET':
            self.send(200, (ROOT / 'console.html').read_bytes(), 'text/html; charset=utf-8')
            return
        if path == '/login' and method == 'POST':
            now = time.time()
            addr = self.client_address[0]
            with self.server.lock:
                recent = [ts for ts in self.server.failures.get(addr, []) if now - ts < 300]
                self.server.failures[addr] = recent
                if len(recent) >= 10:
                    self.error(429, '尝试过于频繁，请稍后再试')
                    return
            code = str(self.json_body().get('code', ''))
            if not hmac.compare_digest(code, self.server.config['admin_token']):
                with self.server.lock:
                    self.server.failures[addr].append(now)
                self.error(401, '管理口令不正确')
                return
            session = secrets.token_urlsafe(32)
            with self.server.lock:
                self.server.sessions = {k: v for k, v in self.server.sessions.items() if v > now}
                self.server.sessions[session] = now + 7 * 86400
            self.send(200, {'ok': True}, cookie=f'sj_admin={session}; Path={prefix}/; HttpOnly; Secure; SameSite=Strict; Max-Age=604800')
            return
        if path.startswith('/admin/'):
            if not self.admin():
                self.error(401, '请先登录管理后台')
                return
            if path == '/admin/qr' and method == 'GET':
                from io import BytesIO
                from urllib.parse import parse_qs
                import qrcode
                import qrcode.image.svg
                ident = parse_qs(urlsplit(self.path).query)['id'][0]
                row = self.server.config['devices'][ident]
                if not row['enabled']:
                    self.error(403, '设备已停用')
                    return
                # The public origin is pinned by deployment, never taken from Host.
                origin = os.environ.get('SHENGJIAN_ORIGIN', 'https://server.xjiaoai.com')
                url = origin + prefix + '/d/' + ident + '/#' + row['mobile_token']
                output = BytesIO()
                qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage).save(output)
                self.send(200, output.getvalue(), 'image/svg+xml')
                return
            if path == '/admin/devices' and method == 'GET':
                with self.server.lock:
                    devices = [{'id': ident, 'name': row['name'], 'enabled': row['enabled'],
                                'online': time.monotonic() - self.server.seen.get(ident, 0) < 35,
                                'mobile_path': prefix + '/d/' + ident + '/#' + row['mobile_token']}
                               for ident, row in self.server.config['devices'].items()]
                    self.send(200, {'ok': True, 'devices': devices, 'stats': dict(self.server.total)})
                return
            if path == '/admin/devices' and method == 'POST':
                self.send(200, {'ok': True, **self.server.enroll(self.json_body().get('name', '电脑'))})
                return
            if path == '/admin/revoke' and method == 'POST':
                ident = self.json_body()['id']
                with self.server.changed:
                    self.server.config['devices'][ident]['enabled'] = False
                    self.server.save()
                    for job in self.server.jobs.values():
                        if job['device'] == ident:
                            job['event'].set()
                    self.server.changed.notify_all()
                self.send(200, {'ok': True})
                return
        match = re.fullmatch(r'/connector/([a-f0-9]{24})/(poll|result)', path)
        if match:
            ident, action = match.groups()
            if not self.device(ident, True):
                self.error(401, '设备未授权')
                return
            if action == 'poll' and method == 'GET':
                from urllib.parse import parse_qs
                can_paste = (parse_qs(urlsplit(self.path).query).get('can_paste') or ['0'])[0] == '1'
                deadline = time.monotonic() + 20
                with self.server.changed:
                    self.server.capabilities[ident] = can_paste
                    self.server.seen[ident] = time.monotonic()
                    while True:
                        jobs = [j for j in self.server.jobs.values() if j['device'] == ident and not j['taken']]
                        if jobs or time.monotonic() >= deadline:
                            break
                        self.server.changed.wait(min(1, deadline - time.monotonic()))
                        if not self.device(ident, True):
                            self.error(401, '设备授权已撤销')
                            return
                    requests = []
                    for job in jobs[:1]:
                        job['taken'] = True
                        requests.append(job['request'])
                    self.server.seen[ident] = time.monotonic()
                self.send(200, {'ok': True, 'requests': requests})
                return
            if action == 'result' and method == 'POST':
                result = self.json_body()
                status = int(result['status'])
                if status < 200 or status > 599:
                    raise ValueError('status')
                payload = base64.b64decode(result['body'], validate=True)
                if len(payload) > MAX_BYTES:
                    raise ValueError('body')
                with self.server.lock:
                    job = self.server.jobs.get(result['id'])
                    if job and job['device'] == ident and job['taken']:
                        job['result'] = (status, payload, str(result.get('content_type', 'application/octet-stream')))
                        job['event'].set()
                self.send(200, {'ok': True})
                return
        match = re.fullmatch(r'/d/([a-f0-9]{24})(/.*)', path)
        if match:
            ident, subpath = match.groups()
            if subpath == '/' and method == 'GET':
                self.send(200, (ROOT / 'phone.html').read_bytes(), 'text/html; charset=utf-8')
                return
            if subpath == '/login' and method == 'POST':
                code = str(self.json_body().get('code', ''))
                row = self.server.config['devices'].get(ident, {})
                if not row.get('enabled') or not hmac.compare_digest(code, row.get('mobile_token', '')):
                    self.error(401, '连接码已失效，请重新扫码')
                    return
                self.send(200, {'ok': True}, cookie=f'sj_phone_{ident}={code}; Path={prefix}/d/{ident}/; HttpOnly; Secure; SameSite=Strict; Max-Age=2592000')
                return
            if not self.device(ident):
                self.error(401, '请从电脑重新扫码连接')
                return
            if subpath == '/status' and method == 'GET':
                with self.server.lock:
                    row = self.server.config['devices'][ident]
                    self.send(200, {'ok': True, 'name': row['name'], 'online': time.monotonic() - self.server.seen.get(ident, 0) < 35,
                                    'can_paste': self.server.capabilities.get(ident, False)})
                return
            if subpath.startswith('/r/'):
                route = subpath[2:]
                query = urlsplit(self.path).query
                if query:
                    route += '?' + query
                if not valid_route(method, route):
                    self.error(403, '此操作不允许通过公网调用')
                    return
                if route.split('?')[0] == '/health':
                    self.error(403, '请使用设备状态接口')
                    return
                body = self.read_body() if method == 'POST' else b''
                with self.server.changed:
                    if time.monotonic() - self.server.seen.get(ident, 0) >= 35:
                        self.error(503, '电脑离线，请打开声笺并检查网络')
                        return
                    if len(self.server.jobs) >= 16 or sum(len(j['request']['body']) for j in self.server.jobs.values()) + len(body) * 1.34 > 64 * 1024 * 1024:
                        self.error(429, '服务繁忙，请稍后重试')
                        return
                    job_id = secrets.token_hex(16)
                    job = {'device': ident, 'taken': False, 'event': threading.Event(), 'result': None,
                           'request': {'id': job_id, 'method': method, 'path': route, 'body': base64.b64encode(body).decode(), 'content_type': self.headers.get('Content-Type', 'application/json')}}
                    self.server.jobs[job_id] = job
                    self.server.changed.notify_all()
                job['event'].wait(self.server.timeout)
                with self.server.lock:
                    self.server.jobs.pop(job_id, None)
                    result = job['result']
                    self.server.total['delivered' if result and result[0] < 400 else 'failed'] += 1
                if result:
                    if route.split('?')[0] == '/files/download':
                        from urllib.parse import parse_qs
                        name = (parse_qs(urlsplit(route).query).get('file') or ['download'])[0]
                        self.send(*result, download=name)
                    else:
                        self.send(*result)
                else:
                    self.error(504, '电脑未返回结果，请在电脑确认后再发送；本次不会自动重发。')
                return
        self.error(404, '不存在的入口')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', required=True)
    parser.add_argument('--port', type=int, default=18766)
    parser.add_argument('--prefix', default='/shengjian')
    args = parser.parse_args()
    server = Relay(('127.0.0.1', args.port), args.data, args.prefix)
    print('Shengjian relay listening on loopback', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
