"""Headless service owned by the native SwiftUI app."""
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gui_app as bridge
import mac_tunnel


def create_service(key, ports=None):
    for port in ports if ports is not None else range(bridge.DEFAULT_PORT, bridge.DEFAULT_PORT + bridge.PORT_AUTO_INCREMENT_LIMIT):
        if bridge.is_tcp_port_in_use(port):
            continue
        try:
            candidate = bridge.BridgeServer(('0.0.0.0', port), bridge.BridgeRequestHandler, key)
        except OSError:
            continue
        threading.Thread(target=candidate.serve_forever, daemon=True).start()
        valid, _ = bridge.wait_for_bridge_server_identity(candidate.server_port, os.getpid(), hosts=['127.0.0.1'])
        if valid:
            return candidate
        candidate.shutdown()
        candidate.server_close()
    raise RuntimeError('没有可用端口')


def main():
    key = bridge.read_or_create_access_key()
    server = create_service(key)
    bridge.backfill_history_archive()
    manager = mac_tunnel.manager(bridge.DATA_DIR)
    manager.origin_port = server.server_port
    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *args: stopping.set())
    signal.signal(signal.SIGINT, lambda *args: stopping.set())
    print(json.dumps({'port': server.server_port, 'pid': os.getpid()}), flush=True)
    parent = os.getppid()
    try:
        while not stopping.wait(1):
            if os.getppid() != parent:
                break
    finally:
        manager.stop()
        server.shutdown()
        server.server_close()

if __name__ == '__main__':
    main()
