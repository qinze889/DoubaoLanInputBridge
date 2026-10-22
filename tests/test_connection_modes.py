import json
from types import SimpleNamespace
import pytest
import connection_modes as modes
import peer_share


class Tunnel:
    def __init__(self): self.ready = False; self.started = 0; self.stopped = 0
    def status(self): return {'ready': self.ready, 'public_url': 'https://test.trycloudflare.com', 'phase': 'ready' if self.ready else 'off', 'error': ''}
    def start(self, port): self.ready = True; self.started += 1
    def stop(self): self.ready = False; self.stopped += 1


def setup_modes(tmp_path, monkeypatch):
    clients = []
    def connect(*args):
        client = SimpleNamespace(status={'phase': 'online', 'error': ''}, closed=False, rtc=None)
        client.close = lambda: setattr(client, 'closed', True)
        clients.append(client)
        return client
    monkeypatch.setattr(modes.relay_client, 'from_data_dir', connect)
    server = SimpleNamespace(server_port=8766, quick_tunnel=Tunnel(), relay=None, peer_manager=None)
    manager = modes.ConnectionModes(server, tmp_path, lambda: 'local-key', lambda: '10.0.0.8')
    return server, manager, clients


def test_four_modes_persist_and_stop_other_transports(tmp_path, monkeypatch):
    server, manager, clients = setup_modes(tmp_path, monkeypatch)
    config = {'url':'https://test.xjiaoai.com/shengjian', 'device_id':'a'*24, 'token':'b'*43, 'mobile_token':'c'*43}
    manager.import_config(config)
    assert manager.snapshot()['ready'] and '/d/' in manager.url()
    manager.select('p2p')
    assert clients[0].closed and '/p2p/' in manager.peer_endpoint()
    assert json.loads((tmp_path/'relay.json').read_text())['connection_mode'] == 'p2p'
    manager.select('cloudflare')
    assert clients[-1].closed and server.quick_tunnel.started == 1
    assert manager.url().startswith('https://test.trycloudflare.com/')
    manager.select('lan')
    assert not server.quick_tunnel.ready
    assert not json.loads((tmp_path/'relay.json').read_text())['enabled']
    assert manager.url() == 'http://10.0.0.8:8766/?key=local-key'
    restored = modes.ConnectionModes(server, tmp_path, lambda: 'k', lambda: '10.0.0.8')
    assert restored.config == {'mode': 'lan', 'enabled': True}
    manager.select('lan', False)
    assert not manager.url() and not manager.snapshot()['ready']


def test_invalid_config_does_not_overwrite_working_credentials(tmp_path, monkeypatch):
    _, manager, _ = setup_modes(tmp_path, monkeypatch)
    valid = {'url':'https://test.xjiaoai.com/shengjian', 'device_id':'a'*24, 'token':'b'*43, 'mobile_token':'c'*43}
    manager.import_config(valid)
    before = (tmp_path/'relay.json').read_bytes()
    with pytest.raises(ValueError): manager.import_config({**valid, 'mobile_token': '?'*40})
    assert (tmp_path/'relay.json').read_bytes() == before


def test_p2p_never_silently_relays_file_to_public_receiver(tmp_path):
    own = peer_share.PeerManager(tmp_path, lambda: 'https://test.xjiaoai.com/shengjian/p2p/'+'a'*24)
    with pytest.raises(ValueError, match='不会通过服务器'):
        own.request({'endpoint': 'https://test.xjiaoai.com/shengjian/bridge/'+'b'*24}, '/peer/files/start', b'{}')
