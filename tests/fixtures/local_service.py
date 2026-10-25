"""Temporary local-only identity fixture, never uses the installed app's data."""
import os
import sys
import json
import signal
import threading
from pathlib import Path
os.environ['DOUBAO_BRIDGE_DATA_DIR'] = sys.argv[1]
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'src'))
import gui_app as bridge
key = 'fixture-local-service-key'
bridge.write_access_key(key)
server = bridge.create_verified_bridge_service(key)
stop = threading.Event()
signal.signal(signal.SIGTERM, lambda *args: stop.set())
print(json.dumps(bridge.bridge_service_info(server)), flush=True)
try: stop.wait()
finally:
    server.shutdown(); server.server_close()
