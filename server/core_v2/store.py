"""SQLite transactions are the authority for ownership, dispatch and billing."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError

CAPABILITIES = {'tasks', 'screen', 'input', 'files', 'metrics'}
SESSION_TTL = 180*86400

TERMINAL = {'succeeded', 'failed', 'cancelled', 'unknown'}
TRANSITIONS = {
    'queued': {'running', 'failed', 'cancelled', 'unknown'},
    'running': {'awaiting_user', 'succeeded', 'failed', 'cancelled', 'unknown'},
    'awaiting_user': {'running', 'failed', 'cancelled', 'unknown'},
}


class Fault(Exception):
    def __init__(self, code, status=400):
        self.code, self.status = code, status
        super().__init__(code)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


class Store:
    def __init__(self, directory):
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(root, 0o700)
        self.lock = threading.RLock()
        path = root/'core.sqlite3'
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        os.chmod(path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA busy_timeout=5000')
        self.passwords = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
        self.dummy_hash = self.passwords.hash(secrets.token_urlsafe(32))
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
          balance INTEGER NOT NULL DEFAULT 0 CHECK(balance>=0), reserved INTEGER NOT NULL DEFAULT 0 CHECK(reserved>=0));
        CREATE TABLE IF NOT EXISTS invites(code TEXT PRIMARY KEY, expires REAL NOT NULL, remaining INTEGER NOT NULL, credits INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL,
          token TEXT UNIQUE NOT NULL, capabilities TEXT NOT NULL, grants TEXT NOT NULL DEFAULT '[]', revoked INTEGER NOT NULL DEFAULT 0,
          last_seen REAL, metrics TEXT NOT NULL DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), device_id TEXT NOT NULL REFERENCES devices(id),
          request_id TEXT NOT NULL, specification TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued', created REAL NOT NULL,
          dispatched REAL, cancel_requested INTEGER NOT NULL DEFAULT 0, UNIQUE(user_id,request_id));
        CREATE TABLE IF NOT EXISTS events(task_id TEXT NOT NULL REFERENCES tasks(id), seq INTEGER NOT NULL, event_id TEXT NOT NULL,
          body TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY(task_id,seq), UNIQUE(task_id,event_id));
        CREATE TABLE IF NOT EXISTS assistant_preferences(user_id TEXT PRIMARY KEY REFERENCES users(id), chat_model TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS assistant_conversations(id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
          device_id TEXT NOT NULL REFERENCES devices(id), created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS usage(id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), amount INTEGER NOT NULL,
          actual INTEGER, state TEXT NOT NULL, fingerprint TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS grants(id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), amount INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS approvals(id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), status TEXT NOT NULL DEFAULT 'pending', decision TEXT);
        ''')
        for table,column in [('users','unlimited'),('usage','unlimited')]:
            if column not in {r[1] for r in self.db.execute('PRAGMA table_info('+table+')')}:
                self.db.execute('ALTER TABLE '+table+' ADD COLUMN '+column+' INTEGER NOT NULL DEFAULT 0')
        self.db.execute('CREATE TABLE IF NOT EXISTS quota_changes(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),unlimited INTEGER NOT NULL,created REAL NOT NULL)')
        if 'is_work' not in {r[1] for r in self.db.execute('PRAGMA table_info(tasks)')}:
            with self.tx() as db:
                db.execute('ALTER TABLE tasks ADD COLUMN is_work INTEGER NOT NULL DEFAULT 1')
                for row in db.execute('SELECT id,specification FROM tasks').fetchall():
                    if json.loads(row['specification']).get('assistant_chat'):db.execute('UPDATE tasks SET is_work=0 WHERE id=?',(row['id'],))
                for row in db.execute('SELECT task_id,body FROM events').fetchall():
                    if self.work_event(json.loads(row['body'])):db.execute('UPDATE tasks SET is_work=1 WHERE id=?',(row['task_id'],))
        self.db.execute('CREATE INDEX IF NOT EXISTS tasks_owner_created ON tasks(user_id,created DESC)')
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version > 2:
            raise RuntimeError('Database schema is newer than this service')
        if version < 2:
            # Version 1 data stays in place; all changes commit together.
            with self.tx() as db:
                db.execute('ALTER TABLE sessions ADD COLUMN device_id TEXT REFERENCES devices(id)')
                db.execute('CREATE TABLE qr_tickets(ticket TEXT PRIMARY KEY, session_token TEXT NOT NULL REFERENCES sessions(token) ON DELETE CASCADE, expires REAL NOT NULL, consumed REAL)')
                db.execute('CREATE INDEX sessions_device ON sessions(device_id)')
                db.execute('PRAGMA user_version=2')
        # A restart cannot prove whether a dispatched action executed. Never redispatch it.
        with self.tx() as db:
            for row in db.execute("SELECT id FROM tasks WHERE dispatched IS NOT NULL AND state NOT IN ('succeeded','failed','cancelled','unknown')").fetchall():
                db.execute("UPDATE tasks SET state='unknown' WHERE id=?", (row['id'],))
                self._event(db, row['id'], {'type': 'task.state', 'state': 'unknown', 'reason': 'server_restarted'})

    @contextmanager
    def tx(self):
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield self.db
                self.db.execute('COMMIT')
            except BaseException:
                self.db.execute('ROLLBACK')
                raise

    def close(self):
        with self.lock:
            self.db.close()

    def invite(self, credits=0, uses=1, lifetime=86400):
        code = secrets.token_urlsafe(24)
        with self.tx() as db:
            db.execute('INSERT INTO invites VALUES(?,?,?,?)', (digest(code), time.time()+lifetime, uses, credits))
        return code

    def register(self, username, password, invite):
        password_hash = self.passwords.hash(password)
        with self.tx() as db:
            row = db.execute('SELECT * FROM invites WHERE code=?', (digest(invite),)).fetchone()
            if not row or row['remaining'] < 1 or row['expires'] <= time.time():
                raise Fault('invalid_invitation', 403)
            uid = secrets.token_hex(16)
            try:
                db.execute('INSERT INTO users(id,username,password,balance) VALUES(?,?,?,?)', (uid, username.lower(), password_hash, row['credits']))
            except sqlite3.IntegrityError:
                raise Fault('username_unavailable', 409) from None
            db.execute('UPDATE invites SET remaining=remaining-1 WHERE code=?', (digest(invite),))
        return self.session(uid)

    def login(self, username, password):
        with self.lock:
            row = self.db.execute('SELECT * FROM users WHERE username=?', (username.lower(),)).fetchone()
        try:
            valid = self.passwords.verify(row['password'] if row else self.dummy_hash, password)
        except (VerificationError, InvalidHashError):
            valid = False
        if not row or not valid:
            raise Fault('invalid_credentials', 401)
        return self.session(row['id'])

    def session(self, uid):
        token = secrets.token_urlsafe(48)
        expires = time.time()+SESSION_TTL
        with self.tx() as db:
            db.execute('DELETE FROM sessions WHERE expires<=?', (time.time(),))
            db.execute('INSERT INTO sessions(token,user_id,expires) VALUES(?,?,?)', (digest(token), uid, expires))
        return {'token': token, 'user_id': uid, 'expires_at': expires}

    def qr_ticket(self, token):
        ticket = secrets.token_urlsafe(32)
        now = time.time()
        with self.tx() as db:
            if not db.execute('SELECT 1 FROM sessions WHERE token=? AND expires>?', (digest(token), now)).fetchone():
                raise Fault('unauthorized', 401)
            db.execute('DELETE FROM qr_tickets WHERE expires<=? OR session_token=?', (now, digest(token)))
            db.execute('INSERT INTO qr_tickets VALUES(?,?,?,NULL)', (digest(ticket), digest(token), now+120))
        return {'ticket': ticket, 'expires_at': now+120}

    def redeem_qr(self, ticket, name):
        token, ident = secrets.token_urlsafe(48), secrets.token_hex(16)
        now = time.time()
        with self.tx() as db:
            row = db.execute('SELECT s.user_id FROM qr_tickets q JOIN sessions s ON s.token=q.session_token WHERE q.ticket=? AND q.expires>? AND q.consumed IS NULL AND s.expires>?', (digest(ticket), now, now)).fetchone()
            if not row:
                raise Fault('qr_expired', 410)
            uid = row['user_id']
            if db.execute('SELECT COUNT(*) FROM devices WHERE user_id=? AND revoked=0', (uid,)).fetchone()[0] >= 32:
                raise Fault('device_limit', 409)
            # A phone login is a client, never an execution connector.
            db.execute('INSERT INTO devices(id,user_id,name,token,capabilities) VALUES(?,?,?,?,?)', (ident, uid, name, digest(secrets.token_urlsafe(48)), '[]'))
            db.execute('INSERT INTO sessions(token,user_id,expires,device_id) VALUES(?,?,?,?)', (digest(token), uid, now+SESSION_TTL, ident))
            db.execute('UPDATE qr_tickets SET consumed=? WHERE ticket=?', (now, digest(ticket)))
        return {'token': token, 'user_id': uid, 'device_id': ident, 'expires_at': now+SESSION_TTL}

    def authenticate(self, token, device=False):
        with self.lock:
            if device:
                row = self.db.execute('SELECT * FROM devices WHERE token=? AND revoked=0', (digest(token),)).fetchone()
            else:
                now=time.time()
                row = self.db.execute('SELECT user_id,expires FROM sessions WHERE token=? AND expires>?', (digest(token), now)).fetchone()
                if row and row['expires'] < now+SESSION_TTL-86400:
                    self.db.execute('UPDATE sessions SET expires=? WHERE token=?', (now+SESSION_TTL,digest(token)))
                    row={'user_id':row['user_id'],'expires':now+SESSION_TTL}
        if not row:
            raise Fault('unauthorized', 401)
        return dict(row)

    def logout(self, token):
        with self.tx() as db:
            db.execute('DELETE FROM sessions WHERE token=?', (digest(token),))

    def wallet(self, uid):
        with self.lock:
            return dict(self.db.execute('SELECT balance,reserved FROM users WHERE id=?', (uid,)).fetchone())

    def unlimited(self, uid):
        with self.lock:
            row=self.db.execute('SELECT unlimited FROM users WHERE id=?',(uid,)).fetchone()
        if not row:raise Fault('user_not_found',404)
        return bool(row['unlimited'])

    def set_unlimited(self, uid, value, request_id):
        with self.tx() as db:
            old=db.execute('SELECT * FROM quota_changes WHERE id=?',(request_id,)).fetchone()
            if old:
                if old['user_id']!=uid or old['unlimited']!=int(value):raise Fault('idempotency_conflict',409)
                return
            if not db.execute('UPDATE users SET unlimited=? WHERE id=?',(int(value),uid)).rowcount:raise Fault('user_not_found',404)
            db.execute('INSERT INTO quota_changes VALUES(?,?,?,?)',(request_id,uid,int(value),time.time()))

    def credit(self, uid, amount, request_id):
        with self.tx() as db:
            old = db.execute('SELECT * FROM grants WHERE id=?', (request_id,)).fetchone()
            if old:
                if old['user_id'] != uid or old['amount'] != amount:
                    raise Fault('idempotency_conflict', 409)
                return
            if not db.execute('SELECT 1 FROM users WHERE id=?', (uid,)).fetchone():
                raise Fault('user_not_found', 404)
            db.execute('INSERT INTO grants VALUES(?,?,?)', (request_id, uid, amount))
            db.execute('UPDATE users SET balance=balance+? WHERE id=?', (amount, uid))

    def reserve(self, uid, usage_id, amount, fingerprint):
        with self.tx() as db:
            old = db.execute('SELECT * FROM usage WHERE id=?', (usage_id,)).fetchone()
            if old:
                raise Fault('usage_already_submitted' if old['user_id'] == uid and old['fingerprint'] == fingerprint else 'idempotency_conflict', 409)
            unlimited=bool(db.execute('SELECT unlimited FROM users WHERE id=?',(uid,)).fetchone()['unlimited'])
            changed = unlimited or db.execute('UPDATE users SET balance=balance-?,reserved=reserved+? WHERE id=? AND balance>=?', (amount, amount, uid, amount)).rowcount
            if not changed:
                raise Fault('insufficient_credits', 402)
            db.execute('INSERT INTO usage(id,user_id,amount,state,fingerprint,created) VALUES(?,?,?,\'reserved\',?,?)', (usage_id, uid, amount, fingerprint, time.time()))
            if unlimited:db.execute('UPDATE usage SET unlimited=1 WHERE id=?',(usage_id,))

    def settle(self, uid, usage_id, actual):
        with self.tx() as db:
            row = db.execute('SELECT * FROM usage WHERE id=? AND user_id=?', (usage_id, uid)).fetchone()
            if not row:
                raise Fault('usage_not_found', 404)
            if row['state'] == 'settled':
                if row['actual'] != actual:
                    raise Fault('settlement_conflict', 409)
                return
            if not 0 <= actual <= row['amount']:
                raise Fault('usage_requires_reconciliation', 409)
            if not row['unlimited']:
                db.execute('UPDATE users SET reserved=reserved-?,balance=balance+? WHERE id=?', (row['amount'], row['amount']-actual, uid))
            db.execute("UPDATE usage SET actual=?,state='settled' WHERE id=?", (actual, usage_id))

    def usages(self, uid):
        with self.lock:
            return [dict(row) for row in self.db.execute(
                'SELECT id,amount,actual,state,created FROM usage WHERE user_id=? ORDER BY created DESC LIMIT 100', (uid,))]

    def enroll(self, uid, name, capabilities):
        token, ident = secrets.token_urlsafe(48), secrets.token_hex(16)
        with self.tx() as db:
            count = db.execute('SELECT COUNT(*) FROM devices WHERE user_id=? AND revoked=0', (uid,)).fetchone()[0]
            if count >= 32:
                raise Fault('device_limit', 409)
            db.execute('INSERT INTO devices(id,user_id,name,token,capabilities) VALUES(?,?,?,?,?)', (ident, uid, name, digest(token), encode(capabilities)))
        return {'id': ident, 'token': token}

    @staticmethod
    def public_device(row):
        data = {k: row[k] for k in ['id', 'name', 'capabilities', 'grants', 'revoked', 'last_seen', 'metrics']}
        for key in ['capabilities', 'grants', 'metrics']:
            data[key] = json.loads(data[key])
        return data

    def devices(self, uid):
        with self.lock:
            return [self.public_device(r) for r in self.db.execute('SELECT * FROM devices WHERE user_id=?', (uid,))]

    def device(self, uid, ident):
        with self.lock:
            row = self.db.execute('SELECT * FROM devices WHERE id=? AND user_id=?', (ident, uid)).fetchone()
        if not row:
            raise Fault('device_not_found', 404)
        return self.public_device(row)

    def authorize_device(self, uid, ident, grants):
        with self.tx() as db:
            row = db.execute('SELECT * FROM devices WHERE id=? AND user_id=? AND revoked=0', (ident, uid)).fetchone()
            if not row:
                raise Fault('device_not_found', 404)
            if not set(grants) <= set(json.loads(row['capabilities'])):
                raise Fault('unsupported_capability')
            db.execute('UPDATE devices SET grants=? WHERE id=?', (encode(sorted(set(grants))), ident))

    def revoke(self, uid, ident):
        with self.tx() as db:
            if not db.execute('UPDATE devices SET revoked=1,grants=\'[]\' WHERE id=? AND user_id=?', (ident, uid)).rowcount:
                raise Fault('device_not_found', 404)
            db.execute('DELETE FROM sessions WHERE device_id=? AND user_id=?', (ident, uid))
            for row in db.execute("SELECT id FROM tasks WHERE device_id=? AND state IN ('queued','running','awaiting_user')", (ident,)).fetchall():
                db.execute("UPDATE tasks SET state='unknown',cancel_requested=1 WHERE id=?", (row['id'],))
                self._event(db, row['id'], {'type': 'task.state', 'state': 'unknown', 'reason': 'device_revoked'})

    def heartbeat(self, ident, metrics):
        with self.tx() as db:
            if not db.execute('UPDATE devices SET last_seen=?,metrics=? WHERE id=? AND revoked=0', (time.time(), encode(metrics), ident)).rowcount:
                raise Fault('device_revoked', 401)

    @staticmethod
    def work_event(body):
        if body.get('type')=='task.approval':return True
        if body.get('type')!='task.log':return False
        try:log=json.loads(body.get('text',''))
        except (ValueError,TypeError):return False
        return isinstance(log,dict) and log.get('type')=='tool_call' and log.get('tool') not in {
            'see_user_image','media_models','create_image','edit_image','view_conversation_image','image_job_status'}

    def _event(self, db, task_id, body, event_id=None):
        if self.work_event(body):db.execute('UPDATE tasks SET is_work=1 WHERE id=?',(task_id,))
        sequence = db.execute('SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE task_id=?', (task_id,)).fetchone()[0]
        db.execute('INSERT INTO events VALUES(?,?,?,?,?)', (task_id, sequence, event_id or secrets.token_hex(16), encode(body), time.time()))
        return sequence

    def chat_preference(self, uid, model=None):
        with self.tx() as db:
            db.execute('INSERT OR IGNORE INTO assistant_preferences(user_id) VALUES(?)',(uid,))
            if model is not None:db.execute('UPDATE assistant_preferences SET chat_model=? WHERE user_id=?',(model,uid))
            return db.execute('SELECT chat_model FROM assistant_preferences WHERE user_id=?',(uid,)).fetchone()[0]

    def conversation(self, uid, ident, device_id=None):
        with self.tx() as db:
            row = db.execute('SELECT * FROM assistant_conversations WHERE id=?', (ident,)).fetchone()
            if row:
                if row['user_id'] != uid: raise Fault('conversation_not_found', 404)
                if device_id and row['device_id'] != device_id: raise Fault('conversation_device_mismatch', 409)
                return dict(row)
            if not device_id: raise Fault('conversation_not_found', 404)
            self.device(uid, device_id)
            db.execute('INSERT INTO assistant_conversations VALUES(?,?,?,?)', (ident, uid, device_id, time.time()))
            return {'id': ident, 'user_id': uid, 'device_id': device_id}

    def create_task(self, uid, specification):
        with self.tx() as db:
            previous = db.execute('SELECT * FROM tasks WHERE user_id=? AND request_id=?', (uid, specification['request_id'])).fetchone()
            if previous:
                if previous['specification'] != encode(specification):
                    raise Fault('idempotency_conflict', 409)
                return dict(previous)
            device = db.execute('SELECT * FROM devices WHERE id=? AND user_id=? AND revoked=0', (specification['device_id'], uid)).fetchone()
            if not device:
                raise Fault('device_not_found', 404)
            if 'tasks' not in json.loads(device['grants']):
                raise Fault('capability_not_granted', 403)
            active = db.execute("SELECT COUNT(*) FROM tasks WHERE user_id=? AND state IN ('queued','running','awaiting_user')", (uid,)).fetchone()[0]
            if active >= 100:
                raise Fault('active_task_limit', 429)
            task_id = secrets.token_hex(16)
            db.execute('INSERT INTO tasks(id,user_id,device_id,request_id,specification,created) VALUES(?,?,?,?,?,?)', (task_id, uid, device['id'], specification['request_id'], encode(specification), time.time()))
            if specification.get('assistant_chat'):db.execute('UPDATE tasks SET is_work=0 WHERE id=?',(task_id,))
            self._event(db, task_id, {'type': 'task.state', 'state': 'queued'})
            return dict(db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone())

    def task(self, uid, ident):
        with self.lock:
            row = self.db.execute('SELECT * FROM tasks WHERE id=? AND user_id=?', (ident, uid)).fetchone()
        if not row:
            raise Fault('task_not_found', 404)
        return dict(row)

    def tasks(self, uid):
        with self.lock:
            return [dict(r) for r in self.db.execute('SELECT * FROM tasks WHERE user_id=? ORDER BY created DESC LIMIT 100', (uid,))]

    def task_brief(self, uid, ident):
        self.task(uid, ident)
        with self.lock:
            rows = self.db.execute('SELECT body FROM events WHERE task_id=? ORDER BY seq DESC LIMIT 12', (ident,)).fetchall()
            events = [json.loads(row['body']) for row in rows]
            approvals = [row['id'] for row in self.db.execute("SELECT id FROM approvals WHERE task_id=? AND status='pending'", (ident,))]
        return {'result': next((e.get('text', '') for e in events if e['type'] == 'task.result'), ''),
                'latest': next((e.get('text', '') for e in events if e['type'] == 'task.log'), ''), 'approvals': approvals}

    def task_by_request(self, uid, request_id):
        with self.lock:
            row = self.db.execute('SELECT * FROM tasks WHERE user_id=? AND request_id=?', (uid, request_id)).fetchone()
            return dict(row) if row else None

    def events(self, uid, task_id, after):
        self.task(uid, task_id)
        with self.lock:
            return [{'seq': r['seq'], 'created': r['created'], **json.loads(r['body'])} for r in self.db.execute('SELECT * FROM events WHERE task_id=? AND seq>? ORDER BY seq LIMIT 200', (task_id, after))]

    def dispatch(self, ident):
        with self.tx() as db:
            row = db.execute("SELECT * FROM tasks WHERE device_id=? AND state='queued' AND dispatched IS NULL ORDER BY created LIMIT 1", (ident,)).fetchone()
            if not row:
                return None
            expiry = json.loads(row['specification']).get('expires_at')
            if expiry is not None and time.time() > expiry:
                db.execute("UPDATE tasks SET state='failed' WHERE id=?", (row['id'],))
                self._event(db, row['id'], {'type': 'task.log', 'text': '定时任务已过期，没有执行。'})
                self._event(db, row['id'], {'type': 'task.state', 'state': 'failed'})
                return None
            db.execute('UPDATE tasks SET dispatched=? WHERE id=?', (time.time(), row['id']))
            return dict(row)

    def device_event(self, device_id, task_id, body, event_id):
        with self.tx() as db:
            row = db.execute('SELECT * FROM tasks WHERE id=? AND device_id=?', (task_id, device_id)).fetchone()
            if not row or row['dispatched'] is None:
                raise Fault('task_not_found', 404)
            previous = db.execute('SELECT body FROM events WHERE task_id=? AND event_id=?', (task_id, event_id)).fetchone()
            if previous:
                if previous['body'] != encode(body):
                    raise Fault('event_conflict', 409)
                return
            if row['state'] in TERMINAL:
                raise Fault('task_is_terminal', 409)
            if body['type'] == 'task.state':
                state = body['state']
                if state not in TRANSITIONS.get(row['state'], set()):
                    raise Fault('invalid_state_transition', 409)
                if state == 'cancelled' and not row['cancel_requested']:
                    raise Fault('cancellation_not_requested', 409)
                db.execute('UPDATE tasks SET state=? WHERE id=?', (state, task_id))
            if body['type'] == 'task.approval':
                if not body.get('approval_id'):
                    raise Fault('missing_approval_id')
                if db.execute('SELECT 1 FROM approvals WHERE id=?', (body['approval_id'],)).fetchone():
                    raise Fault('approval_id_conflict', 409)
                db.execute('INSERT INTO approvals(id,task_id) VALUES(?,?)', (body['approval_id'], task_id))
                db.execute("UPDATE tasks SET state='awaiting_user' WHERE id=?", (task_id,))
            self._event(db, task_id, body, event_id)

    def cancel(self, uid, task_id):
        with self.tx() as db:
            row = db.execute('SELECT * FROM tasks WHERE id=? AND user_id=?', (task_id, uid)).fetchone()
            if not row:
                raise Fault('task_not_found', 404)
            if row['state'] not in TERMINAL and not row['cancel_requested']:
                db.execute('UPDATE tasks SET cancel_requested=1 WHERE id=?', (task_id,))
                self._event(db, task_id, {'type': 'task.cancel_requested'})
                if row['dispatched'] is None:
                    db.execute("UPDATE tasks SET state='cancelled' WHERE id=?", (task_id,))
                    self._event(db, task_id, {'type': 'task.state', 'state': 'cancelled'})
        return self.task(uid, task_id)

    def approve(self, uid, task_id, approval_id, decision):
        with self.tx() as db:
            task = db.execute('SELECT state FROM tasks WHERE id=? AND user_id=?', (task_id, uid)).fetchone()
            row = db.execute('SELECT * FROM approvals WHERE id=? AND task_id=?', (approval_id, task_id)).fetchone()
            if not task or not row:
                raise Fault('approval_not_found', 404)
            if row['status'] != 'pending':
                if row['decision'] != encode(decision):
                    raise Fault('approval_already_answered', 409)
                return
            if task['state'] != 'awaiting_user':
                raise Fault('approval_no_longer_active', 409)
            db.execute("UPDATE approvals SET status='answered',decision=? WHERE id=?", (encode(decision), approval_id))
            self._event(db, task_id, {'type': 'approval.decision', 'approval_id': approval_id, **decision})

    def decisions(self, device_id):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT a.id,a.task_id,a.decision FROM approvals a JOIN tasks t ON t.id=a.task_id WHERE t.device_id=? AND t.state='awaiting_user' AND a.status='answered'", (device_id,))]

    def pending_cancellations(self, device_id):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT id FROM tasks WHERE device_id=? AND cancel_requested=1 AND state IN ('queued','running','awaiting_user')", (device_id,))]

    def disconnect(self, device_id):
        with self.tx() as db:
            for row in db.execute("SELECT id FROM tasks WHERE device_id=? AND dispatched IS NOT NULL AND state IN ('queued','running','awaiting_user')", (device_id,)).fetchall():
                db.execute("UPDATE tasks SET state='unknown' WHERE id=?", (row['id'],))
                self._event(db, row['id'], {'type': 'task.state', 'state': 'unknown', 'reason': 'device_disconnected'})
