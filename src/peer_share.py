"""Paired-machine sharing: per-device HMAC, resumable 8 MiB chunks, SHA256 receipts."""
import hashlib
import hmac
import http.client
import ipaddress
import json
import os
import re
import secrets
import socket
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

CHUNK_BYTES = 8 * 1024 * 1024
JSON_BYTES = 64 * 1024
SEND_CHUNK_BYTES = 1024 * 1024


def safe_filename(value):
    name = str(value).replace('\\', '/').split('/')[-1]
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip('. ')
    if name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$',
                                    *('COM'+str(i) for i in range(1, 10)),
                                    *('LPT'+str(i) for i in range(1, 10))}:
        name = '_' + name
    # Keep a component below both NTFS and UTF-8 filesystem limits.
    stem, suffix = os.path.splitext(name)
    if len(suffix.encode('utf-8')) > 30:
        stem, suffix = name, ''
    while len((stem + suffix).encode('utf-8')) > 120:
        stem = stem[:-1]
    return (stem.rstrip('. ') + suffix).rstrip('. ')


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    try:
        with temp.open('x', encoding='utf-8') as output:
            if os.name != 'nt': os.chmod(temp, 0o600)
            json.dump(value, output, ensure_ascii=False)
        temp.replace(path)
    finally:
        if temp.exists(): temp.unlink()


def load_json(path, default):
    try: return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError): return default


def endpoint(value):
    parsed = urlsplit(str(value).strip())
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise ValueError('连接地址只能包含主机和端口')
    if parsed.scheme not in ('https','http') or not parsed.hostname:
        raise ValueError('请输入完整的 HTTPS 连接地址')
    if parsed.scheme == 'http':
        try: address = ipaddress.ip_address(parsed.hostname)
        except ValueError: raise ValueError('HTTP 仅用于局域网 IP')
        if not (address.is_loopback or any(address in ipaddress.ip_network(net) for net in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16'))):
            raise ValueError('公网连接需要 HTTPS')
    return parsed.geturl().rstrip('/')


def signature(secret, method, path, stamp, nonce, digest):
    canonical = '\n'.join([method,path,stamp,nonce,digest]).encode()
    return hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()


class NoPeerRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('机器连接地址发生跳转，请重新配对')


def transport(base, path, payload, headers):
    base = endpoint(base)
    # Honor the user's Windows/macOS system proxy for public HTTPS connections.
    # LAN traffic stays direct; signatures must never follow a redirect.
    proxy = ProxyHandler() if urlsplit(base).scheme == 'https' else ProxyHandler({})
    opener = build_opener(proxy, NoPeerRedirect())
    request = Request(base+path, payload, headers, method='POST')
    try:
        response = opener.open(request, timeout=90)
    except HTTPError as error:
        response = error
    with response:
        data = json.loads(response.read(JSON_BYTES))
        if response.status != 200 or not data.get('ok'):
            raise ValueError(data.get('error','另一台设备未完成请求'))
        return data


class PeerManager:
    def __init__(self, data_dir, endpoint_provider):
        self.root = Path(data_dir)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.endpoint_provider = endpoint_provider
        self.lock = threading.RLock()
        self.identity_file = self.root/'device.json'
        self.device = load_json(self.identity_file, None)
        if not self.device:
            self.device = {'id':uuid.uuid4().hex,'name':socket.gethostname().split('.')[0][:64] or 'Mac'}
            atomic_json(self.identity_file,self.device)
        self.peers_file = self.root/'paired-devices.json'
        self.peers = load_json(self.peers_file,{})
        self.invites = {}
        self.nonces = {}
        self.jobs = {}
        self.upload_locks = {}
        self.advertised = ''

    def snapshot(self):
        with self.lock:
            return {'device':dict(self.device),'peers':[{'id':row['id'],'name':row['name'],'endpoint':row['endpoint'],'paired_at':row['paired_at']} for row in self.peers.values()],
                    'jobs':[dict(job) for job in list(self.jobs.values())[-50:]][::-1],
                    'received_dir':str(self.root/'received')}

    def invite(self):
        base = endpoint(self.endpoint_provider())
        code = secrets.token_urlsafe(32)
        with self.lock:
            self.invites = {code:time.time()+300}
        return {'invitation':'shengjian://pair?'+urlencode({'endpoint':base,'code':code}), 'expires_in':300}

    def join(self, invitation):
        parsed = urlsplit(invitation.strip())
        if parsed.scheme != 'shengjian' or parsed.netloc != 'pair': raise ValueError('请粘贴完整的机器配对邀请')
        fields = parse_qs(parsed.query)
        base = endpoint((fields.get('endpoint') or [''])[0])
        code = (fields.get('code') or [''])[0]
        if not code: raise ValueError('邀请缺少配对码')
        own_endpoint = endpoint(self.endpoint_provider())
        if urlsplit(base).scheme == 'https' and urlsplit(own_endpoint).scheme != 'https':
            raise ValueError('对方使用公网邀请，请先开启本机公网连接再配对。')
        shared = secrets.token_urlsafe(32)
        payload = {'code':code,'device':dict(self.device),'endpoint':own_endpoint,'secret':shared}
        result = transport(base,'/peer/pair',json.dumps(payload).encode(),{'Content-Type':'application/json'})
        remote = result['device']
        if not re.fullmatch('[a-f0-9]{32}', str(remote.get('id',''))) or remote['id'] == self.device['id']: raise ValueError('无效的目标机器身份')
        with self.lock:
            self.peers[remote['id']] = {'id':remote['id'],'name':str(remote['name'])[:64],'endpoint':base,'secret':shared,'paired_at':time.time()}
            atomic_json(self.peers_file,self.peers)
        return self.snapshot()

    def accept_pair(self, data):
        other = data.get('device') or {}
        ident = str(other.get('id',''))
        secret = str(data.get('secret',''))
        if not re.fullmatch('[a-f0-9]{32}',ident) or ident == self.device['id'] or len(secret) < 32:
            raise ValueError('无效的机器配对信息')
        remote_endpoint = endpoint(data.get('endpoint',''))
        with self.lock:
            code = str(data.get('code',''))
            expiry = self.invites.get(code,0)
            if expiry < time.time(): raise PermissionError('邀请已失效，请在另一台机器重新生成')
            del self.invites[code]
            self.peers[ident] = {'id':ident,'name':str(other.get('name','Mac'))[:64],'endpoint':remote_endpoint,'secret':secret,'paired_at':time.time()}
            atomic_json(self.peers_file,self.peers)
        return {'device':dict(self.device)}

    def remove(self, ident):
        with self.lock:
            self.peers.pop(ident,None)
            atomic_json(self.peers_file,self.peers)
        return self.snapshot()

    def authenticate(self, method, path, headers):
        ident = headers.get('X-Shengjian-Peer','')
        stamp, nonce = headers.get('X-Shengjian-Time',''), headers.get('X-Shengjian-Nonce','')
        digest = headers.get('X-Shengjian-SHA256','')
        with self.lock:
            peer = self.peers.get(ident)
            try: timely = abs(time.time()-int(stamp)) <= 120
            except ValueError: timely = False
            if not peer or not timely or not re.fullmatch('[a-f0-9]{64}',digest) or not re.fullmatch('[a-f0-9]{32}',nonce):
                raise PermissionError('机器身份验证失败')
            expected = signature(peer['secret'],method,path,stamp,nonce,digest)
            if not hmac.compare_digest(expected,headers.get('X-Shengjian-Signature','')):
                raise PermissionError('机器身份验证失败')
            self.nonces = {key:expiry for key,expiry in self.nonces.items() if expiry > time.time()}
            if (ident,nonce) in self.nonces: raise PermissionError('重复请求已拒绝')
            self.nonces[(ident,nonce)] = time.time()+240
            if len(self.nonces)>8192: raise PermissionError('请求过于频繁')
        return ident,digest

    def request(self, peer, path, data):
        stamp,nonce = str(int(time.time())),uuid.uuid4().hex
        digest = hashlib.sha256(data).hexdigest()
        headers = {'Content-Type':'application/octet-stream','X-Shengjian-Peer':self.device['id'],
                   'X-Shengjian-Time':stamp,'X-Shengjian-Nonce':nonce,'X-Shengjian-SHA256':digest,
                   'X-Shengjian-Signature':signature(peer['secret'],'POST',path,stamp,nonce,digest)}
        return transport(peer['endpoint'],path,data,headers)

    def receive(self, peer_id, path, body):
        route = urlsplit(path)
        data = None if route.path == '/peer/files/chunk' else json.loads(body)
        if route.path == '/peer/endpoint':
            base = endpoint(data['endpoint'])
            with self.lock:
                self.peers[peer_id]['endpoint'] = base
                atomic_json(self.peers_file,self.peers)
            return {}
        if route.path == '/peer/ping': return {'device':dict(self.device)}
        fields = parse_qs(route.query)
        ident = str((fields.get('id') or [''])[0]) if data is None else str(data.get('id',''))
        if not re.fullmatch('[a-f0-9]{32}',ident): raise ValueError('无效传输编号')
        with self.lock: guard = self.upload_locks.setdefault(ident,threading.RLock())
        with guard:
            folder = self.root/'incoming'/ident
            meta_file = folder/'state.json'
            meta = load_json(meta_file,None)
            if route.path == '/peer/files/start':
                filename = safe_filename(data.get('name',''))
                size = int(data.get('size',-1)); checksum = str(data.get('sha256',''))
                if not filename or size < 0 or not re.fullmatch('[a-f0-9]{64}',checksum): raise ValueError('无效文件信息')
                if meta:
                    if (meta['peer'],meta['size'],meta['sha256']) != (peer_id,size,checksum): raise PermissionError('传输不属于当前机器')
                else:
                    folder.mkdir(parents=True,exist_ok=True)
                    meta = {'id':ident,'peer':peer_id,'name':filename,'size':size,'sha256':checksum,'received':0,'complete':False}
                    (folder/'data.part').touch()
                    atomic_json(meta_file,meta)
                with self.lock:
                    self.jobs['receive-'+ident] = {'id':'receive-'+ident,'peer_name':self.peers[peer_id]['name'],'direction':'receive','status':'complete' if meta['complete'] else 'receiving','name':meta['name'],'sent':meta['received'],'total':meta['size'],'error':''}
                return {'received':meta['received'],'complete':meta['complete']}
            if meta is None or meta['peer'] != peer_id: raise PermissionError('找不到这台机器的传输')
            if route.path == '/peer/files/chunk':
                offset = int((fields.get('offset') or ['-1'])[0])
                if meta['complete']: return {'received':meta['received']}
                if offset != meta['received'] or not body or len(body)>CHUNK_BYTES or offset+len(body)>meta['size']:
                    raise ValueError('文件分块位置不匹配，请重试传输')
                with (folder/'data.part').open('r+b') as output:
                    output.seek(offset);output.write(body);output.flush();os.fsync(output.fileno())
                meta['received'] += len(body);atomic_json(meta_file,meta)
                with self.lock:
                    if 'receive-'+ident in self.jobs: self.jobs['receive-'+ident]['sent'] = meta['received']
                return {'received':meta['received']}
            if route.path != '/peer/files/finish': raise ValueError('未知传输操作')
            if meta['complete']: return {'name':meta['name'],'sha256':meta['sha256']}
            if meta['received'] != meta['size']: raise ValueError('文件尚未收齐')
            with (folder/'data.part').open('rb') as source:
                checksum = hashlib.file_digest(source,'sha256').hexdigest()
            if checksum != meta['sha256']: raise ValueError('文件校验失败，请重新发送')
            target = self.root/'received'/ident/meta['name'];target.parent.mkdir(parents=True,exist_ok=True)
            (folder/'data.part').replace(target)
            meta['complete'] = True;atomic_json(meta_file,meta)
            with self.lock:
                self.jobs['receive-'+ident] = {'id':'receive-'+ident,'peer_name':self.peers[peer_id]['name'],'direction':'receive','status':'complete','name':meta['name'],'sent':meta['size'],'total':meta['size'],'path':str(target),'error':''}
            return {'name':meta['name'],'sha256':checksum}

    def send(self, peer_id, paths):
        with self.lock:
            peer = dict(self.peers[peer_id])
        sources = [Path(path).expanduser().resolve(strict=True) for path in paths]
        if not sources or any(not source.is_file() for source in sources): raise ValueError('请选择普通文件')
        ident = uuid.uuid4().hex
        job = {'id':ident,'peer_name':peer['name'],'direction':'send','status':'sending','name':sources[0].name if len(sources)==1 else f'{len(sources)} 个文件',
               'sent':0,'total':sum(p.stat().st_size for p in sources),'error':''}
        with self.lock: self.jobs[ident] = job
        threading.Thread(target=self._send_worker,args=(ident,peer,sources),daemon=True).start()
        return {'job_id':ident}

    def _send_worker(self, ident, peer, sources):
        completed = 0
        try:
            for source in sources:
                with source.open('rb') as stream: checksum = hashlib.file_digest(stream,'sha256').hexdigest()
                file_id = uuid.uuid4().hex;size = source.stat().st_size
                info = json.dumps({'id':file_id,'name':source.name,'size':size,'sha256':checksum}).encode()
                response = self.request(peer,'/peer/files/start',info)
                offset = response['received']
                with source.open('rb') as stream:
                    retries = 0
                    while offset<size:
                        stream.seek(offset);chunk=stream.read(min(CHUNK_BYTES,SEND_CHUNK_BYTES,size-offset))
                        if not chunk: raise ValueError('源文件在传输期间发生变化')
                        try:
                            reply=self.request(peer,'/peer/files/chunk?'+urlencode({'id':file_id,'offset':offset}),chunk)
                            offset=reply['received'];retries=0
                        except (OSError,ValueError,http.client.HTTPException):
                            retries+=1
                            if retries>2: raise ValueError('连接中断，自动重试失败')
                            time.sleep(.5)
                            offset=self.request(peer,'/peer/files/start',info)['received']
                        with self.lock: self.jobs[ident]['sent']=completed+offset
                finish=self.request(peer,'/peer/files/finish',json.dumps({'id':file_id}).encode())
                if finish.get('sha256') != checksum: raise ValueError('接收端文件校验不一致')
                completed+=size
            with self.lock: self.jobs[ident].update(status='complete',sent=completed)
        except Exception:
            with self.lock: self.jobs[ident].update(status='error',error='传输未完成，请确认对方在线后重新发送。')

    def advertise(self):
        try: base=endpoint(self.endpoint_provider())
        except ValueError:return
        with self.lock:
            if base==self.advertised:return
            peers=[dict(peer) for peer in self.peers.values()]
        succeeded=True
        for peer in peers:
            try:self.request(peer,'/peer/endpoint',json.dumps({'endpoint':base}).encode())
            except Exception:succeeded=False
        if succeeded:self.advertised=base


def handle_public(handler, manager, responder):
    try:
        path=urlsplit(handler.path).path
        length=int(handler.headers.get('Content-Length','0'))
        limit=CHUNK_BYTES if path=='/peer/files/chunk' else JSON_BYTES
        if length<1 or length>limit or handler.headers.get('Transfer-Encoding'): raise ValueError('请求大小无效')
        if path=='/peer/pair':
            body=handler.rfile.read(length)
            result=manager.accept_pair(json.loads(body))
        else:
            peer,digest=manager.authenticate('POST',handler.path,handler.headers)
            body=handler.rfile.read(length)
            if len(body)!=length or not hmac.compare_digest(hashlib.sha256(body).hexdigest(),digest): raise ValueError('分块内容校验失败')
            result=manager.receive(peer,handler.path,body)
        responder(handler,200,{'ok':True,**result})
    except PermissionError as error:responder(handler,403,{'ok':False,'error':str(error)})
    except (ValueError,KeyError,TypeError,OSError):responder(handler,400,{'ok':False,'error':'无效的机器共享请求'})
