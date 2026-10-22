"""P2P through real relay signaling; all application bytes bypass its queues."""
import base64
import hashlib
import http.server
import json
import threading
import time
import uuid
from types import SimpleNamespace
import pytest
from test_relay import relay, request, enroll
from relay_client import RelayClient
from rtc_bridge import RTCBridge


def test_phone_direct_content_and_scoped_machine_channel(relay):
    received = []
    class Origin(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            body = self.rfile.read(int(self.headers['Content-Length']))
            received.append((self.path, body))
            assert 'key=private-origin-key' in self.path
            response = json.dumps({'ok': True, 'sha256': hashlib.sha256(body).hexdigest()}).encode()
            self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(response))); self.end_headers(); self.wfile.write(response)
    origin = http.server.ThreadingHTTPServer(('127.0.0.1',0), Origin)
    threading.Thread(target=origin.serve_forever, daemon=True).start()
    device, phone, _ = enroll(relay)
    client = RelayClient({'url': f'http://127.0.0.1:{relay.server_port}/shengjian', 'connection_mode':'p2p', **device}, origin.server_port, lambda:'private-origin-key')
    client.rtc.stun = None
    client.start()
    outgoing = RTCBridge(stun=None)
    try:
        deadline = time.monotonic()+3
        while device['device_id'] not in relay.seen and time.monotonic()<deadline: time.sleep(.01)
        base = '/d/'+device['device_id']
        assert json.loads(request(relay,'GET',base+'/status',headers=phone)[1])['connection_mode'] == 'p2p'
        assert request(relay,'GET',base+'/p2p.js')[0] == 200
        assert request(relay,'POST',base+'/r/send',{'text':'blocked'},phone)[0] == 409
        assert request(relay,'POST','/p2p/'+device['device_id']+'/peer/files/start',{})[0] == 409
        def signal(offer):
            status, body, _ = request(relay,'POST',base+'/p2p/offer',offer,phone)
            assert status == 200
            return json.loads(body)['answer']
        content = json.dumps({'text':'中文 😀'*100000}).encode()
        result = outgoing.request('phone', signal, {'id':uuid.uuid4().hex,'method':'POST','path':'/send','body':base64.b64encode(content).decode(),'content_type':'application/json'})
        assert result['status'] == 200 and len(received) == 1
        assert json.loads(received[0][1])['text'] == '中文 😀'*100000
        assert relay.total['delivered'] == 1  # SDP only; no send/file job was relayed.
        def peer_signal(offer):
            raw = json.dumps(offer).encode()
            client.peer_manager = SimpleNamespace(authenticate=lambda *a: ('paired',hashlib.sha256(raw).hexdigest()))
            result = client.execute({'id':uuid.uuid4().hex,'method':'POST','path':'/peer/p2p/offer','body':base64.b64encode(raw).decode()})
            return json.loads(base64.b64decode(result['body']))['answer']
        denied = outgoing.request('paired-machine', peer_signal, {'id':uuid.uuid4().hex,'method':'POST','path':'/send','body':base64.b64encode(b'{"text":"forbidden"}').decode(),'content_type':'application/json'})
        assert denied['status'] == 400 and len(received) == 1
    finally:
        outgoing.close(); client.close(); origin.shutdown(); origin.server_close()
