"""Real isolated sockets: dynamic allocation, competing listeners and identity."""
import errno
import http.client
import json
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import gui_app as bridge
import mac_service


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(bridge, 'KEY_FILE', tmp_path/'access_key.txt')
    bridge.write_access_key('local-test-key')
    return 'local-test-key'


def close(server):
    server.shutdown()
    server.server_close()


def test_dynamic_allocation_does_not_probe_a_fixed_range(isolated, monkeypatch):
    monkeypatch.setattr(bridge, 'is_tcp_port_in_use', lambda port: pytest.fail('default startup must bind port zero atomically'))
    server = mac_service.create_service(isolated)
    try:
        assert server.server_port > 0
        info = bridge.bridge_service_info(server)
        assert info['port'] == server.server_port and info['pid'] == os.getpid()
        assert info['instance_id'] == server.instance_id
    finally:
        close(server)


def test_explicit_port_in_use_falls_back_without_reusing_other_service(isolated):
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0)); listener.listen(4)
    occupied = listener.getsockname()[1]
    try:
        server = mac_service.create_service(isolated, [occupied])
        try:
            assert server.server_port != occupied
            assert listener.fileno() >= 0
        finally:
            close(server)
    finally:
        listener.close()


def test_bind_race_is_retried_with_kernel_allocated_port(isolated, monkeypatch):
    original = bridge.BridgeServer
    attempted = []
    def racing(address, *args):
        attempted.append(address[1])
        if address[1] == 45678:
            raise OSError(errno.EADDRINUSE, 'simulated bind race after a free-port check')
        return original(address, *args)
    monkeypatch.setattr(bridge, 'is_tcp_port_in_use', lambda port: False)
    monkeypatch.setattr(bridge, 'BridgeServer', racing)
    server = mac_service.create_service(isolated, [45678])
    try:
        assert attempted == [45678, 0]
    finally:
        close(server)


def test_later_loopback_listener_cannot_shadow_wildcard_server(isolated):
    server = mac_service.create_service(isolated)
    competing = socket.socket()
    competing.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        with pytest.raises(OSError):
            competing.bind(('127.0.0.1', server.server_port))
        assert bridge.wait_for_bridge_server_identity(server.server_port, os.getpid(), hosts=['127.0.0.1'],
            expected_instance=server.instance_id, access_key=isolated)[0]
    finally:
        competing.close(); close(server)


def test_same_pid_version_other_instance_and_wrong_key_are_rejected(isolated):
    first = mac_service.create_service(isolated)
    second = mac_service.create_service(isolated)
    try:
        for instance, key in [(first.instance_id, isolated), (second.instance_id, 'wrong-key')]:
            assert not bridge.wait_for_bridge_server_identity(second.server_port, os.getpid(), hosts=['127.0.0.1'],
                expected_instance=instance, access_key=key, timeout=.12)[0]
        assert bridge.wait_for_bridge_server_identity(second.server_port, os.getpid(), hosts=['127.0.0.1'],
            expected_instance=second.instance_id, access_key=isolated)[0]
    finally:
        close(first); close(second)


def test_wrong_instance_rejected_before_action_and_old_clients_still_work(isolated, monkeypatch):
    server = mac_service.create_service(isolated)
    monkeypatch.setattr(bridge, 'set_clipboard_text', lambda text: pytest.fail('must never perform stale-instance action'))
    connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
    try:
        connection.request('POST', '/desktop/copy', json.dumps({'key': isolated, 'text': 'test'}),
            {'Content-Type': 'application/json', 'X-Shengjian-Instance': '0'*32})
        response = connection.getresponse(); response.read(); assert response.status == 409
        connection.request('GET', '/health')
        response = connection.getresponse(); health = json.loads(response.read())
        assert health['ok'] and health['pid'] == os.getpid() and 'proof' not in health
        assert response.getheader('X-Shengjian-Instance') == server.instance_id
        connection.request('GET', '/desktop/state?key='+isolated)
        response = connection.getresponse(); assert response.status == 200; response.read()
    finally:
        connection.close(); close(server)


def test_foreign_html_listener_not_mistaken_for_bridge(isolated):
    class Foreign(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b'<title>Other app</title>')
        def log_message(self, *args): pass
    foreign = HTTPServer(('127.0.0.1', 0), Foreign)
    threading.Thread(target=foreign.serve_forever, daemon=True).start()
    try:
        assert not bridge.wait_for_bridge_server_identity(foreign.server_port, os.getpid(), hosts=['127.0.0.1'],
            expected_instance='0'*32, access_key=isolated, timeout=.12)[0]
    finally:
        close(foreign)
