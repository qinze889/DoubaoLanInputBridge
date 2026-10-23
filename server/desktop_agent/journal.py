"""A task identity is durably claimed before the first engine operation."""
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid


class Journal:
    def __init__(self, root):
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = root / 'agent.sqlite3'
        self.db = sqlite3.connect(path, isolation_level=None)
        os.chmod(path, 0o600)
        self.db.executescript('''PRAGMA journal_mode=WAL;
          CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, specification TEXT NOT NULL, state TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, task_id TEXT NOT NULL, body TEXT NOT NULL, acknowledged INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
          UPDATE tasks SET state='unknown' WHERE state IN ('received','running','awaiting_user');''')

    def claim(self, task):
        cursor = self.db.execute("INSERT OR IGNORE INTO tasks VALUES(?,?,'received')",
                                 (task['task_id'], json.dumps(task, sort_keys=True)))
        return bool(cursor.rowcount)

    def state(self, ident, state):
        self.db.execute('UPDATE tasks SET state=? WHERE id=?', (state, ident))

    def event(self, ident, body):
        event_id = uuid.uuid4().hex
        self.db.execute('INSERT INTO events(id,task_id,body,created) VALUES(?,?,?,?)',
                        (event_id, ident, json.dumps(body, ensure_ascii=False), time.time()))
        return {'type': 'task.event', 'task_id': ident, 'event_id': event_id, 'event': body}

    def acknowledge(self, ident):
        self.db.execute('UPDATE events SET acknowledged=1 WHERE id=?', (ident,))

    def close(self):
        self.db.close()
