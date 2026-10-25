import json,secrets,time,sqlite3
from pathlib import Path
from fastapi.testclient import TestClient
from server.core_v2.app import PREFIX,create_app

class Peer:
    async def close(self,**kwargs):pass

def fixture(tmp_path):
    app=create_app(tmp_path,admin_token='product-admin-'+'x'*40);s=app.state.store
    u=s.register('product-user','product-password-123',s.invite(0));other=s.register('product-other','product-password-456',s.invite(0))
    d=s.enroll(u['user_id'],'我的电脑',['tasks','metrics']);s.authorize_device(u['user_id'],d['id'],['tasks','metrics']);s.heartbeat(d['id'],{'harness_chat':True,'cpu_percent':5});app.state.peers[d['id']]=Peer()
    return app,u,other,d

def auth(u):return {'Authorization':'Bearer '+u['token']}
def post(c,u,d,cid,text,**kw):return c.post(PREFIX+'/assistant/chat',headers=auth(u),json={'text':text,'conversation_id':cid,'device_id':d['id'],'request_id':secrets.token_hex(16),**kw})
def event(s,d,t,body):s.device_event(d['id'],t,body,secrets.token_hex(16))
def start(s,d,t):assert s.dispatch(d['id'])['id']==t;event(s,d,t,{'type':'task.state','state':'running'})
def finish(s,d,t,text='已完成'):event(s,d,t,{'type':'task.result','text':text});event(s,d,t,{'type':'task.state','state':'succeeded'})

def test_owned_history_archive_models_and_work_classification(tmp_path):
    app,u,other,d=fixture(tmp_path);s=app.state.store;cid=secrets.token_hex(16)
    with TestClient(app) as c:
        r=post(c,u,d,cid,'第一句日常聊天');assert r.status_code==200,r.text;t=r.json()['task']['id'];assert r.json()['task']['is_work']==0
        start(s,d,t);event(s,d,t,{'type':'task.log','text':json.dumps({'type':'tool_call','tool':'see_user_image'})});assert s.task(u['user_id'],t)['is_work']==0

        for media in ['media_models','create_image','edit_image','view_conversation_image','image_job_status']:
            event(s,d,t,{'type':'task.log','text':json.dumps({'type':'tool_call','tool':media})});assert s.task(u['user_id'],t)['is_work']==0
        event(s,d,t,{'type':'task.delta','text':'中间'});finish(s,d,t,'完整回复')
        t2=post(c,u,d,cid,'帮我在后台打开网页').json()['task']['id'];start(s,d,t2);event(s,d,t2,{'type':'task.log','text':json.dumps({'type':'tool_call','tool':'background_browser','private':'must not appear in transcript'})});assert s.task(u['user_id'],t2)['is_work']==1;finish(s,d,t2)
        data=c.get(PREFIX+'/assistant/conversations/'+cid,headers=auth(u)).json();assert len(data['turns'])==2;assert data['turns'][0]['assistant_text']=='完整回复';assert 'private' not in json.dumps(data)
        assert c.get(PREFIX+'/assistant/conversations/'+cid).status_code==401
        assert c.get(PREFIX+'/assistant/conversations/'+cid,headers=auth(other)).status_code==404
        assert c.patch(PREFIX+'/assistant/conversations/'+cid,headers=auth(other),json={'archived':True}).status_code==404
        assert c.get(PREFIX+'/assistant/conversations',headers=auth(other)).json()['conversations']==[]
        meta=c.patch(PREFIX+'/assistant/conversations/'+cid,headers=auth(u),json={'archived':True,'title':'我自己的标题'}).json()['conversation'];assert meta['archived']
        assert c.get(PREFIX+'/assistant/conversations',headers=auth(u)).json()['conversations']==[]
        assert c.get(PREFIX+'/assistant/conversations?archived=true',headers=auth(u)).json()['conversations'][0]['title']=='我自己的标题'
        assert c.get(PREFIX+'/assistant/conversations/'+cid,headers=auth(u)).json()['turns'][1]['is_work']
        assert c.patch(PREFIX+'/assistant/conversations/'+cid,headers=auth(u),json={'archived':False}).status_code==200
        assert c.get(PREFIX+'/me',headers=auth(u)).json()['username']=='product-user'
    reopened=create_app(tmp_path,admin_token='product-admin-'+'x'*40)
    with TestClient(reopened) as c:assert c.get(PREFIX+'/assistant/conversations/'+cid,headers=auth(u)).json()['conversation']['title']=='我自己的标题'


def test_control_turns_persist_and_cancel_retry_never_cancels_new_work(tmp_path):
    app,u,other,d=fixture(tmp_path);s=app.state.store;cid=secrets.token_hex(16)
    with TestClient(app) as c:
        metrics=post(c,u,d,cid,'查看电脑状态');assert metrics.status_code==200;assert metrics.json()['action']=='metrics'
        history=c.get(PREFIX+'/assistant/conversations/'+cid,headers=auth(u)).json();assert history['turns'][0]['task_id'] is None;assert 'CPU' in history['turns'][0]['assistant_text']
        assert c.get(PREFIX+'/assistant/conversations',headers=auth(u)).json()['conversations'][0]['title']=='查看电脑状态'
        t=post(c,u,d,cid,'后台完成第一项工作').json()['task']['id'];start(s,d,t)
        request=secrets.token_hex(16);cancel=post(c,u,d,cid,'取消当前任务',task_id=t,request_id=request);assert cancel.status_code==200 and cancel.json()['task']['cancel_requested']
        event(s,d,t,{'type':'task.state','state':'cancelled'})
        t2=post(c,u,d,cid,'这是另一项新工作').json()['task']['id'];start(s,d,t2)
        again=post(c,u,d,cid,'取消当前任务',task_id=t,request_id=request);assert again.json()==cancel.json();assert not s.task(u['user_id'],t2)['cancel_requested']
        assert post(c,u,d,cid,'查看电脑状态',request_id=request).status_code==409
        turns=c.get(PREFIX+'/assistant/conversations/'+cid,headers=auth(u)).json()['turns'];assert len(turns)==4 and sum(t['user_text']=='取消当前任务' for t in turns)==1
        finish(s,d,t2)


def test_pagination_tie_breaker_control_and_task_history_never_execute(tmp_path):
    app,u,_,d=fixture(tmp_path);s=app.state.store;cid=secrets.token_hex(16)
    with TestClient(app) as c:
        ids=[]
        for i in range(5):
            t=post(c,u,d,cid,'第'+str(i)+'句话').json()['task']['id'];ids.append(t);start(s,d,t);finish(s,d,t)
        with s.tx() as db:db.execute('UPDATE tasks SET created=123 WHERE user_id=?',(u['user_id'],))
        a=c.get(PREFIX+'/assistant/conversations/'+cid+'?limit=2',headers=auth(u)).json();assert a['next_cursor']
        b=c.get(PREFIX+'/assistant/conversations/'+cid+'?limit=2&before='+a['next_cursor'],headers=auth(u)).json()
        last=c.get(PREFIX+'/assistant/conversations/'+cid+'?limit=2&before='+b['next_cursor'],headers=auth(u)).json();found=[t['task_id'] for x in [a,b,last] for t in x['turns']];assert len(found)==len(set(found))==5
        assert s.dispatch(d['id']) is None
        assert c.get(PREFIX+'/assistant/conversations/'+cid+'?before='+'a'*32,headers=auth(u)).status_code==404


def test_upgrade_classifies_existing_chat_work_and_approvals_without_reexecution(tmp_path):
    app,u,_,d=fixture(tmp_path);s=app.state.store;cid=secrets.token_hex(16)
    with TestClient(app) as c:
        ids=[]
        for tool in ['see_user_image','shell','approval']:
            ident=post(c,u,d,cid,'历史对话 '+tool).json()['task']['id'];ids.append(ident);start(s,d,ident)
            if tool=='approval':
                approval=secrets.token_hex(16);event(s,d,ident,{'type':'task.approval','approval_id':approval,'text':'需要确认'});s.approve(u['user_id'],ident,approval,{'approved':True});event(s,d,ident,{'type':'task.state','state':'running'})
            else:event(s,d,ident,{'type':'task.log','text':json.dumps({'type':'tool_call','tool':tool})})
            finish(s,d,ident)
    s.close()
    db=sqlite3.connect(tmp_path/'core.sqlite3');db.execute('ALTER TABLE tasks DROP COLUMN is_work');db.commit();db.close()
    upgraded=create_app(tmp_path,admin_token='product-admin-'+'x'*40);store=upgraded.state.store
    assert [store.task(u['user_id'],ident)['is_work'] for ident in ids]==[0,1,1]
    assert store.dispatch(d['id']) is None
    assert store.db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]==3


def test_conversation_list_cursor_and_control_only_history(tmp_path):
    app,u,other,d=fixture(tmp_path);s=app.state.store
    with TestClient(app) as c:
        ids=[]
        for i in range(5):
            cid=secrets.token_hex(16);ids.append(cid)
            if i==0:assert post(c,u,d,cid,'查看电脑状态').status_code==200
            else:
                t=post(c,u,d,cid,'第'+str(i)+'段对话').json()['task']['id'];start(s,d,t);finish(s,d,t)
        with s.tx() as db:
            db.execute('UPDATE tasks SET created=123');db.execute('UPDATE conversation_controls SET created=123')
        found=[];cursor=''
        for _ in range(3):
            page=c.get(PREFIX+'/assistant/conversations?limit=2'+('&before='+cursor if cursor else ''),headers=auth(u)).json();found.extend(r['id'] for r in page['conversations']);cursor=page['next_cursor']
        assert not cursor and found==sorted(ids,reverse=True)
        assert c.get(PREFIX+'/assistant/conversations?before='+ids[0],headers=auth(other)).status_code==404
