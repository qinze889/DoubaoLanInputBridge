"""One explicit connection mode. Never label a relayed transfer as P2P."""
import json
import re
import threading
from pathlib import Path
from urllib.parse import quote
import peer_share
import relay_client
import rtc_bridge

MODES = {
    'public': ('固定公网', '经自己的服务器中转，域名固定，适合跨网络稳定连接。'),
    'cloudflare': ('CF 隧道', '经 Cloudflare 加密连接，不需要自建服务器。'),
    'p2p': ('P2P 直连', '服务器只协助握手，文字和文件直接在设备间加密传送。'),
    'lan': ('局域网', '同一 Wi-Fi 或内网直接连接，不经过公网服务器。'),
}


class ConnectionModes:
    def __init__(self, server, root, key_provider, host_provider):
        self.server, self.root = server, Path(root)
        self.key_provider, self.host_provider = key_provider, host_provider
        self.path = self.root/'connections.json'
        self.lock = threading.RLock()
        self.config = peer_share.load_json(self.path, {})
        if self.config.get('mode') not in MODES:
            self.config = {'mode': 'public' if relay_client.phone_url(root, True) else 'lan', 'enabled': True}

    def url(self):
        if not self.config['enabled']: return ''
        mode = self.config['mode']
        if mode in ('public', 'p2p'):
            return relay_client.phone_url(self.root)
        if mode == 'cloudflare':
            state = self.server.quick_tunnel.status()
            return state['public_url']+'/?key='+quote(self.key_provider(), safe='') if state['ready'] else ''
        host = self.host_provider()
        return f'http://{host}:{self.server.server_port}/?key='+quote(self.key_provider(), safe='') if host != '127.0.0.1' else ''

    def peer_endpoint(self):
        mode = self.config['mode']
        if mode in ('public', 'p2p') and self.config['enabled']:
            try:
                c = json.loads((self.root/'relay.json').read_text())
                return c['url'].rstrip('/')+('/p2p/' if mode == 'p2p' else '/bridge/')+c['device_id']
            except (ValueError, KeyError, OSError): pass
        if mode == 'cloudflare' and self.config['enabled']:
            quick = self.server.quick_tunnel.status()
            if quick['ready']: return quick['public_url']
        return f'http://{self.host_provider()}:{self.server.server_port}'

    def snapshot(self):
        mode, enabled = self.config['mode'], self.config['enabled']
        configured = bool(relay_client.phone_url(self.root, True))
        client = getattr(self.server, 'relay', None)
        if not enabled: phase, error = 'off', ''
        elif mode in ('public', 'p2p'):
            phase = client.status['phase'] if client else 'error'
            error = client.status['error'] if client else '请导入这台机器的服务器配置'
        elif mode == 'cloudflare':
            state = self.server.quick_tunnel.status();phase, error = state['phase'], state['error']
        else: phase, error = ('ready', '') if self.url() else ('error', '未检测到可用局域网地址')
        engine = getattr(client, 'rtc', None)
        return {'mode': mode, 'enabled': enabled, 'phase': phase, 'error': error,
                'ready': enabled and phase in ('ready', 'online'), 'url': self.url(),
                'peer_endpoint': self.peer_endpoint(),
                'p2p': dict(engine.status) if engine else {'available': rtc_bridge.available(), 'connections': 0},
                'modes': [{'id': ident, 'title': title, 'description': detail,
                           'configured': configured if ident in ('public', 'p2p') else True,
                           'available': rtc_bridge.available() if ident == 'p2p' else True}
                          for ident, (title, detail) in MODES.items()]}

    def select(self, mode, enabled=True):
        if mode not in MODES: raise ValueError('请选择四种连接方式之一')
        if enabled and mode in ('public', 'p2p') and not relay_client.phone_url(self.root, True):
            raise ValueError('请先导入本机的服务器配置 relay.json')
        if enabled and mode == 'p2p' and not rtc_bridge.available():
            raise ValueError('安装包缺少 P2P 组件，请安装完整版本')
        with self.lock:
            outgoing = getattr(self.server.peer_manager, 'rtc_outgoing', None)
            if outgoing:
                outgoing.close()
                self.server.peer_manager.rtc_outgoing = None
            previous = getattr(self.server, 'relay', None)
            if previous:
                previous.close()
                self.server.relay = None
            if mode != 'cloudflare' or not enabled:
                self.server.quick_tunnel.stop()
            self.config = {'mode': mode, 'enabled': bool(enabled)}
            peer_share.atomic_json(self.path, self.config)
            relay_path = self.root/'relay.json'
            if relay_path.exists():
                relay = peer_share.load_json(relay_path, {})
                relay['enabled'] = bool(enabled and mode in ('public', 'p2p'))
                relay['connection_mode'] = mode
                peer_share.atomic_json(relay_path, relay)
                if relay['enabled']:
                    self.server.relay = relay_client.from_data_dir(self.root, self.server.server_port, self.key_provider, self.server.peer_manager)
            if enabled and mode == 'cloudflare':
                self.server.quick_tunnel.start(self.server.server_port)
        return self.snapshot()

    def import_config(self, data):
        allowed = {'url', 'device_id', 'token', 'mobile_token'}
        if not isinstance(data, dict) or not allowed.issubset(data):
            raise ValueError('请选择后台生成的本机 relay.json')
        clean = {k: str(data[k]).strip() for k in allowed}
        if any(len(v) > 2048 for v in clean.values()) or any(len(clean[k]) < 32 for k in ('token', 'mobile_token')):
            raise ValueError('配置格式不正确')
        relay_client.RelayClient(clean, self.server.server_port, self.key_provider)
        if not re.fullmatch(r'[A-Za-z0-9_-]{32,100}', clean['mobile_token']):
            raise ValueError('配置中的手机连接码不正确')
        clean['enabled'] = False
        peer_share.atomic_json(self.root/'relay.json', clean)
        return self.select('public', True)
