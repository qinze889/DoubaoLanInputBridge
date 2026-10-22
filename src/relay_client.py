"""Outbound HTTPS phone connector; desktop routes and automatic paste replay forbidden."""
import base64
import http.client
import json
import re
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

GET_PATHS = {'/files/shared', '/files/download', '/prompt/library'}
POST_PATHS = {'/send', '/prompt/enrich', '/files/clipboard', '/files/paste', '/files/share'}
MAX_BYTES = 16 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def valid_route(method, path):
    parsed = urlsplit(path)
    return not parsed.scheme and not parsed.netloc and not parsed.fragment and parsed.path in (GET_PATHS if method == 'GET' else POST_PATHS if method == 'POST' else set())


class RelayClient:
    def __init__(self, config, origin_port, key_provider):
        self.config = dict(config)
        base = str(config['url']).rstrip('/')
        parsed = urlsplit(base)
        if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in {'127.0.0.1', 'localhost'}):
            raise ValueError('中转服务必须使用 HTTPS')
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('中转地址不应包含凭据')
        if not re.fullmatch(r'[a-f0-9]{24}', str(config['device_id'])):
            raise ValueError('无效设备编号')
        self.base = base
        self.origin_port = int(origin_port)
        self.key_provider = key_provider
        self.stop_event = threading.Event()
        self.thread = None
        self.responses = {}
        self.status = {'phase': 'off', 'error': '', 'last_seen': 0}
        self.opener = build_opener(NoRedirect())

    def start(self):
        if not self.thread or not self.thread.is_alive():
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()

    def close(self):
        self.stop_event.set()

    def call(self, suffix, body=None):
        request = Request(self.base + '/connector/' + self.config['device_id'] + suffix,
                          None if body is None else json.dumps(body).encode(),
                          {'Authorization': 'Bearer ' + self.config['token'], 'Content-Type': 'application/json'})
        with self.opener.open(request, timeout=35) as response:
            return json.loads(response.read(MAX_BYTES * 2))

    def capability(self):
        connection = http.client.HTTPConnection('127.0.0.1', self.origin_port, timeout=3)
        try:
            connection.request('GET', '/desktop/state?' + urlencode({'key': self.key_provider()}))
            result = json.loads(connection.getresponse().read(65536))
            return '1' if result.get('accessibility') else '0'
        except (OSError, ValueError, http.client.HTTPException):
            return '0'
        finally:
            connection.close()

    def execute(self, job):
        ident = job['id']
        if ident in self.responses:
            return self.responses[ident]
        method, path = job['method'], job['path']
        if not valid_route(method, path):
            raise ValueError('中转请求被拒绝')
        parsed, key = urlsplit(path), self.key_provider()
        query = [(k, v) for k, v in parse_qsl(parsed.query) if k != 'key'] + [('key', key)]
        path = parsed.path + '?' + urlencode(query)
        body = base64.b64decode(job.get('body', ''), validate=True)
        if len(body) > MAX_BYTES:
            raise ValueError('文件超过 16 MiB 限制')
        content_type = job.get('content_type', 'application/json')
        if method == 'POST':
            if content_type.startswith('application/json'):
                payload = json.loads(body)
                payload['key'] = key
                body = json.dumps(payload).encode()
            elif content_type.startswith('multipart/form-data'):
                match = re.search(r'boundary=(?:"([^"\r\n]+)"|([^;\s\r\n]+))', content_type)
                if not match:
                    raise ValueError('无效上传格式')
                boundary = (match.group(1) or match.group(2)).encode('ascii')
                body = b'--' + boundary + b'\r\nContent-Disposition: form-data; name="key"\r\n\r\n' + key.encode() + b'\r\n' + body
            else:
                raise ValueError('不支持的请求格式')
        connection = http.client.HTTPConnection('127.0.0.1', self.origin_port, timeout=75)
        try:
            connection.request(method, path, body if method == 'POST' else None, {'Content-Type': content_type, 'X-Bridge-Public': '1'})
            response = connection.getresponse()
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                result = {'status': 413, 'body': base64.b64encode(b'{"ok":false,"error":"Download exceeds 16 MiB"}').decode(), 'content_type': 'application/json'}
            else:
                result = {'status': response.status, 'body': base64.b64encode(data).decode(), 'content_type': response.getheader('Content-Type', 'application/octet-stream')}
        except (OSError, http.client.HTTPException):
            result = {'status': 502, 'body': base64.b64encode(json.dumps({'ok': False, 'error': '电脑处理结果未知，请在电脑确认后再发送。'}).encode()).decode(), 'content_type': 'application/json'}
        finally:
            connection.close()
        self.responses[ident] = result
        if len(self.responses) > 128:
            self.responses.pop(next(iter(self.responses)))
        return result

    def run(self):
        while not self.stop_event.is_set():
            try:
                reply = self.call('/poll?can_paste=' + self.capability())
                if self.stop_event.is_set():
                    return
                self.status.update(phase='online', error='', last_seen=time.time())
                for job in reply.get('requests', []):
                    result = self.execute(job)
                    for attempt in range(3):
                        try:
                            self.call('/result', {'id': job['id'], **result})
                            break
                        except (OSError, ValueError):
                            if self.stop_event.wait(1 + attempt):
                                return
            except HTTPError as exc:
                self.status.update(phase='error', error='设备授权已失效' if exc.code in (401, 403) else '中转服务暂不可用')
                if self.stop_event.wait(5):
                    return
            except (OSError, ValueError, KeyError):
                self.status.update(phase='reconnecting', error='连接中断，正在重连')
                if self.stop_event.wait(3):
                    return


def from_data_dir(data_dir, port, key_provider):
    path = Path(data_dir) / 'relay.json'
    if not path.is_file():
        return None
    config = json.loads(path.read_text(encoding='utf-8'))
    if not config.get('enabled', True):
        return None
    client = RelayClient(config, port, key_provider)
    client.start()
    return client


def phone_url(data_dir, include_disabled=False):
    try:
        config = json.loads((Path(data_dir) / 'relay.json').read_text(encoding='utf-8'))
        if not include_disabled and not config.get('enabled', True):
            return ''
        base = str(config['url']).rstrip('/')
        client = RelayClient(config, 1, lambda: '')
        token = str(config['mobile_token'])
        if not re.fullmatch(r'[A-Za-z0-9_-]{32,100}', token):
            return ''
        return base + '/d/' + client.config['device_id'] + '/#' + token
    except (OSError, ValueError, KeyError):
        return ''
