import hashlib
import http.client
import json
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import gui_app as bridge
import peer_share
from mac_tunnel import PublicGateway


def post(port,path,payload,headers=None):
    conn=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
    conn.request('POST',path,payload,headers or {'Content-Type':'application/json'})
    result=conn.getresponse();status,body=result.status,json.loads(result.read());conn.close()
    return status,body


@pytest.fixture
def machines(tmp_path,monkeypatch):
    services=[];gateways=[]
    for name in ['alpha','beta','gamma']:
        monkeypatch.setattr(bridge,'DATA_DIR',tmp_path/name)
        service=bridge.BridgeServer(('127.0.0.1',0),bridge.BridgeRequestHandler,'local-key')
        gateway=PublicGateway(service.server_port)
        service.peer_manager.endpoint_provider=lambda port=gateway.server_port:f'http://127.0.0.1:{port}'
        for server in [service,gateway]:threading.Thread(target=server.serve_forever,daemon=True).start()
        services.append(service);gateways.append(gateway)
    try:yield [server.peer_manager for server in services],gateways
    finally:
        for server in gateways+services:server.shutdown();server.server_close()


def pair(left,right):
    return left.join(right.invite()['invitation'])


def wait_job(manager,ident):
    for _ in range(100):
        row=next(row for row in manager.snapshot()['jobs'] if row['id']==ident)
        if row['status'] in ['complete','error']:return row
        time.sleep(.05)
    raise AssertionError('transfer timed out')


def test_three_machines_pair_and_transfer_in_both_directions(machines,tmp_path,monkeypatch):
    peers,_=machines;a,b,c=peers
    pair(a,b);pair(a,c)
    monkeypatch.setattr(peer_share,'CHUNK_BYTES',1024)
    source=tmp_path/'多分块 😀.txt';source.write_bytes(bytes(range(256))*34)
    for sender,receiver in [(a,b),(b,a),(a,c),(c,a)]:
        ident=sender.send(receiver.device['id'],[source])['job_id']
        assert wait_job(sender,ident)['status']=='complete'
        target=list((receiver.root/'received').glob('*/'+source.name))[-1]
        assert hashlib.sha256(target.read_bytes()).digest()==hashlib.sha256(source.read_bytes()).digest()
    assert len(a.snapshot()['peers'])==2
    assert 'secret' not in json.dumps(a.snapshot())


def test_invitation_is_one_time_and_expires(machines,monkeypatch):
    (a,b,c),_=machines
    invitation=b.invite()['invitation'];a.join(invitation)
    with pytest.raises(ValueError):c.join(invitation)
    invitation=b.invite()['invitation']
    b.invites={key:time.time()-1 for key in b.invites}
    with pytest.raises(ValueError):c.join(invitation)


def test_removed_peer_cannot_send(machines,tmp_path):
    (a,b,c),_=machines;pair(a,b)
    b.remove(a.device['id'])
    source=tmp_path/'test.txt';source.write_text('revocation')
    job=a.send(b.device['id'],[source])['job_id']
    assert wait_job(a,job)['status']=='error'
    assert not list((b.root/'received').glob('*'))


def test_hmac_replay_and_body_tamper_are_rejected(machines):
    (a,b,c),gateways=machines;pair(a,b)
    peer=a.peers[b.device['id']];path='/peer/ping';body=b'{}';stamp=str(int(time.time()));nonce='a'*32;digest=hashlib.sha256(body).hexdigest()
    headers={'X-Shengjian-Peer':a.device['id'],'X-Shengjian-Time':stamp,'X-Shengjian-Nonce':nonce,'X-Shengjian-SHA256':digest,'X-Shengjian-Signature':peer_share.signature(peer['secret'],'POST',path,stamp,nonce,digest)}
    assert post(gateways[1].server_port,path,body,headers)[0]==200
    assert post(gateways[1].server_port,path,body,headers)[0]==403
    headers['X-Shengjian-Nonce']='b'*32;headers['X-Shengjian-Signature']=peer_share.signature(peer['secret'],'POST',path,stamp,'b'*32,digest)
    assert post(gateways[1].server_port,path,b'{"tampered":true}',headers)[0]==400


def test_chunk_resume_survives_receiver_restart_and_verifies_sha(machines):
    (a,b,c),_=machines;pair(a,b);peer=a.peers[b.device['id']]
    data=b'first-second';ident='c'*32
    metadata=json.dumps({'id':ident,'name':'../../escape.txt','size':len(data),'sha256':hashlib.sha256(data).hexdigest()}).encode()
    assert a.request(peer,'/peer/files/start',metadata)['received']==0
    a.request(peer,f'/peer/files/chunk?id={ident}&offset=0',data[:5])
    restarted=peer_share.PeerManager(b.root,b.endpoint_provider)
    assert restarted.receive(a.device['id'],'/peer/files/start',metadata)['received']==5
    restarted.receive(a.device['id'],f'/peer/files/chunk?id={ident}&offset=5',data[5:])
    receipt=restarted.receive(a.device['id'],'/peer/files/finish',json.dumps({'id':ident}).encode())
    assert receipt['sha256']==hashlib.sha256(data).hexdigest()
    assert (b.root/'received'/ident/'escape.txt').read_bytes()==data
    assert not (b.root.parent/'escape.txt').exists()


def test_wrong_checksum_never_publishes_file(machines):
    (a,b,c),_=machines;pair(a,b);peer=a.peers[b.device['id']];ident='d'*32
    metadata=json.dumps({'id':ident,'name':'wrong.txt','size':4,'sha256':'0'*64}).encode()
    a.request(peer,'/peer/files/start',metadata)
    a.request(peer,f'/peer/files/chunk?id={ident}&offset=0',b'data')
    with pytest.raises(ValueError):a.request(peer,'/peer/files/finish',json.dumps({'id':ident}).encode())
    assert not (b.root/'received'/ident/'wrong.txt').exists()


def test_endpoint_change_is_authenticated_and_persisted(machines):
    (a,b,c),_=machines;pair(a,b)
    a.endpoint_provider=lambda:'https://new-example.trycloudflare.com'
    a.advertise()
    assert b.peers[a.device['id']]['endpoint']=='https://new-example.trycloudflare.com'
    assert peer_share.PeerManager(b.root,b.endpoint_provider).peers[a.device['id']]['endpoint']=='https://new-example.trycloudflare.com'


@pytest.mark.parametrize('value',['http://example.com','https://user:password@example.com','https://example.com/path','file:///tmp/test'])
def test_reject_malformed_endpoints(value):
    with pytest.raises(ValueError):peer_share.endpoint(value)
