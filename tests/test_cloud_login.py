import concurrent.futures
import importlib.util
from pathlib import Path
import sqlite3
import time

import pytest
pytest.importorskip('fastapi')
from fastapi.testclient import TestClient

from server.core_v2.app import PREFIX, create_app
from server.core_v2.store import Fault, Store, digest


def test_version_one_migrates_and_reopens_without_losing_accounts(tmp_path):
    path = tmp_path/'core.sqlite3'
    with sqlite3.connect(path) as db:
        db.executescript('''
          CREATE TABLE users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, balance INTEGER DEFAULT 0, reserved INTEGER DEFAULT 0);
          CREATE TABLE devices(id TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id), name TEXT, token TEXT UNIQUE, capabilities TEXT, grants TEXT DEFAULT '[]', revoked INTEGER DEFAULT 0, last_seen REAL, metrics TEXT DEFAULT '{}');
          CREATE TABLE sessions(token TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id), expires REAL);
          INSERT INTO users VALUES('original', 'old-user', 'hash', 345, 0);
          PRAGMA user_version=1;
        ''')
    for _ in range(2):
        store = Store(tmp_path)
        assert store.db.execute('PRAGMA user_version').fetchone()[0] == 2
        assert store.wallet('original')['balance'] == 345
        assert store.db.execute('PRAGMA foreign_key_check').fetchall() == []
        store.close()


@pytest.fixture
def cloud(tmp_path):
    app = create_app(tmp_path, admin_token='test-admin-'+'x'*48)
    with TestClient(app, base_url='https://testserver') as client:
        store = app.state.store
        result = client.post(PREFIX+'/auth/register', json={'username': 'cloud-user', 'password': 'cloud-password-123', 'invite': store.invite(credits=20)}).json()
        yield client, store, {'Authorization': 'Bearer '+result['token']}, result


def test_persistent_https_cookie_resume_logout_and_origin(cloud):
    client, store, auth, session = cloud
    cookie = client.cookies.get('__Secure-shengjian_session')
    assert cookie == session['token']
    resume = client.post(PREFIX+'/auth/session').json()
    assert resume['authenticated'] and resume['user_id'] == session['user_id']
    assert client.post(PREFIX+'/auth/session', headers={'Origin': 'https://attacker.invalid'}).status_code == 403
    assert client.post(PREFIX+'/auth/login', headers={'Sec-Fetch-Site': 'cross-site'}, json={'username': 'cloud-user', 'password': 'cloud-password-123'}).status_code == 403
    assert client.post(PREFIX+'/auth/logout', headers=auth).status_code == 200
    assert not client.post(PREFIX+'/auth/session').json()['authenticated']
    assert client.get(PREFIX+'/me', headers=auth).status_code == 401


def test_cookie_flags(cloud):
    client, _, auth, _ = cloud
    ticket = client.post(PREFIX+'/auth/qr', headers=auth).json()['ticket']
    response = client.post(PREFIX+'/auth/qr/redeem', json={'ticket': ticket})
    value = response.headers['set-cookie'].lower()
    assert 'httponly' in value and 'secure' in value and 'samesite=strict' in value and 'max-age='+str(180*86400) in value


def test_qr_once_separate_token_device_revocation_and_refresh(cloud):
    client, store, auth, parent = cloud
    old = client.post(PREFIX+'/auth/qr', headers=auth).json()['ticket']
    ticket = client.post(PREFIX+'/auth/qr', headers=auth).json()['ticket']
    assert client.post(PREFIX+'/auth/qr/redeem', json={'ticket': old}).status_code == 410
    child = client.post(PREFIX+'/auth/qr/redeem', json={'ticket': ticket}).json()
    assert child['token'] != parent['token'] and child['user_id'] == parent['user_id']
    device = store.device(parent['user_id'], child['device_id'])
    assert device['capabilities'] == device['grants'] == []
    assert client.post(PREFIX+'/auth/qr/redeem', json={'ticket': ticket}).status_code == 410
    assert all(row['ticket'] != ticket for row in store.db.execute('SELECT ticket FROM qr_tickets'))
    assert store.db.execute('SELECT token FROM sessions WHERE token=?', (digest(child['token']),)).fetchone()
    client.delete(PREFIX+'/devices/'+child['device_id'], headers=auth).raise_for_status()
    assert client.get(PREFIX+'/me', headers={'Authorization': 'Bearer '+child['token']}).status_code == 401
    assert client.get(PREFIX+'/me', headers=auth).status_code == 200


def test_qr_parallel_redeem_expiry_and_parent_logout(cloud):
    client, store, _, parent = cloud
    ticket = store.qr_ticket(parent['token'])['ticket']
    def redeem():
        try:
            return store.redeem_qr(ticket, 'phone')['token']
        except Fault as exc:
            return exc.status
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: redeem(), range(2)))
    assert sum(isinstance(result, str) for result in results) == 1
    assert 410 in results
    ticket = store.qr_ticket(parent['token'])['ticket']
    store.db.execute('UPDATE qr_tickets SET expires=?', (time.time()-1,))
    with pytest.raises(Fault, match='qr_expired'):
        store.redeem_qr(ticket, 'phone')
    ticket = store.qr_ticket(parent['token'])['ticket']
    store.logout(parent['token'])
    with pytest.raises(Fault, match='qr_expired'):
        store.redeem_qr(ticket, 'phone')


def test_native_boundary_keeps_bearer_in_vault_and_reuses_login(tmp_path):
    spec = importlib.util.spec_from_file_location('cloud_account_test', Path(__file__).parents[1]/'src/cloud_account.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    class Vault:
        value = ''
        def read(self): return self.value
        def write(self, value): self.value = value
        def clear(self): self.value = ''
    vault = Vault()
    account = module.CloudAccount(tmp_path, vault=vault)
    calls = []
    def request(path, body=None, token=''):
        calls.append((path, token))
        return {'token': 'private-bearer', 'user_id': 'user'} if path.endswith('login') else {'ticket': 'one-use-ticket', 'expires_at': 123, 'user_id': 'user'}
    account.request = request
    assert 'private-bearer' not in str(account.perform('login', {'username': 'user', 'password': 'secret'}))
    resumed = module.CloudAccount(tmp_path, vault=vault)
    resumed.request = request
    assert resumed.perform('status')['authenticated']
    qr = resumed.perform('qr')
    assert 'private-bearer' not in str(qr) and '#login=one-use-ticket' in qr['url']
    assert calls[-1] == ('/auth/qr', 'private-bearer')
    resumed.perform('logout')
    assert not resumed.perform('status')['authenticated']


def test_browser_session_rolling_lifetime_and_cookie_refresh(cloud,monkeypatch):
    from server.core_v2.store import SESSION_TTL
    client,store,auth,parent=cloud
    original=time.time()
    child=store.redeem_qr(store.qr_ticket(parent['token'])['ticket'],'phone')
    monkeypatch.setattr('server.core_v2.store.time.time',lambda:original+40*86400)
    assert store.authenticate(child['token'])['expires']>original+SESSION_TTL
    client.cookies.set('__Secure-shengjian_session',child['token'])
    resumed=client.post(PREFIX+'/auth/session')
    assert resumed.json()['authenticated']
    assert 'Max-Age='+str(SESSION_TTL) in resumed.headers['set-cookie']
    store.revoke(parent['user_id'],child['device_id'])
    assert not client.post(PREFIX+'/auth/session').json()['authenticated']
