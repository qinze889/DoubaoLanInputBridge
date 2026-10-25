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
import agent_runtime


def create_service(key, ports=None):
    return bridge.create_verified_bridge_service(key, ports)


def main():
    key = bridge.read_or_create_access_key()
    server = create_service(key)
    server.agent = agent_runtime.manager(bridge.DATA_DIR)
    server.agent.resume()
    bridge.backfill_history_archive()
    manager = mac_tunnel.manager(bridge.DATA_DIR)
    manager.origin_port = server.server_port
    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *args: stopping.set())
    signal.signal(signal.SIGINT, lambda *args: stopping.set())
    print(json.dumps(bridge.bridge_service_info(server)), flush=True)
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
