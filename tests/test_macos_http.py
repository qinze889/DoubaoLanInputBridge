import http.client
import json
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import gui_app as bridge


@contextmanager
def server(monkeypatch):
    monkeypatch.setattr(bridge, 'current_access_key', lambda fallback='': 'mac-test-key')
    service = bridge.BridgeServer(('127.0.0.1', 0), bridge.BridgeRequestHandler, 'mac-test-key')
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    try:
        yield service
    finally:
        service.shutdown()
        service.server_close()
        thread.join(timeout=2)


def request(service, method, path, data=None, headers=None):
    conn = http.client.HTTPConnection('127.0.0.1', service.server_port, timeout=4)
    payload = json.dumps(data).encode() if data is not None else None
    conn.request(method, path, payload, headers or {'Content-Type': 'application/json'})
    response = conn.getresponse()
    body = response.read()
    status = response.status
    conn.close()
    return status, body


def test_phone_send_and_history(monkeypatch):
    calls = []
    monkeypatch.setattr(bridge.mac_platform, 'require_accessibility', lambda: None)
    monkeypatch.setattr(bridge, 'set_clipboard_text', calls.append)
    monkeypatch.setattr(bridge, 'send_ctrl_v', lambda: calls.append('command-v'))
    monkeypatch.setattr(bridge, 'send_enter', lambda: calls.append('return'))
    monkeypatch.setattr(bridge, 'record_text_history', lambda text, action: calls.append(('history', text)))
    with server(monkeypatch) as service:
        status, body = request(service, 'POST', '/send', {'key': 'wrong', 'text': '不能发送'})
        assert status == 401
        assert calls == []
        status, body = request(service, 'POST', '/send', {'key': 'mac-test-key', 'text': 'Mac 中文😀', 'press_enter': True, 'enter_delay_sec': 0})
        assert status == 200
        assert json.loads(body)['result']['enter_pressed']
        assert calls == ['Mac 中文😀', 'command-v', 'return', ('history', 'Mac 中文😀')]
        assert service.state['paste_count'] == 1


def test_phone_page_pairs_and_logs_redact_key(monkeypatch, tmp_path):
    logs = []
    monkeypatch.setattr(bridge, 'append_service_log', lambda line: logs.append(line))
    with server(monkeypatch) as service:
        status, body = request(service, 'GET', '/?key=mac-test-key')
        assert status == 200
        assert '发送'.encode() in body
        status, body = request(service, 'GET', '/?key=expired')
        assert status == 401
        assert '二维码已失效'.encode() in body
    assert 'mac-test-key' not in '\n'.join(logs)
    assert 'expired' not in '\n'.join(logs)


def test_desktop_publish_then_phone_download(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, 'MOBILE_SHARE_FEED_FILE', tmp_path/'feed.json')
    source = tmp_path/'文档.txt'
    source.write_text('文件内容', encoding='utf-8')
    # Exercise existing share functions with explicit isolated storage.
    files = bridge.publish_files_for_mobile_download([source], share_dir=tmp_path/'share')
    assert files['files'] == 1
    target = bridge.resolve_shared_download(source.name, share_dir=tmp_path/'share')
    assert target.read_text(encoding='utf-8') == '文件内容'


def test_upload_is_authorized_before_any_disk_write(monkeypatch):
    monkeypatch.setattr(bridge, 'parse_multipart_upload_stream', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('parsed an unauthorized upload')))
    with server(monkeypatch) as service:
        status, body = request(service, 'POST', '/files/clipboard?key=invalid', {'key': 'mac-test-key'})
        assert status == 401


def test_phone_upload_and_download_over_http(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, 'HISTORY_ARCHIVE_DIR', tmp_path / 'history')
    monkeypatch.setattr(bridge, 'MOBILE_SHARE_DIR', tmp_path / 'share')
    monkeypatch.setattr(bridge, 'MOBILE_SHARE_FEED_FILE', tmp_path / 'feed.json')
    monkeypatch.setattr(bridge, 'record_file_history', lambda *args, **kw: {'id': 'test-file', 'ts': 1})
    original_publish_files = bridge.publish_files_for_mobile_download
    original_publish_text = bridge.publish_text_for_mobile_download
    monkeypatch.setattr(bridge, 'publish_files_for_mobile_download', lambda paths: original_publish_files(paths, share_dir=tmp_path / 'share'))
    monkeypatch.setattr(bridge, 'publish_text_for_mobile_download', lambda text: original_publish_text(text, share_dir=tmp_path / 'share'))
    clipboard = []
    monkeypatch.setattr(bridge, 'set_clipboard_files', lambda paths: clipboard.extend(paths))
    boundary = 'mac-test-boundary'
    payload = (f'--{boundary}\r\nContent-Disposition: form-data; name="key"\r\n\r\nmac-test-key\r\n'
               f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="note.txt"\r\n'
               f'Content-Type: text/plain\r\n\r\nhello from phone\r\n--{boundary}--\r\n').encode()
    with server(monkeypatch) as service:
        conn = http.client.HTTPConnection('127.0.0.1', service.server_port, timeout=3)
        conn.request('POST', '/files/clipboard?key=mac-test-key', payload,
                     {'Content-Type': f'multipart/form-data; boundary={boundary}'})
        response = conn.getresponse()
        assert response.status == 200
        assert json.loads(response.read())['result']['files'] == 1
        conn.close()
        assert clipboard[0].read_text() == 'hello from phone'
        # Mac -> phone: publish through desktop API, then fetch the phone feed.
        status, body = request(service, 'POST', '/desktop/publish', {'key': 'mac-test-key', 'paths': [str(clipboard[0])], 'text': '来自 Mac'})
        assert status == 200
        status, body = request(service, 'GET', '/files/shared?key=mac-test-key')
        assert status == 200
        assert len(json.loads(body)['items']) == 2
        status, body = request(service, 'GET', '/files/download?key=mac-test-key&file=note.txt')
        assert status == 200
        assert body == b'hello from phone'
