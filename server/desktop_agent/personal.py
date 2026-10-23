"""Device-local memory, schedules and run claims. Never copy this database to cloud."""
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class PersonalStore:
    def __init__(self, directory, scope):
        root = Path(directory); root.mkdir(mode=0o700, parents=True, exist_ok=True); os.chmod(root, 0o700)
        self.scope = scope
        self.lock = threading.RLock()
        self.db = sqlite3.connect(root/'personal.sqlite3', isolation_level=None, check_same_thread=False)
        os.chmod(root/'personal.sqlite3', 0o600)
        self.db.row_factory = sqlite3.Row
        if self.db.execute('PRAGMA user_version').fetchone()[0] > 1:
            self.db.close()
            raise ValueError('personal_database_requires_newer_app')
        self.db.executescript('''PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;
          CREATE TABLE IF NOT EXISTS memories(id TEXT PRIMARY KEY, scope TEXT NOT NULL, text TEXT NOT NULL, fingerprint TEXT NOT NULL, created REAL NOT NULL, deleted INTEGER DEFAULT 0, UNIQUE(scope,fingerprint));
          CREATE TABLE IF NOT EXISTS settings(scope TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(scope,key));
          CREATE TABLE IF NOT EXISTS life_memories(scope TEXT NOT NULL,id TEXT NOT NULL,text TEXT NOT NULL,day TEXT NOT NULL,sources TEXT NOT NULL,synced REAL NOT NULL,PRIMARY KEY(scope,id));
          CREATE TABLE IF NOT EXISTS schedules(id TEXT PRIMARY KEY, scope TEXT NOT NULL, title TEXT NOT NULL, prompt TEXT NOT NULL, kind TEXT NOT NULL, local_time TEXT, timezone TEXT NOT NULL, at REAL, enabled INTEGER NOT NULL, deleted INTEGER DEFAULT 0, created REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS schedule_runs(schedule_id TEXT NOT NULL, slot TEXT NOT NULL, state TEXT NOT NULL, task_id TEXT, created REAL NOT NULL, PRIMARY KEY(schedule_id,slot));
          PRAGMA user_version=1;''')

    def __enter__(self): return self
    def __exit__(self, *args): self.close()
    def close(self):
        with self.lock: self.db.close()

    @contextmanager
    def tx(self):
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield self.db
                self.db.execute('COMMIT')
            except BaseException:
                self.db.execute('ROLLBACK'); raise

    def settings(self):
        result = {'desktop_enabled': False, 'browser_enabled': True, 'memory_context': True, 'applications': ['com.apple.calculator', 'com.apple.TextEdit', 'com.apple.Safari']}
        with self.lock:
            for row in self.db.execute('SELECT key,value FROM settings WHERE scope=?', (self.scope,)):
                result[row['key']] = json.loads(row['value'])
        return result

    def configure(self, values):
        if set(values)-{'desktop_enabled', 'browser_enabled', 'memory_context', 'applications'}: raise ValueError('unknown_setting')
        for key in ['desktop_enabled', 'browser_enabled', 'memory_context']:
            if key in values and type(values[key]) is not bool: raise ValueError('invalid_setting')
        if 'applications' in values and (not isinstance(values['applications'], list) or not 1 <= len(values['applications']) <= 20 or any(not isinstance(v, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{3,160}', v) for v in values['applications'])): raise ValueError('invalid_application_scope')
        with self.tx() as db:
            for key, value in values.items(): db.execute('INSERT INTO settings VALUES(?,?,?) ON CONFLICT(scope,key) DO UPDATE SET value=excluded.value', (self.scope, key, json.dumps(value)))
        return self.settings()

    def memories(self, include_deleted=False):
        with self.lock:
            return [dict(row) for row in self.db.execute('SELECT id,text,created,deleted FROM memories WHERE scope=?'+('' if include_deleted else ' AND deleted=0')+' ORDER BY created DESC LIMIT 100', (self.scope,))]

    def remember(self, text):
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 2000: raise ValueError('invalid_memory')
        text = text.strip()
        if re.search(r'(?i)(password|api[_ -]?key|access[_ -]?token|cookie|私钥|密码|密钥)', text): raise ValueError('credentials_belong_in_keychain')
        fingerprint = hashlib.sha256(text.encode()).hexdigest()
        with self.tx() as db:
            old = db.execute('SELECT id FROM memories WHERE scope=? AND fingerprint=?', (self.scope, fingerprint)).fetchone()
            if old:
                db.execute('UPDATE memories SET deleted=0 WHERE id=?', (old['id'],)); return old['id']
            if db.execute('SELECT count(*) FROM memories WHERE scope=? AND deleted=0', (self.scope,)).fetchone()[0] >= 100: raise ValueError('memory_limit')
            ident = secrets.token_hex(16)
            db.execute('INSERT INTO memories(id,scope,text,fingerprint,created) VALUES(?,?,?,?,?)', (ident, self.scope, text, fingerprint, time.time()))
            return ident

    def delete_memory(self, ident, restore=False):
        with self.tx() as db:
            if not db.execute('UPDATE memories SET deleted=? WHERE id=? AND scope=?', (0 if restore else 1, ident, self.scope)).rowcount: raise ValueError('memory_not_found')

    def context(self, prompt):
        if not self.settings()['memory_context']: return ''
        rows = self.memories() + self.life_memories()
        terms = set(re.findall(r'[A-Za-z]{3,}|[\u4e00-\u9fff]{2}', prompt))
        rows.sort(key=lambda r: sum(term in r['text'] for term in terms), reverse=True)
        return '\n'.join('- '+r['text'] for r in rows[:12])[:4000]

    def life_memories(self):
        with self.lock:
            return [dict(r) for r in self.db.execute('SELECT id,text,day,sources,synced FROM life_memories WHERE scope=? ORDER BY day DESC,id', (self.scope,))]

    def sync_life(self, rows):
        # Full snapshot: deletions on the server also retract local context.
        if not isinstance(rows,list) or len(rows)>500:raise ValueError('invalid_life_snapshot')
        for row in rows:
            if not isinstance(row,dict) or any(not isinstance(row.get(k),str) for k in ('id','text','day')) or not 1<=len(row['text'])<=1000 or not isinstance(row.get('sources'),list):raise ValueError('invalid_life_snapshot')
        with self.tx() as db:
            db.execute('DELETE FROM life_memories WHERE scope=?',(self.scope,))
            for row in rows:db.execute('INSERT INTO life_memories VALUES(?,?,?,?,?,?)',(self.scope,row['id'],row['text'],row['day'],json.dumps(row['sources']),time.time()))
            db.execute("INSERT INTO settings VALUES(?,'life_synced_at',?) ON CONFLICT(scope,key) DO UPDATE SET value=excluded.value",(self.scope,json.dumps(time.time())))

    def schedules(self):
        with self.lock:
            return [dict(row) for row in self.db.execute('SELECT * FROM schedules WHERE scope=? AND deleted=0 ORDER BY created DESC', (self.scope,))]

    def schedule(self, values, now=None):
        now = time.time() if now is None else now
        if set(values)-{'title','prompt','kind','local_time','timezone','at','enabled'}: raise ValueError('unknown_schedule_field')
        if not isinstance(values.get('title'), str) or not isinstance(values.get('prompt'), str): raise ValueError('invalid_schedule')
        title, prompt = values['title'].strip(), values['prompt'].strip()
        kind, zone = values.get('kind'), values.get('timezone', 'Asia/Shanghai')
        if not 1 <= len(title) <= 80 or not 1 <= len(prompt) <= 16000 or kind not in {'daily','once'}: raise ValueError('invalid_schedule')
        try: ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError, TypeError): raise ValueError('invalid_timezone') from None
        local_time, at = values.get('local_time'), values.get('at')
        if kind == 'daily' and (not isinstance(local_time, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', local_time)): raise ValueError('invalid_local_time')
        if kind == 'once' and (type(at) not in (int,float) or not math.isfinite(at) or at <= now): raise ValueError('schedule_time_must_be_future')
        enabled = values.get('enabled', False)
        if type(enabled) is not bool: raise ValueError('invalid_schedule_state')
        with self.tx() as db:
            if db.execute('SELECT count(*) FROM schedules WHERE scope=? AND deleted=0', (self.scope,)).fetchone()[0] >= 50: raise ValueError('schedule_limit')
            ident = secrets.token_hex(16)
            db.execute('INSERT INTO schedules(id,scope,title,prompt,kind,local_time,timezone,at,enabled,created) VALUES(?,?,?,?,?,?,?,?,?,?)', (ident,self.scope,title,prompt,kind,local_time,zone,at,int(enabled),now))
        return ident

    def change_schedule(self, ident, enabled=False, deleted=False):
        if type(enabled) is not bool or type(deleted) is not bool: raise ValueError('invalid_schedule_state')
        with self.tx() as db:
            if not db.execute('UPDATE schedules SET enabled=?,deleted=? WHERE id=? AND scope=?', (int(enabled),int(deleted),ident,self.scope)).rowcount: raise ValueError('schedule_not_found')

    def claim_due(self, now=None):
        now = time.time() if now is None else now
        due = []
        with self.tx() as db:
            for row in db.execute('SELECT * FROM schedules WHERE scope=? AND enabled=1 AND deleted=0', (self.scope,)).fetchall():
                valid = True
                if row['kind'] == 'once': target, slot = row['at'], 'once'
                else:
                    zone = ZoneInfo(row['timezone']); date = datetime.fromtimestamp(now, zone)
                    hour, minute = map(int, row['local_time'].split(':'))
                    local = date.replace(hour=hour, minute=minute, second=0, microsecond=0, fold=0)
                    target, slot = local.timestamp(), date.date().isoformat()
                    check = datetime.fromtimestamp(target, zone)
                    valid = check.hour == hour and check.minute == minute
                if now < target: continue
                state = 'claimed' if valid and now-target <= 60 else 'missed'
                inserted = db.execute('INSERT OR IGNORE INTO schedule_runs(schedule_id,slot,state,created) VALUES(?,?,?,?)', (row['id'],slot,state,now)).rowcount
                if inserted and state == 'claimed': due.append({**dict(row), 'slot':slot, 'request_id':'schedule-'+row['id']+'-'+slot})
        return due

    def finish_run(self, ident, slot, state, task_id=None):
        if state not in {'submitted','unknown','failed','missed'}: raise ValueError('invalid_run_state')
        with self.tx() as db:
            db.execute('UPDATE schedule_runs SET state=?,task_id=? WHERE schedule_id=? AND slot=? AND schedule_id IN (SELECT id FROM schedules WHERE scope=?)', (state,task_id,ident,slot,self.scope))
            db.execute("UPDATE schedules SET enabled=0 WHERE id=? AND scope=? AND kind='once'", (ident,self.scope))

    def recover_runs(self):
        with self.tx() as db: db.execute("UPDATE schedule_runs SET state='unknown' WHERE state='claimed' AND schedule_id IN (SELECT id FROM schedules WHERE scope=?)", (self.scope,))

    def runs(self):
        with self.lock:
            return [dict(row) for row in self.db.execute('SELECT r.*,s.title FROM schedule_runs r JOIN schedules s ON s.id=r.schedule_id WHERE s.scope=? ORDER BY r.created DESC LIMIT 100', (self.scope,))]
