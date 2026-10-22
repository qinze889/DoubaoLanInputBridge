import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import gui_app as bridge
import mac_platform as mac


def test_data_uses_application_support(monkeypatch):
    monkeypatch.delenv('DOUBAO_BRIDGE_DATA_DIR', raising=False)
    assert bridge.app_data_dir() == Path.home() / 'Library/Application Support/DoubaoLanInputBridge'


@pytest.mark.parametrize('host', ['10.0.0.2', '172.16.1.2', '172.31.255.2', '192.168.3.2'])
def test_private_networks(host):
    assert bridge.is_allowed_mobile_lan_host(host)


@pytest.mark.parametrize('host', ['8.8.8.8', '127.0.0.1', '198.18.0.1', '172.32.0.1', '192.168.invalid', '::1'])
def test_reject_public_loopback_and_vpn_addresses(host):
    assert not bridge.is_allowed_mobile_lan_host(host)


def test_network_uses_active_physical_interfaces(monkeypatch):
    result = SimpleNamespace(stdout='''lo0: flags=1
\tinet 127.0.0.1 netmask 0xff000000
en0: flags=1
\tinet 10.0.1.4 netmask 0xffffff00
\tstatus: active
en1: flags=1
\tinet 192.168.1.2 netmask 0xffffff00
\tstatus: inactive
utun9: flags=1
\tinet 10.4.0.2 netmask 0xffffff00
bridge0: flags=1
\tinet 172.20.1.3 netmask 0xffffff00
\tstatus: active
''')
    monkeypatch.setattr(mac.subprocess, 'run', lambda *args, **kwargs: result)
    assert mac.lan_ipv4_addresses() == ['10.0.1.4', '172.20.1.3']


def test_no_fixed_ip_when_offline(monkeypatch):
    monkeypatch.setattr(bridge, 'read_mobile_host_override', lambda: '')
    monkeypatch.setattr(bridge, 'get_lan_ipv4_addresses', lambda: [])
    assert bridge.get_mobile_access_hosts() == ['127.0.0.1']
    assert bridge.preferred_lan_host() == '127.0.0.1'


def test_permission_denial_does_not_modify_clipboard(monkeypatch):
    monkeypatch.setattr(mac, 'accessibility_enabled', lambda: False)
    monkeypatch.setattr(bridge, 'set_clipboard_text', lambda _: pytest.fail('clipboard changed without permission'))
    with pytest.raises(RuntimeError, match='辅助功能'):
        bridge.paste_text('不会发送')


def test_mac_keyboard_posts_command_v_and_return(monkeypatch):
    created, posted, flags = [], [], []
    monkeypatch.setattr(mac, 'require_accessibility', lambda: None)
    def make(source, key, down):
        event = (key, down)
        created.append(event)
        return event
    monkeypatch.setattr(mac, 'CGEventCreateKeyboardEvent', make)
    monkeypatch.setattr(mac, 'CGEventSetFlags', lambda event, value: flags.append((event, value)))
    monkeypatch.setattr(mac, 'CGEventPost', lambda tap, event: posted.append(event))
    mac.send_command_v()
    mac.send_enter()
    assert created == [(9, True), (9, False), (36, True), (36, False)]
    assert posted == created
    assert [value for _, value in flags] == [mac.kCGEventFlagMaskCommand] * 2 + [0, 0]


def test_paste_transactions_do_not_interleave(monkeypatch):
    operations = []
    monkeypatch.setattr(mac, 'require_accessibility', lambda: None)
    def copy(value):
        operations.append(('copy', value))
        time.sleep(0.03)
    monkeypatch.setattr(bridge, 'set_clipboard_text', copy)
    monkeypatch.setattr(bridge, 'send_ctrl_v', lambda: operations.append(('paste', None)))
    threads = [threading.Thread(target=bridge.paste_text, args=(str(index),)) for index in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)
        assert not thread.is_alive()
    assert [op for op, value in operations] == ['copy', 'paste'] * 3


def test_unicode_clipboard_routes_to_mac(monkeypatch):
    values = []
    monkeypatch.setattr(mac, 'set_clipboard_text', values.append)
    bridge.set_clipboard_text('豆包\nMac 😀')
    assert values == ['豆包\nMac 😀']


def test_file_clipboard_passes_file_urls_and_adds_bitmap(monkeypatch, tmp_path):
    from PIL import Image
    image = tmp_path / '图片 空格.png'
    Image.new('RGB', (2, 2), 'red').save(image)
    class Board:
        def __init__(self):
            self.urls = []
            self.formats = []
        def clearContents(self):
            pass
        def writeObjects_(self, urls):
            self.urls = urls
            return True
        def setData_forType_(self, data, kind):
            self.formats.append(kind)
            return True
    board = Board()
    monkeypatch.setattr(mac, 'NSPasteboard', SimpleNamespace(generalPasteboard=lambda: board))
    bridge.set_clipboard_files([image])
    assert len(board.urls) == 1
    assert str(board.urls[0].path()) == str(image)
    assert board.urls[0].isFileURL()
    assert mac.NSPasteboardTypeTIFF in board.formats


def test_no_windows_updates_on_mac(monkeypatch):
    monkeypatch.setenv('DOUBAO_BRIDGE_UPDATE_URL', 'https://example.com/windows.exe')
    assert bridge.read_update_manifest_url() == ''
    assert not bridge.check_for_update()['configured']


def test_open_file_uses_argument_array(monkeypatch, tmp_path):
    calls = []
    path = tmp_path / 'file $(never run).txt'
    monkeypatch.setattr(mac.subprocess, 'run', lambda args, **kw: calls.append(args))
    bridge.open_local_path(path)
    assert calls == [['/usr/bin/open', str(path)]]


def test_qt_window_permissions_and_service(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QApplication
    import qt_app
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(mac, 'accessibility_enabled', lambda: False)
    monkeypatch.setattr(bridge, 'get_mobile_access_hosts', lambda: ['10.0.1.4'])
    window = qt_app.BridgeQtWindow()
    window.start_server()
    try:
        assert window.server is not None
        assert window.service_state == 'running'
        assert not window.permission_bar.isHidden()
        monkeypatch.setattr(mac, 'accessibility_enabled', lambda: True)
        window.refresh_permissions()
        assert window.permission_bar.isHidden()
        qr = qt_app.QrDialog(window)
        assert qr.qr.pixmap() is not None
        manage = qt_app.ManageDialog(window)
        assert '网络权限' in ' '.join(label.text() for label in manage.findChildren(qt_app.QLabel))
    finally:
        window.stop_server()
        window.log_timer.stop()
        window.preview_timer.stop()
        window.permission_timer.stop()
        if window.tray:
            window.tray.hide()
        window.deleteLater()
        app.processEvents()


def test_native_app_owns_permission_and_keyboard_events(monkeypatch):
    calls = []
    monkeypatch.setenv('SHENGJIAN_NATIVE_INPUT_SOCKET', '/tmp/native-test.sock')
    def native(request):
        calls.append(request['operation'])
        return {'ok': True, 'allowed': True}
    monkeypatch.setattr(mac, 'native_input', native)
    monkeypatch.setattr(mac, 'AXIsProcessTrusted', lambda: pytest.fail('helper permission must not decide app authorization'))
    monkeypatch.setattr(mac, 'CGEventPost', lambda *args: pytest.fail('helper must not post events'))
    assert mac.accessibility_enabled()
    mac.send_command_v()
    mac.send_enter()
    assert calls == ['permission', 'permission', 'paste', 'permission', 'enter']


def test_native_input_failure_never_falls_back_to_helper(monkeypatch):
    monkeypatch.setenv('SHENGJIAN_NATIVE_INPUT_SOCKET', '/tmp/nonexistent-shengjian-test.sock')
    monkeypatch.setenv('SHENGJIAN_NATIVE_INPUT_TOKEN', 'test-token')
    monkeypatch.setattr(mac, 'AXIsProcessTrusted', lambda: pytest.fail('unsafe helper fallback'))
    assert not mac.accessibility_enabled()
    with pytest.raises(RuntimeError, match='原生输入服务'):
        mac.native_input({'operation': 'paste'})


def test_native_socket_authentication_and_explicit_rejection(monkeypatch):
    import json
    import socket
    import tempfile
    import uuid
    path = str(Path(tempfile.gettempdir()) / ('sj-' + uuid.uuid4().hex[:8] + '.sock'))
    # macOS Unix socket paths are limited to 104 bytes; use the short /tmp alias.
    if len(path.encode()) >= 100:
        path = '/tmp/sj-' + uuid.uuid4().hex + '.sock'
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(path)
    listener.listen(1)
    received = []
    def serve():
        client, _ = listener.accept()
        with client:
            received.append(json.loads(client.makefile('rb').readline()))
            client.sendall(b'{"ok":false,"error":"not authorized"}\n')
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    monkeypatch.setenv('SHENGJIAN_NATIVE_INPUT_SOCKET', path)
    monkeypatch.setenv('SHENGJIAN_NATIVE_INPUT_TOKEN', 'private-test-token')
    try:
        with pytest.raises(RuntimeError, match='not authorized'):
            mac.native_input({'operation': 'paste'})
        thread.join(timeout=2)
        assert received == [{'operation': 'paste', 'token': 'private-test-token'}]
    finally:
        listener.close()
        Path(path).unlink(missing_ok=True)
