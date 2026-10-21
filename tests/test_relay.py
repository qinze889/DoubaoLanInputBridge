"""Exercise phone -> real relay -> outbound connector -> desktop HTTP contracts."""
import base64
import hashlib
import http.client
import importlib.util
import json
import threading
import time
from pathlib import Path

import pytest
import gui_app as bridge
from relay_client import RelayClient, valid_route, phone_url

spec = importlib.util.spec_from_file_location('shengjian_relay_server', Path(__file__).resolve().parents[1] / 'server/relay.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def request(server, method, path, data=None, headers=None):
    connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
    if isinstance(data, dict):
        data = json.dumps(data).encode()
    connection.request(method, '/shengjian' + path, data, {'Content-Type': 'application/json', **(headers or {})})
    response = connection.getresponse()
    result = response.status, response.read(), dict(response.getheaders())
    connection.close()
    return result


@pytest.fixture
def relay(tmp_path):
    service = module.Relay(('127.0.0.1', 0), tmp_path / 'relay', timeout=2)
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    yield service
    service.shutdown()
    service.server_close()


def login(relay):
    status, body, headers = request(relay, 'POST', '/login', {'code': relay.config['admin_token']})
    assert status == 200
    assert 'Secure' in headers['Set-Cookie'] and 'HttpOnly' in headers['Set-Cookie']
    return {'Cookie': headers['Set-Cookie'].split(';')[0]}


def enroll(relay):
    admin = login(relay)
    status, body, _ = request(relay, 'POST', '/admin/devices', {'name': '测试电脑'}, admin)
    assert status == 200
    device = json.loads(body)
    ident = device['device_id']
    status, _, headers = request(relay, 'POST', f'/d/{ident}/login', {'code': device['mobile_token']})
    assert status == 200
    return device, {'Cookie': headers['Set-Cookie'].split(';')[0]}, admin


def test_auth_offline_and_private_routes(relay):
    assert request(relay, 'GET', '/admin/devices')[0] == 401
    device, phone, admin = enroll(relay)
    path = '/d/' + device['device_id']
    assert request(relay, 'POST', path + '/r/send', {'text': 'test'})[0] == 401
    assert request(relay, 'GET', path + '/r/desktop/state', headers=phone)[0] == 403
    assert request(relay, 'POST', path + '/r/send', {'text': 'test'}, phone)[0] == 503
    assert request(relay, 'GET', '/connector/' + device['device_id'] + '/poll')[0] == 401
    listing = json.loads(request(relay, 'GET', '/admin/devices', headers=admin)[1])
    assert not listing['devices'][0]['online']
    assert 'token' not in listing['devices'][0]
    import os
    if os.name != 'nt':
        assert relay.path.stat().st_mode & 0o777 == 0o600
    assert request(relay, 'GET', '/admin/qr?id=' + device['device_id'], headers=admin)[0] == 200


def test_phone_text_and_file_roundtrip(relay, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(bridge, 'current_access_key', lambda fallback='': 'local-only-key')
    monkeypatch.setattr(bridge, 'paste_text', lambda text, *args: calls.append(text) or {'chars': len(text), 'enter_pressed': False})
    monkeypatch.setattr(bridge, 'record_text_history', lambda *args, **kwargs: None)
    monkeypatch.setattr(bridge, 'HISTORY_ARCHIVE_DIR', tmp_path / 'received')
    monkeypatch.setattr(bridge, 'paste_uploaded_files', lambda files: {'files': len(files), 'pastes': len(files)})
    monkeypatch.setattr(bridge, 'record_file_history', lambda *args, **kwargs: None)
    origin = bridge.BridgeServer(('127.0.0.1', 0), bridge.BridgeRequestHandler, 'local-only-key')
    threading.Thread(target=origin.serve_forever, daemon=True).start()
    device, phone, _ = enroll(relay)
    client = RelayClient({'url': f'http://127.0.0.1:{relay.server_port}/shengjian', **device}, origin.server_port, lambda: 'local-only-key')
    client.start()
    try:
        deadline = time.monotonic() + 3
        while device['device_id'] not in relay.seen and time.monotonic() < deadline:
            time.sleep(.01)
        path = '/d/' + device['device_id'] + '/r'
        status, body, _ = request(relay, 'POST', path + '/send', {'text': '手机中文 😀', 'key': 'malicious'}, phone)
        assert status == 200 and json.loads(body)['result']['chars'] == 6
        assert calls == ['手机中文 😀']
        content = bytes(range(256)) * 4097
        boundary = 'relay-file-boundary'
        body = b'--' + boundary.encode() + '\r\nContent-Disposition: form-data; name="files"; filename="手机验证.bin"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + content + b'\r\n--' + boundary.encode() + b'--\r\n'
        status, body, _ = request(relay, 'POST', path + '/files/paste', body, {**phone, 'Content-Type': 'multipart/form-data; boundary=' + boundary})
        assert status == 200, body
        received = list((tmp_path / 'received').rglob('*.bin'))
        assert len(received) == 1
        assert hashlib.sha256(received[0].read_bytes()).digest() == hashlib.sha256(content).digest()
        assert not relay.jobs
    finally:
        client.close()
        origin.shutdown()
        origin.server_close()


def test_connector_result_cache_does_not_repeat_paste(relay, monkeypatch):
    count = []
    class Response:
        status = 200
        def read(self, *_): return b'{"ok":true}'
        def getheader(self, *_): return 'application/json'
    class Connection:
        def __init__(self, *args, **kwargs): pass
        def request(self, *args, **kwargs): count.append(1)
        def getresponse(self): return Response()
        def close(self): pass
    device, _, _ = enroll(relay)
    client = RelayClient({'url': f'http://127.0.0.1:{relay.server_port}/shengjian', **device}, 1, lambda: 'secret')
    monkeypatch.setattr('relay_client.http.client.HTTPConnection', Connection)
    job = {'id': 'one-request', 'method': 'POST', 'path': '/send', 'body': base64.b64encode(b'{"text":"test"}').decode()}
    assert client.execute(job) == client.execute(job)
    assert len(count) == 1
    with pytest.raises(ValueError): client.execute({**job, 'id': 'evil', 'path': 'https://evil.example/send'})


def test_revocation_immediately_invalidates_phone_and_connector(relay):
    device, phone, admin = enroll(relay)
    ident = device['device_id']
    assert request(relay, 'POST', '/admin/revoke', {'id': ident}, admin)[0] == 200
    assert request(relay, 'GET', f'/d/{ident}/status', headers=phone)[0] == 401
    assert request(relay, 'GET', f'/connector/{ident}/poll', headers={'Authorization': 'Bearer ' + device['token']})[0] == 401


def test_route_allowlist_and_https_configuration(tmp_path):
    for method, route in [('GET', '/desktop/state'), ('POST', '/desktop/config'), ('POST', '//evil/send'), ('PUT', '/send'), ('GET', '/files/download#x')]:
        assert not valid_route(method, route)
    assert valid_route('GET', '/files/download?file=a.txt')
    with pytest.raises(ValueError):
        RelayClient({'url': 'http://public.example', 'device_id': 'a' * 24, 'token': 'test'}, 1, lambda: '')
    config = {'url': 'https://example.com/shengjian', 'device_id': 'a' * 24, 'token': 'test', 'mobile_token': 'b' * 43}
    (tmp_path / 'relay.json').write_text(json.dumps(config))
    assert phone_url(tmp_path) == 'https://example.com/shengjian/d/' + 'a' * 24 + '/#' + 'b' * 43


def test_timeout_reports_unknown_without_replay(relay):
    device, phone, _ = enroll(relay)
    relay.seen[device['device_id']] = time.monotonic()
    status, body, _ = request(relay, 'POST', '/d/' + device['device_id'] + '/r/send', {'text': 'test'}, phone)
    assert status == 504
    assert '不会自动重发' in json.loads(body)['error']
    assert not relay.jobs
