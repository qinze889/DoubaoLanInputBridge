"""Private life timeline, attachments, revision-bound consolidation and sourced memory."""
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from zoneinfo import ZoneInfo

from .store import Fault, encode


class LifeStore:
    def __init__(self, directory):
        self.root = Path(directory)/'life'
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.files = self.root/'images'; self.files.mkdir(exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.root/'life.sqlite3', isolation_level=None, check_same_thread=False)
        os.chmod(self.root/'life.sqlite3', 0o600)
        self.db.row_factory = sqlite3.Row
        if self.db.execute('PRAGMA user_version').fetchone()[0] > 1: raise RuntimeError('Life database requires newer service')
        self.db.executescript('''PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000;
          CREATE TABLE IF NOT EXISTS preferences(uid TEXT PRIMARY KEY, auto INTEGER DEFAULT 1, capture INTEGER DEFAULT 1, clock TEXT DEFAULT '23:00', timezone TEXT DEFAULT 'Asia/Shanghai');
          CREATE TABLE IF NOT EXISTS images(id TEXT PRIMARY KEY,uid TEXT NOT NULL,size INTEGER NOT NULL,width INTEGER,height INTEGER,caption TEXT DEFAULT '',created REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS entries(id TEXT PRIMARY KEY,uid TEXT NOT NULL,request_id TEXT NOT NULL,kind TEXT NOT NULL,role TEXT NOT NULL,text TEXT NOT NULL,images TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,deleted INTEGER DEFAULT 0,UNIQUE(uid,request_id));
          CREATE INDEX IF NOT EXISTS entries_owner_date ON entries(uid,created);
          CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,uid TEXT NOT NULL,day TEXT NOT NULL,revision TEXT NOT NULL,state TEXT NOT NULL,summary TEXT DEFAULT '',error TEXT DEFAULT '',created REAL NOT NULL,updated REAL NOT NULL,UNIQUE(uid,day,revision));
          CREATE TABLE IF NOT EXISTS memories(id TEXT PRIMARY KEY,uid TEXT NOT NULL,key TEXT NOT NULL,text TEXT NOT NULL,kind TEXT NOT NULL,day TEXT NOT NULL,sources TEXT NOT NULL,manual INTEGER DEFAULT 0,deleted INTEGER DEFAULT 0,updated REAL NOT NULL,UNIQUE(uid,key));
          CREATE TABLE IF NOT EXISTS memory_history(id TEXT NOT NULL,version TEXT NOT NULL,text TEXT NOT NULL,created REAL NOT NULL);
          PRAGMA user_version=1;''')
        if 'request_id' not in {r[1] for r in self.db.execute('PRAGMA table_info(images)')}:
            self.db.execute('ALTER TABLE images ADD COLUMN request_id TEXT')
        self.db.execute('CREATE UNIQUE INDEX IF NOT EXISTS image_request ON images(uid,request_id)')
        for table,column,definition in [('preferences','vision_model',"TEXT DEFAULT ''"),('jobs','vision_model',"TEXT DEFAULT ''"),('images','caption_model',"TEXT DEFAULT ''")]:
            if column not in {r[1] for r in self.db.execute('PRAGMA table_info('+table+')')}:
                self.db.execute('ALTER TABLE '+table+' ADD COLUMN '+column+' '+definition)
        self.db.execute('CREATE TABLE IF NOT EXISTS image_captions(image_id TEXT REFERENCES images(id) ON DELETE CASCADE,model TEXT NOT NULL,text TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(image_id,model))')
        # An interrupted model request may already have been billed; never replay it automatically.
        self.db.execute("UPDATE jobs SET state='unknown',error='service_restarted',updated=? WHERE state='running'", (time.time(),))

    @contextmanager
    def tx(self):
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try: yield self.db; self.db.execute('COMMIT')
            except BaseException: self.db.execute('ROLLBACK'); raise

    def close(self):
        with self.lock: self.db.close()

    def preferences(self, uid, values=None):
        if values is None:
            with self.lock:
                row=self.db.execute('SELECT * FROM preferences WHERE uid=?',(uid,)).fetchone()
                if row: return dict(row)
        with self.tx() as db:
            db.execute('INSERT OR IGNORE INTO preferences(uid) VALUES(?)', (uid,))
            if values is not None:
                if set(values)-{'auto','capture','clock','timezone','vision_model'}: raise Fault('invalid_life_settings')
                if 'vision_model' in values and (not isinstance(values['vision_model'],str) or len(values['vision_model'])>256):raise Fault('invalid_vision_model')
                if any(k in values and type(values[k]) is not bool for k in ('auto','capture')): raise Fault('invalid_life_settings')
                if 'clock' in values and (not isinstance(values['clock'],str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', values['clock'])): raise Fault('invalid_life_time')
                if 'timezone' in values:
                    try: ZoneInfo(values['timezone'])
                    except (ValueError,KeyError,TypeError): raise Fault('invalid_timezone') from None
                for key,value in values.items(): db.execute(f'UPDATE preferences SET {key}=? WHERE uid=?', (value,uid))
            return dict(db.execute('SELECT * FROM preferences WHERE uid=?',(uid,)).fetchone())

    def image(self, uid, ident):
        with self.lock: row=self.db.execute('SELECT * FROM images WHERE id=? AND uid=?',(ident,uid)).fetchone()
        if not row: raise Fault('image_not_found',404)
        return dict(row)

    def caption(self, uid, ident, model, text=None):
        self.image(uid,ident)
        if text is None:
            with self.lock:row=self.db.execute('SELECT text FROM image_captions WHERE image_id=? AND model=?',(ident,model)).fetchone()
            return row['text'] if row else ''
        with self.tx() as db:
            # The source may have been removed during the model request.
            if not db.execute('SELECT 1 FROM images WHERE id=? AND uid=?',(ident,uid)).fetchone():raise Fault('image_not_found',404)
            db.execute('INSERT INTO image_captions VALUES(?,?,?,?) ON CONFLICT(image_id,model) DO UPDATE SET text=excluded.text,created=excluded.created',(ident,model,text,time.time()))
            db.execute('UPDATE images SET caption=?,caption_model=? WHERE id=? AND uid=?',(text,model,ident,uid))

    def add_image(self, uid, raw, width, height, request_id):
        with self.tx() as db:
            previous=db.execute('SELECT * FROM images WHERE uid=? AND request_id=?',(uid,request_id)).fetchone()
            if previous:
                if (self.files/(previous['id']+'.jpg')).read_bytes()!=raw:raise Fault('idempotency_conflict',409)
                return dict(previous)
            size=db.execute('SELECT COALESCE(SUM(size),0) FROM images WHERE uid=?',(uid,)).fetchone()[0]
            if size+len(raw)>200*1024*1024: raise Fault('life_storage_full',413)
            ident=secrets.token_hex(16); path=self.files/(ident+'.jpg')
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            try:
                with os.fdopen(fd,'wb') as stream: stream.write(raw)
                db.execute('INSERT INTO images(id,uid,size,width,height,created,request_id) VALUES(?,?,?,?,?,?,?)',(ident,uid,len(raw),width,height,time.time(),request_id))
            except BaseException: path.unlink(missing_ok=True); raise
        return self.image(uid,ident)

    def record(self, uid, values):
        self.preferences(uid)
        images=values.get('images',[])
        for ident in images: self.image(uid,ident)
        now=time.time(); stamp=values.get('created',now)
        # Client timestamps may be slightly behind during offline capture, but not arbitrary future days.
        if not now-30*86400<=stamp<=now+300: raise Fault('invalid_record_time')
        with self.tx() as db:
            old=db.execute('SELECT * FROM entries WHERE uid=? AND request_id=?',(uid,values['request_id'])).fetchone()
            if old:
                if old['kind']!=values['kind'] or old['role']!=values['role'] or old['text']!=values['text'] or old['images']!=encode(images): raise Fault('idempotency_conflict',409)
                return dict(old)
            if not values['text'].strip() and not images: raise Fault('empty_life_record')
            if db.execute('SELECT COUNT(*) FROM entries WHERE uid=? AND deleted=0',(uid,)).fetchone()[0]>=50000: raise Fault('life_record_limit',429)
            ident=secrets.token_hex(16)
            db.execute('INSERT INTO entries(id,uid,request_id,kind,role,text,images,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',(ident,uid,values['request_id'],values['kind'],values['role'],values['text'],encode(images),stamp,now))
            return dict(db.execute('SELECT * FROM entries WHERE id=?',(ident,)).fetchone())

    def entries(self, uid, before=None, search='', before_id='ffffffffffffffffffffffffffffffff', caption_model=None):
        with self.lock:
            stamp=before if before is not None else time.time()+301
            rows=self.db.execute('SELECT * FROM entries WHERE uid=? AND deleted=0 AND (created<? OR (created=? AND id<?)) AND text LIKE ? ORDER BY created DESC,id DESC LIMIT 50',(uid,stamp,stamp,before_id,'%'+search+'%')).fetchall()
            return [self.describe_entry(uid,row,caption_model) for row in rows]

    def describe_entry(self, uid, row, caption_model=None):
        images=json.loads(row['images']);captions=[];models=[]
        for ident in images:
            image=self.image(uid,ident)
            caption=self.caption(uid,ident,caption_model) if caption_model else image['caption']
            if caption:captions.append(caption);models.append(caption_model or image['caption_model'])
        return {**dict(row),'images':images,'photo_descriptions':captions,'photo_description_models':models}

    def entry(self, uid, ident, caption_model=None):
        with self.lock:row=self.db.execute('SELECT * FROM entries WHERE uid=? AND id=? AND deleted=0',(uid,ident)).fetchone()
        if not row:raise Fault('life_record_not_found',404)
        return self.describe_entry(uid,row,caption_model)

    def delete_entry(self, uid, ident):
        with self.tx() as db:
            row=db.execute('SELECT * FROM entries WHERE id=? AND uid=? AND deleted=0',(ident,uid)).fetchone()
            if not row: raise Fault('life_record_not_found',404)
            db.execute("UPDATE entries SET deleted=1,text='',images='[]',updated=? WHERE id=?",(time.time(),ident))
            for memory in db.execute('SELECT id,sources FROM memories WHERE uid=? AND deleted=0',(uid,)).fetchall():
                if ident in json.loads(memory['sources']):
                    db.execute("UPDATE memories SET deleted=1,text='',updated=? WHERE id=?",(time.time(),memory['id']))
                    db.execute('DELETE FROM memory_history WHERE id=?',(memory['id'],))
            # Older summaries could contain removed material; invalidate all derived summaries for this owner.
            db.execute("UPDATE jobs SET state='obsolete',summary='' WHERE uid=? AND state='succeeded'",(uid,))
            for image in json.loads(row['images']):
                used=any(image in json.loads(r[0]) for r in db.execute('SELECT images FROM entries WHERE uid=? AND deleted=0',(uid,)))
                if not used:
                    db.execute('DELETE FROM images WHERE id=? AND uid=?',(image,uid))
                    (self.files/(image+'.jpg')).unlink(missing_ok=True)

    def day(self, uid, day):
        preferences=self.preferences(uid); zone=ZoneInfo(preferences['timezone'])
        try:
            date=datetime.strptime(day,'%Y-%m-%d').replace(tzinfo=zone)
            from datetime import timedelta
            start,end=date.timestamp(),(date+timedelta(days=1)).timestamp()
        except ValueError: raise Fault('invalid_day') from None
        with self.lock:
            rows=[dict(r) for r in self.db.execute('SELECT * FROM entries WHERE uid=? AND deleted=0 AND created>=? AND created<? ORDER BY created,id',(uid,start,end))]
        if len(rows)>500 or sum(len(r['text']) for r in rows)>200000: raise Fault('life_day_too_large',413)
        revision=hashlib.sha256(encode([(r['id'],r['updated']) for r in rows]).encode()).hexdigest()
        return rows,revision

    @staticmethod
    def model_revision(revision, model):
        return hashlib.sha256(encode([revision,model]).encode()).hexdigest() if model else revision

    def claim(self, uid, day, force=False, vision_model=''):
        rows,revision=self.day(uid,day)
        revision=self.model_revision(revision,vision_model)
        if not rows: raise Fault('no_life_records')
        with self.tx() as db:
            previous=db.execute('SELECT * FROM jobs WHERE uid=? AND day=? AND revision=?',(uid,day,revision)).fetchone()
            if previous:
                if not force or previous['state']=='running':return dict(previous),False,rows
                db.execute('DELETE FROM jobs WHERE id=?',(previous['id'],))
            if db.execute("SELECT 1 FROM jobs WHERE uid=? AND state='running'",(uid,)).fetchone(): raise Fault('life_consolidation_busy',409)
            ident=secrets.token_hex(16); now=time.time()
            db.execute("INSERT INTO jobs(id,uid,day,revision,state,created,updated,vision_model) VALUES(?,?,?,?,'running',?,?,?)",(ident,uid,day,revision,now,now,vision_model))
            return dict(db.execute('SELECT * FROM jobs WHERE id=?',(ident,)).fetchone()),True,rows

    def recorded_version(self, uid, day):
        _,revision=self.day(uid,day)
        with self.lock:
            for row in self.db.execute('SELECT * FROM jobs WHERE uid=? AND day=? ORDER BY created DESC',(uid,day)):
                if self.model_revision(revision,row['vision_model'])==row['revision']:return dict(row)
        return None

    def memories(self, uid, deleted=False):
        with self.lock:
            return [{**dict(r),'sources':json.loads(r['sources'])} for r in self.db.execute('SELECT * FROM memories WHERE uid=?'+('' if deleted else ' AND deleted=0')+' ORDER BY updated DESC LIMIT 500',(uid,))]

    def edit_memory(self, uid, ident, text=None):
        with self.tx() as db:
            row=db.execute('SELECT * FROM memories WHERE uid=? AND id=? AND deleted=0',(uid,ident)).fetchone()
            if not row: raise Fault('life_memory_not_found',404)
            if text is not None and (not isinstance(text,str) or not 1<=len(text.strip())<=1000):raise Fault('invalid_memory_text')
            if text is None:
                db.execute("UPDATE memories SET deleted=1,text='',updated=? WHERE id=?",(time.time(),ident));db.execute('DELETE FROM memory_history WHERE id=?',(ident,))
            else:
                db.execute('INSERT INTO memory_history VALUES(?,?,?,?)',(ident,secrets.token_hex(16),row['text'],time.time()))
                db.execute('UPDATE memories SET text=?,manual=1,updated=? WHERE id=?',(text,time.time(),ident))

    def finish(self, job, output):
        rows,revision=self.day(job['uid'],job['day'])
        revision=self.model_revision(revision,job.get('vision_model',''))
        valid={r['id'] for r in rows if r['role']=='user'}; candidates=output.get('memories')
        if not isinstance(output.get('summary'),str) or len(output['summary'])>6000 or not isinstance(candidates,list) or len(candidates)>20: raise Fault('invalid_memory_output',502)
        for value in candidates:
            if not isinstance(value,dict) or not isinstance(value.get('key'),str) or not 1<=len(value['key'])<=100 or not isinstance(value.get('text'),str) or not 1<=len(value['text'])<=1000 or value.get('kind') not in {'event','fact','preference'} or not isinstance(value.get('sources'),list) or not value['sources'] or any(not isinstance(s,str) or s not in valid for s in value['sources']): raise Fault('invalid_memory_sources',502)
            if re.search(r'(?i)(password|api[_ -]?key|access[_ -]?token|cookie|私钥|密码|密钥)',value['text']): raise Fault('sensitive_memory_rejected',502)
        with self.tx() as db:
            # Recompute under the write lock too, so deletion cannot race memory publication.
            _,current=self.day(job['uid'],job['day'])
            current=self.model_revision(current,job.get('vision_model',''))
            if revision!=job['revision'] or current!=revision:
                db.execute("UPDATE jobs SET state='obsolete',summary='',updated=? WHERE id=?",(time.time(),job['id']));return
            for value in candidates:
                old=db.execute('SELECT * FROM memories WHERE uid=? AND key=?',(job['uid'],value['key'])).fetchone()
                if old and (old['manual'] or old['deleted']): continue
                if not old and db.execute('SELECT COUNT(*) FROM memories WHERE uid=? AND deleted=0',(job['uid'],)).fetchone()[0]>=500:raise Fault('life_memory_limit',429)
                ident=old['id'] if old else secrets.token_hex(16)
                if old: db.execute('INSERT INTO memory_history VALUES(?,?,?,?)',(ident,secrets.token_hex(16),old['text'],time.time()))
                db.execute('INSERT INTO memories(id,uid,key,text,kind,day,sources,updated) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(uid,key) DO UPDATE SET text=excluded.text,kind=excluded.kind,day=excluded.day,sources=excluded.sources,updated=excluded.updated',(ident,job['uid'],value['key'],value['text'],value['kind'],job['day'],encode(value['sources']),time.time()))
            db.execute("UPDATE jobs SET state='succeeded',summary=?,updated=? WHERE id=?",(output['summary'],time.time(),job['id']))

    def jobs(self, uid):
        with self.lock: return [dict(r) for r in self.db.execute('SELECT * FROM jobs WHERE uid=? ORDER BY created DESC LIMIT 30',(uid,))]

    def fail(self, ident, code, state='failed'):
        with self.tx() as db: db.execute('UPDATE jobs SET state=?,error=?,updated=? WHERE id=?',(state,code,time.time(),ident))
