import concurrent.futures
import json
import secrets

import pytest
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from server.core_v2.app import PREFIX, create_app
from server.core_v2.store import Fault, Store

ADMIN = 'isolated-test-admin-'+'x'*32
PASSWORD = 'isolated-test-password-123'


@pytest.fixture
def core(tmp_path):
    app = create_app(tmp_path, admin_token=ADMIN)
    with TestClient(app) as client:
        yield client, app.state.store


def account(client, store, username='tester', credits=100):
    code = store.invite(credits=credits)
    response = client.post(PREFIX+'/auth/register', json={'username': username, 'password': PASSWORD, 'invite': code})
    assert response.status_code == 200
    data = response.json()
    return {'Authorization': 'Bearer '+data['token']}, data


def device(client, header):
    row = client.post(PREFIX+'/devices', headers=header, json={'name': 'isolated device', 'capabilities': ['tasks','metrics']}).json()
    client.patch(PREFIX+'/devices/'+row['id'], headers=header, json={'grants': ['tasks','metrics']}).raise_for_status()
    return row


def task(client, header, target, request_id=None, prompt='Run isolated tests'):
    return client.post(PREFIX+'/tasks', headers=header, json={'device_id': target['id'], 'request_id': request_id or secrets.token_hex(16), 'prompt': prompt, 'engine': 'harness'})


def test_invite_is_consumed_once_and_password_not_stored_in_plaintext(core):
    client, store = core
    invite = store.invite(credits=100)
    values = {'username': 'tester', 'password': PASSWORD, 'invite': invite}
    assert client.post(PREFIX+'/auth/register', json=values).status_code == 200
    values['username'] = 'other-user'
    assert client.post(PREFIX+'/auth/register', json=values).status_code == 403
    row = store.db.execute('SELECT password FROM users').fetchone()
    assert row['password'].startswith('$argon2id$') and PASSWORD not in row['password']
    assert store.db.execute('SELECT code FROM invites').fetchone()['code'] != invite


def test_sessions_logout_and_account_isolation(core):
    client, store = core
    one, a = account(client, store)
    two, _ = account(client, store, 'second-user')
    target = device(client, one)
    created = task(client, one, target).json()['task']
    assert client.get(PREFIX+'/devices', headers=two).json()['devices'] == []
    assert client.get(PREFIX+'/tasks/'+created['id'], headers=two).status_code == 404
    assert client.delete(PREFIX+'/devices/'+target['id'], headers=two).status_code == 404
    assert task(client, two, target).status_code == 404
    client.post(PREFIX+'/auth/logout', headers=one).raise_for_status()
    assert client.get(PREFIX+'/me', headers=one).status_code == 401
    login = client.post(PREFIX+'/auth/login', json={'username': 'tester', 'password': PASSWORD}).json()
    assert login['user_id'] == a['user_id']


def test_device_needs_explicit_supported_capability_grant(core):
    client, store = core
    header, _ = account(client, store)
    target = client.post(PREFIX+'/devices', headers=header, json={'name': 'device', 'capabilities': ['tasks']}).json()
    assert task(client, header, target).status_code == 403
    assert client.patch(PREFIX+'/devices/'+target['id'], headers=header, json={'grants': ['screen']}).status_code == 400
    assert 'token' not in client.get(PREFIX+'/devices', headers=header).json()['devices'][0]


def test_idempotent_task_creation_conflicts_on_changed_prompt(core):
    client, store = core
    header, _ = account(client, store)
    target = device(client, header)
    request_id = secrets.token_hex(16)
    one = task(client, header, target, request_id).json()['task']
    two = task(client, header, target, request_id).json()['task']
    assert one['id'] == two['id']
    assert task(client, header, target, request_id, 'different action').status_code == 409


def test_cancel_undelivered_task_without_claiming_remote_execution(core):
    client, store = core
    header, _ = account(client, store)
    target = device(client, header)
    created = task(client, header, target).json()['task']
    response = client.post(PREFIX+'/tasks/'+created['id']+'/cancel', headers=header).json()['task']
    assert response['state'] == 'cancelled' and response['dispatched'] is None
    assert store.dispatch(target['id']) is None


def test_socket_execution_cancel_ack_and_event_replay(core):
    client, store = core
    header, _ = account(client, store)
    target = device(client, header)
    with client.websocket_connect(PREFIX+'/device/ws') as ws:
        ws.send_json({'token': target['token']})
        assert ws.receive_json()['type'] == 'ready'
        created = task(client, header, target).json()['task']
        start = ws.receive_json()
        assert start['type'] == 'task.start' and start['task_id'] == created['id']
        event = {'type': 'task.event', 'task_id': created['id'], 'event_id': 'start-event', 'event': {'type': 'task.state', 'state': 'running'}}
        ws.send_json(event)
        assert ws.receive_json()['type'] == 'event.ack'
        ws.send_json(event)
        assert ws.receive_json()['type'] == 'event.ack'
        before = client.post(PREFIX+'/tasks/'+created['id']+'/cancel', headers=header).json()['task']
        assert before['state'] == 'running' and before['cancel_requested'] == 1
        assert ws.receive_json()['type'] == 'task.cancel'
        ws.send_json({**event, 'event_id': 'cancel-event', 'event': {'type': 'task.state', 'state': 'cancelled'}})
        assert ws.receive_json()['type'] == 'event.ack'
        result = client.get(PREFIX+'/tasks/'+created['id']+'/events', headers=header).json()['events']
        assert [r['seq'] for r in result] == list(range(1, len(result)+1))
        assert len([r for r in result if r.get('state') == 'running']) == 1
        after = client.get(PREFIX+'/tasks/'+created['id']+'/events?after=2', headers=header).json()['events']
        assert all(row['seq'] > 2 for row in after)
    assert store.task(store.authenticate(header['Authorization'][7:])['user_id'], created['id'])['state'] == 'cancelled'


def test_disconnect_marks_dispatched_task_unknown_and_never_replays(core):
    client, store = core
    header, data = account(client, store)
    target = device(client, header)
    with client.websocket_connect(PREFIX+'/device/ws') as ws:
        ws.send_json({'token': target['token']})
        ws.receive_json()
        created = task(client, header, target).json()['task']
        assert ws.receive_json()['type'] == 'task.start'
    assert store.task(data['user_id'], created['id'])['state'] == 'unknown'
    assert store.dispatch(target['id']) is None


def test_server_restart_does_not_replay_dispatched_task(tmp_path):
    store = Store(tmp_path)
    identity = store.register('restart-user', PASSWORD, store.invite(100))
    uid = identity['user_id']
    target = store.enroll(uid, 'device', ['tasks'])
    store.authorize_device(uid, target['id'], ['tasks'])
    job = store.create_task(uid, {'device_id': target['id'], 'request_id': 'restart-request-1', 'prompt': 'test', 'engine': 'harness'})
    store.dispatch(target['id'])
    store.close()
    reopened = Store(tmp_path)
    try:
        assert reopened.task(uid, job['id'])['state'] == 'unknown'
        assert reopened.dispatch(target['id']) is None
        assert reopened.authenticate(identity['token'])['user_id'] == uid
    finally:
        reopened.close()


def test_reservations_are_atomic_and_settlement_is_idempotent(core):
    client, store = core
    _, identity = account(client, store, credits=10)
    uid = identity['user_id']
    def reserve(index):
        try:
            store.reserve(uid, 'usage-'+str(index), 8, 'test-request')
            return index
        except Fault as error:
            assert error.code == 'insufficient_credits'
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        success = [i for i in pool.map(reserve, [1,2]) if i is not None]
    assert len(success) == 1
    ident = 'usage-'+str(success[0])
    assert store.wallet(uid) == {'balance': 2, 'reserved': 8}
    store.settle(uid, ident, 3)
    store.settle(uid, ident, 3)
    assert store.wallet(uid) == {'balance': 7, 'reserved': 0}
    with pytest.raises(Fault):
        store.settle(uid, ident, 1)
    with pytest.raises(Fault):
        store.reserve(uid, ident, 8, 'test-request')


def test_admin_credit_grant_is_idempotent_and_user_cannot_self_credit(core):
    client, store = core
    header, identity = account(client, store, credits=0)
    payload = {'user_id': identity['user_id'], 'amount': 10, 'request_id': 'isolated-grant-request'}
    assert client.post(PREFIX+'/admin/credits', headers=header, json=payload).status_code == 401
    admin = {'Authorization': 'Bearer '+ADMIN}
    for _ in range(2):
        client.post(PREFIX+'/admin/credits', headers=admin, json=payload).raise_for_status()
    assert store.wallet(identity['user_id'])['balance'] == 10
    assert client.post(PREFIX+'/admin/credits', headers=admin, json={**payload, 'amount': 20}).status_code == 409


def test_revocation_rejects_saved_device_token(core):
    client, store = core
    header, identity = account(client, store)
    target = device(client, header)
    client.delete(PREFIX+'/devices/'+target['id'], headers=header).raise_for_status()
    with pytest.raises(Fault):
        store.authenticate(target['token'], device=True)
    assert task(client, header, target).status_code == 404


def test_body_limit_and_missing_provider_readiness(core):
    client, _ = core
    assert client.post(PREFIX+'/auth/login', content=b'x'*131073).status_code == 413
    assert client.get(PREFIX+'/health').json()['providers'] == {'models': False, 'voice': False}


def test_approvals_are_owned_single_use_and_do_not_resume_until_device_ack(core):
    client,store=core
    header,owner=account(client,store)
    other,_=account(client,store,'approval-other')
    target=device(client,header)
    created=task(client,header,target).json()['task'];ident=created['id']
    store.dispatch(target['id'])
    store.device_event(target['id'],ident,{'type':'task.state','state':'running'},'running-event')
    store.device_event(target['id'],ident,{'type':'task.approval','approval_id':'one-approval','text':'fixture command'},'approval-event')
    path=PREFIX+'/tasks/'+ident+'/approvals/one-approval'
    assert client.post(path,headers=other,json={'allow':True}).status_code==404
    assert client.post(path,headers=header,json={'allow':True}).status_code==200
    assert client.post(path,headers=header,json={'allow':True}).status_code==200
    assert client.post(path,headers=header,json={'allow':False}).status_code==409
    assert store.task(owner['user_id'],ident)['state']=='awaiting_user'
    assert len(store.decisions(target['id']))==1
    store.device_event(target['id'],ident,{'type':'task.state','state':'running'},'resumed-event')
    assert not store.decisions(target['id'])


def test_unknown_usage_can_only_be_reconciled_by_admin_idempotently(core):
    client,store=core
    header,owner=account(client,store)
    store.reserve(owner['user_id'],'held-usage-request',10,'isolated-fingerprint')
    path=PREFIX+'/admin/usage/held-usage-request/settle'
    body={'user_id':owner['user_id'],'actual':3}
    assert client.post(path,headers=header,json=body).status_code==401
    admin={'Authorization':'Bearer '+ADMIN}
    assert client.post(path,headers=admin,json=body).status_code==200
    assert client.post(path,headers=admin,json=body).status_code==200
    assert client.post(path,headers=admin,json={**body,'actual':4}).status_code==409
    assert client.get(PREFIX+'/usage',headers=header).json()['usage'][0]['state']=='settled'
    assert store.wallet(owner['user_id'])=={'balance':97,'reserved':0}
