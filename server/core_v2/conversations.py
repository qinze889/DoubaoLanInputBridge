"""Owned conversation views over durable tasks; history reads never execute work."""
import json
import secrets
import time
from fastapi import Depends,Query
from pydantic import Field
from .store import Fault,TERMINAL,encode


def mount(app,store,user):
    from .app import PREFIX,Input
    with store.lock:
        store.db.execute("CREATE TABLE IF NOT EXISTS conversation_views(cid TEXT PRIMARY KEY REFERENCES assistant_conversations(id),title TEXT NOT NULL DEFAULT '',archived INTEGER NOT NULL DEFAULT 0)")
        store.db.execute("CREATE TABLE IF NOT EXISTS conversation_controls(id TEXT PRIMARY KEY,uid TEXT NOT NULL REFERENCES users(id),cid TEXT NOT NULL REFERENCES assistant_conversations(id),request_id TEXT NOT NULL,user_text TEXT NOT NULL,reply TEXT NOT NULL,created REAL NOT NULL,response TEXT NOT NULL DEFAULT '{}',request_body TEXT NOT NULL DEFAULT '{}',UNIQUE(uid,request_id))")
        store.db.execute('CREATE INDEX IF NOT EXISTS conversation_controls_owner ON conversation_controls(uid,cid,created DESC,id DESC)')
        store.db.execute("CREATE INDEX IF NOT EXISTS tasks_conversation ON tasks(user_id,json_extract(specification,'$.conversation_id'),created DESC,id DESC)")
    class Edit(Input):
        title:str|None=Field(default=None,min_length=1,max_length=100)
        archived:bool|None=None

    def meta(uid,cid):
        # This lookup checks ownership without creating a missing conversation.
        row=store.conversation(uid,cid)
        with store.lock:
            view=store.db.execute('SELECT title,archived FROM conversation_views WHERE cid=?',(cid,)).fetchone()
            device=store.db.execute('SELECT name FROM devices WHERE id=? AND user_id=?',(row['device_id'],uid)).fetchone()
        title=view['title'] if view else ''
        if not title:
            with store.lock:
                first=store.db.execute("""SELECT content FROM (
                    SELECT id,created,COALESCE(json_extract(specification,'$.voice_text'),json_extract(specification,'$.prompt')) content FROM tasks WHERE user_id=? AND json_extract(specification,'$.conversation_id')=?
                    UNION ALL SELECT id,created,user_text content FROM conversation_controls WHERE uid=? AND cid=?) ORDER BY created,id LIMIT 1""",(uid,cid,uid,cid)).fetchone()
            title=str(first['content'])[:60] if first else ''
        return {'id':cid,'device_id':row['device_id'],'device_name':device['name'] if device else '电脑','title':title, 'archived':bool(view and view['archived'])}

    def tasks(uid,cid,before=None,limit=50):
        query="SELECT * FROM tasks WHERE user_id=? AND json_extract(specification,'$.conversation_id')=?";args=[uid,cid]
        with store.lock:
            if before:
                cursor=store.db.execute(query+' AND id=?',(*args,before)).fetchone()
                if not cursor:raise Fault('conversation_cursor_not_found',404)
                query+=' AND (created<? OR (created=? AND id<?))';args.extend([cursor['created'],cursor['created'],before])
            return store.db.execute(query+' ORDER BY created DESC,id DESC LIMIT ?',(*args,limit)).fetchall()

    def previous_control(uid,body):
        with store.lock:old=store.db.execute('SELECT * FROM conversation_controls WHERE uid=? AND request_id=?',(uid,body.request_id)).fetchone()
        if not old:return None
        if old['cid']!=body.conversation_id or old['request_body']!=encode(body.model_dump()):raise Fault('idempotency_conflict',409)
        store.conversation(uid,body.conversation_id)
        return json.loads(old['response'])
    app.state.previous_conversation_control=previous_control

    def record_control(uid,body,response):
        if not response.get('device_id'):return
        store.conversation(uid,body.conversation_id,response['device_id'])
        with store.tx() as db:
            old=db.execute('SELECT cid,user_text FROM conversation_controls WHERE uid=? AND request_id=?',(uid,body.request_id)).fetchone()
            if old:
                if old['cid']!=body.conversation_id or old['user_text']!=body.text:raise Fault('idempotency_conflict',409)
                return
            db.execute('INSERT INTO conversation_controls VALUES(?,?,?,?,?,?,?,?,?)',(secrets.token_hex(16),uid,body.conversation_id,body.request_id,body.text,str(response.get('reply',''))[:24000],time.time(),encode(response),encode(body.model_dump())))
    app.state.record_conversation_control=record_control

    def activity(uid,cid,before=None,limit=50):
        query="""SELECT id,created,'task' kind FROM tasks WHERE user_id=? AND json_extract(specification,'$.conversation_id')=?
          UNION ALL SELECT id,created,'control' kind FROM conversation_controls WHERE uid=? AND cid=?""";args=[uid,cid,uid,cid]
        with store.lock:
            if before:
                cursor=store.db.execute('SELECT * FROM ('+query+') WHERE id=?',(*args,before)).fetchone()
                if not cursor:raise Fault('conversation_cursor_not_found',404)
                return store.db.execute('SELECT * FROM ('+query+') WHERE created<? OR (created=? AND id<?) ORDER BY created DESC,id DESC LIMIT ?',(*args,cursor['created'],cursor['created'],before,limit)).fetchall()
            return store.db.execute('SELECT * FROM ('+query+') ORDER BY created DESC,id DESC LIMIT ?',(*args,limit)).fetchall()

    @app.get(PREFIX+'/assistant/conversations')
    async def conversations(archived:bool=False,before:str|None=None,limit:int=Query(default=40,ge=1,le=100),uid=Depends(user)):
        query="""WITH activity AS (
          SELECT json_extract(specification,'$.conversation_id') cid,created FROM tasks WHERE user_id=?
          UNION ALL SELECT cid,created FROM conversation_controls WHERE uid=?),
          recent AS (SELECT cid,MAX(created) latest FROM activity GROUP BY cid)
          SELECT c.id,c.created,r.latest FROM assistant_conversations c
          JOIN recent r ON r.cid=c.id LEFT JOIN conversation_views v ON v.cid=c.id
          WHERE c.user_id=? AND COALESCE(v.archived,0)=?"""
        args=[uid,uid,uid,int(archived)]
        with store.lock:
            if before:
                cursor=store.db.execute(query+' AND c.id=?',(*args,before)).fetchone()
                if not cursor:raise Fault('conversation_cursor_not_found',404)
                query+=' AND (r.latest<? OR (r.latest=? AND c.id<?))';args.extend([cursor['latest'],cursor['latest'],before])
            rows=store.db.execute(query+' ORDER BY r.latest DESC,c.id DESC LIMIT ?',(*args,limit+1)).fetchall()
        more=len(rows)>limit;rows=rows[:limit];data=[]
        for row in rows:
            item=meta(uid,row['id']);recent=tasks(uid,row['id'],limit=1)
            item.update(title=item['title'] or '新对话',created=row['created'],updated=row['latest'],state=recent[0]['state'] if recent else 'empty')
            data.append(item)
        return {'ok':True,'conversations':data,'next_cursor':rows[-1]['id'] if more else None}

    @app.get(PREFIX+'/assistant/conversations/{cid}')
    async def history(cid:str,before:str|None=None,limit:int=Query(default=40,ge=1,le=60),uid=Depends(user)):
        item=meta(uid,cid);rows=activity(uid,cid,before,limit+1);more=len(rows)>limit;rows=rows[:limit];turns=[]
        for event_row in reversed(rows):
            if event_row['kind']=='control':
                with store.lock:control=store.db.execute('SELECT * FROM conversation_controls WHERE uid=? AND id=?',(uid,event_row['id'])).fetchone()
                turns.append({'id':control['id'],'task_id':None,'user_text':control['user_text'],'assistant_text':control['reply'],'images':[],'model':'','state':'succeeded','is_work':False,'created':control['created'],'last_seq':0,'cancel_requested':False})
                continue
            with store.lock:row=store.db.execute('SELECT * FROM tasks WHERE user_id=? AND id=?',(uid,event_row['id'])).fetchone()
            spec=json.loads(row['specification']);delta=[];result=None;seq=0
            with store.lock:events=store.db.execute('SELECT seq,body FROM events WHERE task_id=? ORDER BY seq',(row['id'],)).fetchall()
            for event in events:
                body=json.loads(event['body']);seq=event['seq']
                if body.get('type')=='task.result':result=str(body.get('text',''))[:24000]
                elif body.get('type')=='task.delta':delta.append(str(body.get('text','')))
            turns.append({'task_id':row['id'],'user_text':spec.get('voice_text',spec.get('prompt','')),'assistant_text':result if result is not None else ''.join(delta)[:24000],
                'images':spec.get('life_images',[]),'model':spec.get('chat_model',''),'state':row['state'],'is_work':bool(row['is_work']),'created':row['created'],'last_seq':seq,'cancel_requested':bool(row['cancel_requested'])})
        if not item['title'] and turns:item['title']=turns[0]['user_text'][:60]
        return {'ok':True,'conversation':item,'turns':turns,'next_cursor':rows[-1]['id'] if more else None}

    @app.patch(PREFIX+'/assistant/conversations/{cid}')
    async def edit(cid:str,body:Edit,uid=Depends(user)):
        meta(uid,cid)
        if body.title is None and body.archived is None:raise Fault('conversation_edit_required',400)
        if body.title is not None and not body.title.strip():raise Fault('conversation_title_required',400)
        with store.tx() as db:
            db.execute('INSERT OR IGNORE INTO conversation_views(cid) VALUES(?)',(cid,))
            if body.title is not None:db.execute('UPDATE conversation_views SET title=? WHERE cid=?',(body.title.strip(),cid))
            if body.archived is not None:db.execute('UPDATE conversation_views SET archived=? WHERE cid=?',(int(body.archived),cid))
        return {'ok':True,'conversation':meta(uid,cid)}
