import http.client
import io
import json
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
import mac_tunnel
import gui_app as bridge


def fetch(port,path,method='GET',payload=None,headers=None):
    conn=http.client.HTTPConnection('127.0.0.1',port,timeout=3)
    conn.request(method,path,payload,headers or {})
    response=conn.getresponse()
    status,body=response.status,response.read()
    conn.close()
    return status,body


@pytest.fixture
def public_service(monkeypatch,tmp_path):
    monkeypatch.setattr(bridge,'current_access_key',lambda fallback='':'gateway-test-key')
    monkeypatch.setattr(bridge,'record_text_history',lambda *args,**kw:None)
    server=bridge.BridgeServer(('127.0.0.1',0),bridge.BridgeRequestHandler,'gateway-test-key')
    gateway=mac_tunnel.PublicGateway(server.server_port)
    threads=[threading.Thread(target=service.serve_forever,daemon=True) for service in [server,gateway]]
    for thread in threads:thread.start()
    try:yield server,gateway
    finally:
        for service in [gateway,server]:service.shutdown();service.server_close()
        for thread in threads:thread.join(timeout=2)


@pytest.mark.parametrize('path',['/desktop/state?key=gateway-test-key','/desktop/history?key=gateway-test-key','/desktop/config?key=gateway-test-key','/__updates__/update.json'])
def test_public_gateway_never_exposes_desktop_endpoints(public_service,path):
    server,gateway=public_service
    assert fetch(gateway.server_port,path)[0]==403


def test_public_phone_page_still_requires_pairing_key(public_service):
    _,gateway=public_service
    assert fetch(gateway.server_port,'/')[0]==401
    status,page=fetch(gateway.server_port,'/?key=gateway-test-key')
    assert status==200
    assert (b'ios-appearance' in page) if bridge.IS_MACOS else (b'<!doctype html>' in page.lower())


def test_public_health_does_not_leak_local_paths_or_pid(public_service):
    _,gateway=public_service
    status,body=fetch(gateway.server_port,'/health')
    assert status==200
    assert json.loads(body)=={'ok':True,'name':'Shengjian','probe_id':gateway.probe_id}


def test_cloudflare_headers_never_count_as_desktop_client(public_service):
    server,_=public_service
    for headers in [{'CF-Connecting-IP':'8.8.8.8'},{'X-Bridge-Public':'1'},{'CF-Ray':'test'}]:
        assert fetch(server.server_port,'/desktop/state?key=gateway-test-key',headers=headers)[0]==403


def test_public_send_passes_unicode_and_payload(public_service,monkeypatch):
    _,gateway=public_service
    pasted=[]
    monkeypatch.setattr(bridge,'paste_text',lambda text,*args:(pasted.append(text) or {'chars':len(text),'enter_pressed':False}))
    payload=json.dumps({'key':'gateway-test-key','text':'公网手机发送 😀'}).encode()
    status,body=fetch(gateway.server_port,'/send','POST',payload,{'Content-Type':'application/json'})
    assert status==200
    assert pasted==['公网手机发送 😀']
    assert json.loads(body)['ok']


def test_quick_tunnel_diagnostics_read_current_manager_on_desktop_only(public_service):
    server, gateway = public_service
    server.connections.config = {'mode': 'cloudflare', 'enabled': True}
    tunnel = server.quick_tunnel
    tunnel.phase, tunnel.stage = 'error', 'connecting'
    tunnel.error = 'TCP 7844 connection timed out'
    tunnel.logs.append('ERR failed to reach the current quick tunnel')
    status, body = fetch(server.server_port, '/desktop/tunnel?key=gateway-test-key')
    result = json.loads(body)
    assert status == 200
    assert result['status']['stage'] == 'connecting'
    assert result['log_path'] == str(tunnel.log_file)
    assert 'current quick tunnel' in result['log_tail']
    _, body = fetch(server.server_port, '/desktop/connections?key=gateway-test-key')
    assert json.loads(body)['cloudflare']['error'] == tunnel.error
    assert fetch(gateway.server_port, '/desktop/tunnel?key=gateway-test-key')[0] == 403


@pytest.mark.parametrize('endpoint', ['/files/share', '/files/clipboard', '/files/paste'])
@pytest.mark.parametrize('query', ['', '?key=wrong-key'])
def test_public_upload_rejects_key_before_parser_can_write_files(public_service, monkeypatch, endpoint, query):
    _, gateway = public_service
    def forbidden_parser(*args, **kwargs):
        pytest.fail('unauthenticated public upload reached the file-writing parser')
    monkeypatch.setattr(bridge, 'IS_MACOS', False)
    monkeypatch.setattr(bridge, 'parse_multipart_upload_stream', forbidden_parser)
    status, body = fetch(gateway.server_port, endpoint + query, 'POST', b'--test--\r\n',
                         {'Content-Type': 'multipart/form-data; boundary=test'})
    assert status == 401
    assert json.loads(body)['ok'] is False


@pytest.mark.parametrize('keys', [['wrong-key'], ['gateway-test-key', 'wrong-key']])
def test_public_upload_rejects_invalid_body_key_without_business_files(public_service, monkeypatch, tmp_path, keys):
    _, gateway = public_service
    directory = tmp_path / 'shared'
    monkeypatch.setattr(bridge, 'MOBILE_SHARE_DIR', directory)
    boundary = 'public-upload-test'
    fields = ''.join(f'--{boundary}\r\nContent-Disposition: form-data; name="key"\r\n\r\n{key}\r\n' for key in keys)
    payload = (fields + f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="rejected.txt"\r\n'
               f'Content-Type: text/plain\r\n\r\nshould-not-be-written\r\n--{boundary}--\r\n').encode()
    status, body = fetch(gateway.server_port, '/files/share?key=gateway-test-key', 'POST', payload,
                         {'Content-Type': 'multipart/form-data; boundary=' + boundary})
    assert status == 401
    assert json.loads(body)['ok'] is False
    assert not list(directory.rglob('*'))


def test_parser_ignores_other_urls():
    assert mac_tunnel.quick_url('Visit https://hello-world-123.trycloudflare.com now')=='https://hello-world-123.trycloudflare.com'
    assert not mac_tunnel.quick_url('https://trycloudflare.com.evil.example')
    assert not mac_tunnel.quick_url('https://example.com')


def test_edge_registration_alone_never_proves_public_readiness(tmp_path):
    manager=mac_tunnel.TunnelManager(tmp_path)
    manager.phase='starting';manager.generation=1
    observations=[]
    class Output:
        def __iter__(self):
            yield 'https://example-preview.trycloudflare.com\n'
            observations.append(manager.status()['ready'])
            yield 'Registered tunnel connection connIndex=0\n'
            observations.append(manager.status()['ready'])
        def close(self):pass
    class Process:
        pid=123
        stdout=Output()
        def poll(self):return None
        def terminate(self):pass
        def wait(self,timeout):pass
    process=Process();manager.process=process
    manager._monitor(process,1)
    assert observations==[False,False]
    assert manager.status()['phase']=='error'
    assert manager.status()['public_url']==''


def test_stop_only_terminates_owned_child(tmp_path):
    manager=mac_tunnel.TunnelManager(tmp_path)
    calls=[]
    class Process:
        pid=123
        def poll(self):return None
        def terminate(self):calls.append('terminate')
        def wait(self,timeout):calls.append('wait')
    manager.process=Process();manager.phase='ready';manager.url='https://example-preview.trycloudflare.com'
    assert manager.stop()['stopped']
    assert calls==['terminate','wait']
    assert manager.status()['public_url']==''
    assert manager.status()['phase']=='off'


def test_default_qr_uses_current_cloudflare_address(monkeypatch,tmp_path):
    manager=mac_tunnel.TunnelManager(tmp_path)
    manager.phase='ready';manager.url='https://example-preview.trycloudflare.com'
    monkeypatch.setattr(mac_tunnel,'manager',lambda _:manager)
    assert bridge.build_access_url('10.0.0.2',8767,'synthetic-key')=='https://example-preview.trycloudflare.com/?key=synthetic-key'
    manager.phase='off'
    monkeypatch.setattr(bridge,'read_public_url_override',lambda:'')
    assert bridge.build_access_url('10.0.0.2',8767,'synthetic-key').startswith('http://10.0.0.2:8767/')


def test_native_service_skips_specific_loopback_port_conflict():
    import mac_service
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    class ExistingService(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            self.send_response(200);self.end_headers();self.wfile.write(b'other app')
    occupied=ThreadingHTTPServer(('127.0.0.1',0),ExistingService)
    threading.Thread(target=occupied.serve_forever,daemon=True).start()
    service=None
    try:
        service=mac_service.create_service('synthetic-key',ports=[occupied.server_port,0])
        assert service.server_port != occupied.server_port
        assert fetch(occupied.server_port,'/health')[1]==b'other app'
        assert json.loads(fetch(service.server_port,'/health')[1])['name']=='声笺'
    finally:
        if service:service.shutdown();service.server_close()
        occupied.shutdown();occupied.server_close()

