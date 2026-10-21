import importlib.util
import hashlib
import json
import time
from pathlib import Path

import pytest
import gui_app as bridge
import peer_share


def test_public_transport_uses_system_proxy_but_lan_stays_direct(monkeypatch):
    import io
    configured = []
    class Proxy:
        def __init__(self, *args): configured.append(args)
    class Response(io.BytesIO):
        status = 200
    class Opener:
        def open(self, request, timeout):
            assert timeout == 90
            assert request.get_method() == 'POST'
            return Response(b'{"ok":true}')
    monkeypatch.setattr(peer_share, 'ProxyHandler', Proxy)
    monkeypatch.setattr(peer_share, 'build_opener', lambda *handlers: Opener())
    peer_share.transport('https://example.trycloudflare.com', '/peer/ping', b'{}', {})
    peer_share.transport('http://10.1.2.3:8765', '/peer/ping', b'{}', {})
    assert configured == [(), ({},)]
    with pytest.raises(ValueError, match='跳转'):
        peer_share.NoPeerRedirect().redirect_request(None, None, 302, '', {}, 'https://other.invalid')


@pytest.mark.parametrize('name,expected', [
    ('CON.txt', '_CON.txt'), ('aux', '_aux'), ('LPT1.pdf', '_LPT1.pdf'),
    ('report:Q4?.pdf', 'report_Q4_.pdf'), ('../../图片 😀.png', '图片 😀.png'),
    ('trailing. ', 'trailing'),
])
def test_cross_platform_file_names(name, expected):
    assert peer_share.safe_filename(name) == expected


def test_long_unicode_file_name_keeps_extension():
    name = peer_share.safe_filename('😀' * 100 + '.pdf')
    assert name.endswith('.pdf') and len(name.encode('utf-8')) <= 120


def test_windows_lan_accepts_private_network_without_fixed_fallback(monkeypatch):
    monkeypatch.setattr(bridge, 'IS_MACOS', False)
    monkeypatch.setattr(bridge, 'get_lan_ipv4_addresses', lambda: [])
    monkeypatch.setattr(bridge, 'read_mobile_host_override', lambda: '')
    monkeypatch.setattr(bridge.socket, 'getaddrinfo', lambda *args: [(None, None, None, None, ('198.18.1.1', 0)), (None, None, None, None, ('10.2.3.4', 0))])
    assert bridge.machine_lan_host() == '10.2.3.4'
    monkeypatch.setattr(bridge.socket, 'getaddrinfo', lambda *args: [])
    assert bridge.machine_lan_host() == '127.0.0.1'


def test_windows_invitation_uses_own_public_tunnel(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, 'IS_MACOS', False)
    monkeypatch.setattr(bridge, 'DATA_DIR', tmp_path)
    server = bridge.BridgeServer(('127.0.0.1', 0), bridge.BridgeRequestHandler, 'test-only')
    try:
        monkeypatch.setattr(server.quick_tunnel, 'status', lambda: {'ready': True, 'public_url': 'https://win-example.trycloudflare.com'})
        assert server.peer_manager.endpoint_provider() == 'https://win-example.trycloudflare.com'
        assert bridge.build_access_url('192.168.1.5', server.server_port, 'synthetic') == 'https://win-example.trycloudflare.com/?key=synthetic'
    finally:
        server.server_close()


def test_mac_120_protocol_remains_compatible(tmp_path, monkeypatch):
    """Use the actual released module, rather than a copy of the new sender."""
    root = Path(__file__).resolve().parents[1]
    source = (root / 'tests/fixtures/peer_share_120.py').read_bytes()
    assert hashlib.sha256(source).hexdigest() == 'e4c5d27becb4e5d174138e94b59d826ff5c4075f55c3780c1d3a32872cd36ef0'
    old_file = tmp_path / 'peer_share_120.py'; old_file.write_bytes(source)
    spec = importlib.util.spec_from_file_location('peer_share_120', old_file)
    old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
    a = peer_share.PeerManager(tmp_path / 'new-windows', lambda: 'https://windows.example')
    b = old.PeerManager(tmp_path / 'old-mac', lambda: 'https://mac.example')
    targets = {a.endpoint_provider(): a, b.endpoint_provider(): b}
    def transport(base, path, body, headers):
        receiver = targets[base]
        if path == '/peer/pair':
            return {'ok': True, **receiver.accept_pair(json.loads(body))}
        ident, digest = receiver.authenticate('POST', path, headers)
        assert hashlib.sha256(body).hexdigest() == digest
        return {'ok': True, **receiver.receive(ident, path, body)}
    monkeypatch.setattr(peer_share, 'transport', transport)
    monkeypatch.setattr(old, 'transport', transport)
    monkeypatch.setattr(peer_share, 'CHUNK_BYTES', 1024)
    monkeypatch.setattr(old, 'CHUNK_BYTES', 1024)
    a.join(b.invite()['invitation'])
    source_file = tmp_path / '中文-file.txt'
    data = b'cross-platform\x00' * 300
    source_file.write_bytes(data)
    for sender, receiver in ((a, b), (b, a)):
        ident = sender.send(receiver.device['id'], [source_file])['job_id']
        for _ in range(100):
            job = next(row for row in sender.snapshot()['jobs'] if row['id'] == ident)
            if job['status'] in ('complete', 'error'): break
            time.sleep(.05)
        assert job['status'] == 'complete'
        targets_on_disk = list((receiver.root / 'received').glob('*/中文-file.txt'))
        assert targets_on_disk and targets_on_disk[-1].read_bytes() == data


def test_public_pairing_requires_reachable_return_address(tmp_path):
    sender = peer_share.PeerManager(tmp_path / 'sender', lambda: 'http://10.0.0.2:8765')
    other = peer_share.PeerManager(tmp_path / 'other', lambda: 'https://other.trycloudflare.com')
    with pytest.raises(ValueError, match='开启本机公网连接'):
        sender.join(other.invite()['invitation'])


def test_qt_machine_dialog_lists_devices_and_jobs(tmp_path):
    # Cocoa/Qt owns a process-wide application and cannot share its lifetime
    # with the service/network regression tests running in this process.
    import os
    import subprocess
    import sys
    code = """
from PySide6.QtWidgets import QApplication, QWidget
from qt_peers import MachineShareDialog
import gui_app as bridge
app = QApplication([])
server = bridge.BridgeServer(('127.0.0.1', 0), bridge.BridgeRequestHandler, 'test-only')
try:
    parent = QWidget(); parent.server = server
    dialog = MachineShareDialog(parent)
    assert dialog.windowTitle() == '机器共享 · Mac 与 Windows'
    assert dialog.public.text() == '开启公网连接'
    assert not dialog.send.isEnabled()
    dialog.close(); dialog.deleteLater(); app.processEvents()
finally:
    server.server_close()
"""
    subprocess.run([sys.executable, '-c', code], check=True, timeout=30,
                   env={**os.environ, 'DOUBAO_BRIDGE_DATA_DIR': str(tmp_path),
                        'PYTHONPATH': str(Path(bridge.__file__).parent),
                        'QT_QPA_PLATFORM': 'offscreen'})
