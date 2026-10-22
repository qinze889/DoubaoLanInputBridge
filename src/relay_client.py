"""Outbound HTTPS phone connector; desktop routes and automatic paste replay forbidden."""
import base64
import http.client
import json
import hashlib
import re
import secrets
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

GET_PATHS = {'/files/shared', '/files/download', '/prompt/library'}
POST_PATHS = {'/send', '/prompt/enrich', '/files/clipboard', '/files/paste', '/files/share'}
MAX_BYTES = 16 * 1024 * 1024
PEER_PATHS = {'/peer/pair', '/peer/ping', '/peer/endpoint', '/peer/files/start', '/peer/files/chunk', '/peer/files/finish'}
PEER_HEADERS = {'X-Shengjian-Peer', 'X-Shengjian-Time', 'X-Shengjian-Nonce', 'X-Shengjian-SHA256', 'X-Shengjian-Signature'}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def valid_route(method, path):
    parsed = urlsplit(path)
    return not parsed.scheme and not parsed.netloc and not parsed.fragment and parsed.path in (GET_PATHS if method == 'GET' else POST_PATHS if method == 'POST' else set())


def valid_peer_route(method, path):
    parsed = urlsplit(path)
    return method == 'POST' and not parsed.scheme and not parsed.netloc and not parsed.fragment and parsed.path in PEER_PATHS


class RelayClient:
    def __init__(self, config, origin_port, key_provider, peer_manager=None):
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
        self.session = secrets.token_hex(16)
        self.responses = {}
        self.execute_lock = threading.RLock()
        self.peer_manager = peer_manager
        self.mode = config.get('connection_mode', 'public')
        self.rtc = None
        if self.mode == 'p2p':
            from rtc_bridge import RTCBridge
            self.rtc = RTCBridge(lambda job: self.execute(job, allow_signal=False))
        self.status = {'phase': 'off', 'error': '', 'last_seen': 0}
        self.opener = build_opener(NoRedirect())

    def start(self):
        if not self.thread or not self.thread.is_alive():
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.rtc:
            self.rtc.close()

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

    def execute(self, job, allow_signal=True):
        with self.execute_lock:
            return self._execute(job, allow_signal)

    def _execute(self, job, allow_signal):
        ident = job['id']
        if ident in self.responses:
            return self.responses[ident]
        method, path = job['method'], job['path']
        if self.mode == 'p2p' and allow_signal and urlsplit(path).path not in ('/p2p/offer', '/peer/p2p/offer', '/peer/pair', '/peer/ping', '/peer/endpoint'):
            raise ValueError('P2P 模式拒绝通过服务器中转内容')
        body = base64.b64decode(job.get('body', ''), validate=True)
        if allow_signal and method == 'POST' and path in ('/p2p/offer', '/peer/p2p/offer'):
            if not self.rtc or len(body) > 65536:
                raise ValueError('P2P 当前未启用')
            if path.startswith('/peer/'):
                if not self.peer_manager: raise ValueError('机器共享未初始化')
                _, digest = self.peer_manager.authenticate(method, path, job.get('headers', {}))
                if hashlib.sha256(body).hexdigest() != digest: raise ValueError('P2P 握手签名错误')
            peer_only = path.startswith('/peer/')
            def execute_channel(request):
                valid = valid_peer_route if peer_only else valid_route
                if not valid(request.get('method'), request.get('path', '')):
                    raise ValueError('P2P 通道不允许此操作')
                return self.execute(request, allow_signal=False)
            answer = self.rtc.answer(json.loads(body), execute_channel)
            return {'status': 200, 'content_type': 'application/json', 'body': base64.b64encode(json.dumps({'ok': True, 'answer': answer}).encode()).decode()}
        is_peer = valid_peer_route(method, path)
        if not valid_route(method, path) and not is_peer:
            raise ValueError('中转请求被拒绝')
        parsed, key = urlsplit(path), self.key_provider()
        query = [(k, v) for k, v in parse_qsl(parsed.query) if k != 'key'] + [('key', key)]
        if not is_peer: path = parsed.path + '?' + urlencode(query)
        if len(body) > MAX_BYTES:
            raise ValueError('文件超过 16 MiB 限制')
        content_type = job.get('content_type', 'application/json')
        if method == 'POST' and not is_peer:
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
            headers = {'Content-Type': content_type, 'X-Bridge-Public': '1'}
            if is_peer: headers.update({k: v for k, v in job.get('headers', {}).items() if k in PEER_HEADERS})
            connection.request(method, path, body if method == 'POST' else None, headers)
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
        while len(self.responses) > 128 or sum(len(v.get('body', '')) for v in self.responses.values()) > 64 * 1024 * 1024:
            self.responses.pop(next(iter(self.responses)))
        return result

    def run(self):
        while not self.stop_event.is_set():
            try:
                reply = self.call('/poll?can_paste=' + self.capability() + '&mode=' + ('p2p' if self.mode == 'p2p' else 'public') + '&session=' + self.session)
                if self.stop_event.is_set():
                    return
                self.status.update(phase='online', error='', last_seen=time.time())
                for job in reply.get('requests', []):
                    try:
                        result = self.execute(job)
                    except (ValueError, KeyError, OSError, RuntimeError):
                        result = {'status': 400, 'content_type': 'application/json', 'body': base64.b64encode(json.dumps({'ok': False, 'error': '连接请求被拒绝，请检查连接方式和配对状态'}).encode()).decode()}
                    for attempt in range(3):
                        try:
                            self.call('/result', {'id': job['id'], **result})
                            break
                        except (OSError, ValueError):
                            if self.stop_event.wait(1 + attempt):
                                return
            except HTTPError as exc:
                if exc.code in (401, 403) and self.rtc:
                    self.rtc.close()
                    self.rtc = None
                self.status.update(phase='error', error='设备授权已失效' if exc.code in (401, 403) else '中转服务暂不可用')
                if self.stop_event.wait(5):
                    return
            except (OSError, ValueError, KeyError):
                self.status.update(phase='reconnecting', error='连接中断，正在重连')
                if self.stop_event.wait(3):
                    return


def from_data_dir(data_dir, port, key_provider, peer_manager=None):
    path = Path(data_dir) / 'relay.json'
    if not path.is_file():
        return None
    config = json.loads(path.read_text(encoding='utf-8'))
    if not config.get('enabled', True):
        return None
    client = RelayClient(config, port, key_provider, peer_manager)
    client.start()
    return client


def phone_url(data_dir, include_disabled=False):
    try:
        config = json.loads((Path(data_dir) / 'relay.json').read_text(encoding='utf-8'))
        if not include_disabled and not config.get('enabled', True):
            return ''
        base = str(config['url']).rstrip('/')
        client = RelayClient({**config, 'connection_mode': 'public'}, 1, lambda: '')
        token = str(config['mobile_token'])
        if not re.fullmatch(r'[A-Za-z0-9_-]{32,100}', token):
            return ''
        return base + '/d/' + client.config['device_id'] + '/#' + token
    except (OSError, ValueError, KeyError):
        return ''
