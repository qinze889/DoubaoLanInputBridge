"""Bounded voice transport diagnostics. Never accepts audio or dialogue content."""
import time
from fastapi import Depends
from pydantic import Field
from .store import Fault

def mount(app,store,user):
    from .app import Input,PREFIX
    with store.lock:
        store.db.execute('CREATE TABLE IF NOT EXISTS voice_client_events(uid TEXT NOT NULL,stage TEXT NOT NULL,code TEXT NOT NULL,mode TEXT NOT NULL,created REAL NOT NULL)')
        store.db.execute('CREATE INDEX IF NOT EXISTS voice_client_events_owner_time ON voice_client_events(uid,created)')
        store.db.execute('CREATE INDEX IF NOT EXISTS voice_client_events_time ON voice_client_events(created)')
    class Event(Input):
        stage:str=Field(pattern=r'^(?:capture|asr|reply|playback|dictation)$')
        code:str=Field(pattern=r'^[a-z][a-z0-9_]{2,80}$')
        mode:str=Field(pattern=r'^(?:live|hold|text|dictation)$')
    @app.post(PREFIX+'/voice/client-events')
    async def event(body:Event,uid=Depends(user)):
        now=time.time()
        with store.tx() as db:
            db.execute('DELETE FROM voice_client_events WHERE created<?',(now-7*86400,))
            if db.execute('SELECT COUNT(*) FROM voice_client_events WHERE uid=? AND created>?',(uid,now-60)).fetchone()[0]>=12:raise Fault('rate_limited',429)
            db.execute('INSERT INTO voice_client_events VALUES(?,?,?,?,?)',(uid,body.stage,body.code,body.mode,now))
            db.execute('DELETE FROM voice_client_events WHERE uid=? AND rowid NOT IN (SELECT rowid FROM voice_client_events WHERE uid=? ORDER BY created DESC LIMIT 500)',(uid,uid))
        return {'ok':True}
