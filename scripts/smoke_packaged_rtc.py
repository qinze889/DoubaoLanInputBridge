"""Verify frozen WebRTC dependencies with two installed service executables."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from smoke_packaged_peers import Service
spec = importlib.util.spec_from_file_location('packaged_relay', ROOT/'server/relay.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


class MacService(Service):
    def __init__(self, executable, folder):
        self.folder = folder
        self.process = subprocess.Popen([str(executable)], env={**os.environ, 'DOUBAO_BRIDGE_DATA_DIR':str(folder)}, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        lines = queue.Queue()
        threading.Thread(target=lambda: lines.put(self.process.stdout.readline()), daemon=True).start()
        try:
            self.port = json.loads(lines.get(timeout=60))['port']
            self.key = (folder/'access_key.txt').read_text().strip()
            assert self.call('/desktop/state')['version'] == (ROOT/'VERSION').read_text().strip()
        except BaseException:
            self.close(); raise


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--service',type=Path,required=True)
    args = parser.parse_args()
    services = []
    with tempfile.TemporaryDirectory(prefix='shengjian-frozen-rtc-') as scratch:
        relay = module.Relay(('127.0.0.1',0),Path(scratch)/'relay')
        threading.Thread(target=relay.serve_forever,daemon=True).start()
        relayed_routes = []
        original = module.Handler.forward_device
        def audit(handler, ident, route, method, body):
            relayed_routes.append(route.split('?')[0])
            return original(handler, ident, route, method, body)
        module.Handler.forward_device = audit
        try:
            for index in range(2):
                cls = MacService if sys.platform == 'darwin' else Service
                service = cls(args.service.resolve(),Path(scratch)/str(index)); services.append(service)
                config = {'url':f'http://127.0.0.1:{relay.server_port}/shengjian', **relay.enroll(f'Synthetic {index}')}
                service.call('/desktop/connections/config', {'config':config})
                service.call('/desktop/connections', {'mode':'p2p'})
            a,b = services
            deadline = time.monotonic()+30
            while (len(relay.modes)<2 or set(relay.modes.values()) != {'p2p'}) and time.monotonic()<deadline: time.sleep(.1)
            a.call('/desktop/peers/join', {'invitation':b.call('/desktop/peers/invite',{})['invitation']})
            source=Path(scratch)/'P2P-中文.bin'; source.write_bytes(bytes(range(256))*4097)
            expected=hashlib.sha256(source.read_bytes()).digest()
            for sender,receiver in ((a,b),(b,a)):
                ident=receiver.call('/desktop/peers')['device']['id']
                jobid=sender.call('/desktop/peers/send',{'id':ident,'paths':[str(source)]})['job_id']
                deadline=time.monotonic()+60
                while time.monotonic()<deadline:
                    job=next(j for j in sender.call('/desktop/peers')['jobs'] if j['id']==jobid)
                    if job['status'] in ('complete','error'): break
                    time.sleep(.2)
                assert job['status']=='complete', job.get('error','')
                files=list((receiver.folder/'received').glob('*/P2P-中文.bin'))
                assert files and all(hashlib.sha256(f.read_bytes()).digest()==expected for f in files)
            # Pairing/signaling/status may pass here, but file routes must never do so.
            assert not any(route.startswith('/peer/files/') for route in relayed_routes)
            print('Frozen WebRTC: two-way multi-chunk SHA256 transfers passed; signaling only on relay.')
        finally:
            for service in reversed(services): service.close()
            relay.shutdown(); relay.server_close()


if __name__=='__main__':
    main()
