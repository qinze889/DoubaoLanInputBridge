"""Responses image jobs: private assets, exactly-once submission, explicit uncertainty."""
import base64
import io
import json
import secrets
import time
from pathlib import Path

import httpx
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from server.core_v2.app import PREFIX, create_app
from server.core_v2.providers import Providers, ProviderConfig


def png():
    output=io.BytesIO();Image.new('RGBA',(32,24),(30,120,70,255)).save(output,'PNG');return output.getvalue()


def setup(tmp_path,handler=None,asset=False):
    sent=[]
    def upstream(req):
        if req.url.path=='/v1/models':return httpx.Response(200,json={'data':[{'id':'chat'},{'id':'image-a'},{'id':'image-b'}]})
        if req.method=='GET':
            assert req.url.host=='assets.example.invalid' and 'authorization' not in req.headers
            return httpx.Response(200,content=png())
        sent.append(json.loads(req.content));assert req.url.path=='/v1/responses'
        if handler:return handler(req)
        output=([{'type':'message','content':[{'type':'output_text','text':'![生成图片](https://assets.example.invalid/generated-images/'+'a'*64+'.png)'}]}] if asset else
                [{'type':'image_generation_call','status':'completed','result':base64.b64encode(png()).decode()}])
        return httpx.Response(200,json={'status':'completed','output':output,'usage':{'credit':2.5},'image_source':'fixture image'})
    provider=Providers(ProviderConfig(model_base='https://fixture.invalid/v1',model_key='private-test',text_model='chat',image_models=('image-a','image-b'),image_asset_origin='https://assets.example.invalid'),httpx.MockTransport(upstream))
    app=create_app(tmp_path,admin_token='test-admin-'+'x'*40,providers=provider)
    store=app.state.store
    u=store.register('image-user','image-password-1234',store.invite(100))
    return app,u,sent


def auth(u):return {'Authorization':'Bearer '+u['token']}


def submit(client,u,**overrides):
    return client.post(PREFIX+'/images/jobs',headers=auth(u),json={'prompt':'A green leaf','request_id':secrets.token_hex(16),**overrides})


def wait(client,u,ident):
    for _ in range(100):
        job=client.get(PREFIX+'/images/jobs/'+ident,headers=auth(u)).json()['job']
        if job['state'] not in {'queued','running'}:return job
        time.sleep(.01)
    raise AssertionError('job did not finish')


@pytest.mark.parametrize('asset',[False,True])
def test_responses_image_private_persistent_and_no_replay(tmp_path,asset):
    app,u,sent=setup(tmp_path,asset=asset)
    with TestClient(app) as c:
        request=secrets.token_hex(16);r=submit(c,u,request_id=request);assert r.status_code==200,r.text
        ident=r.json()['job']['id'];job=wait(c,u,ident);assert job['state']=='succeeded',job
        assert job['width']==32 and job['height']==24 and job['usage']=={'credit':2.5}
        file=c.get(PREFIX+'/images/jobs/'+ident+'/file',headers=auth(u));assert file.status_code==200 and file.content==png()
        entry=app.state.life.store.entries(u['user_id'])[0];assert entry['role']=='assistant' and entry['kind']=='photo'
        assert app.state.store.wallet(u['user_id'])=={'balance':90,'reserved':0}
        c.patch(PREFIX+'/images/settings',headers=auth(u),json={'model':'image-b'})
        assert submit(c,u,request_id=request).json()['job']['id']==ident
        assert submit(c,u,request_id=request,prompt='changed').status_code==409
        other=app.state.store.register('image-other','image-other-password',app.state.store.invite(100))
        assert c.get(PREFIX+'/images/jobs',headers=auth(other)).json()['jobs']==[]
        assert c.get(PREFIX+'/images/jobs/'+ident+'/file',headers=auth(other)).status_code==404
        assert c.get(PREFIX+'/images/jobs/'+ident+'/file').status_code==401
        assert len(sent)==1 and sent[0]['tools']==[{'type':'image_generation'}]
    reopened=create_app(tmp_path,admin_token='test-admin-'+'x'*40)
    assert reopened.state.images.public(u['user_id'],ident)['state']=='succeeded'
    assert reopened.state.store.db.execute('SELECT model FROM image_preferences').fetchone()[0]=='image-b'
    reopened.state.life.store.close();reopened.state.store.close()


@pytest.mark.parametrize('status,state,reserved',[(400,'failed',0),(500,'unknown',10)])
def test_rejected_or_unknown_generation_does_not_auto_repeat(tmp_path,status,state,reserved):
    app,u,sent=setup(tmp_path,lambda req:httpx.Response(status,json={'error':'secret upstream body'}))
    with TestClient(app) as c:
        request=secrets.token_hex(16);ident=submit(c,u,request_id=request).json()['job']['id'];job=wait(c,u,ident)
        assert job['state']==state and 'secret' not in json.dumps(job)
        assert app.state.store.wallet(u['user_id'])['reserved']==reserved
        assert submit(c,u,request_id=request).json()['job']['id']==ident and len(sent)==1


def test_unknown_protocol_result_is_not_treated_as_generated_image(tmp_path):
    app,u,sent=setup(tmp_path,lambda req:httpx.Response(200,json={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'I drew a leaf'}]}]}))
    with TestClient(app) as c:
        ident=submit(c,u).json()['job']['id'];assert wait(c,u,ident)['state']=='unknown'
        assert c.get(PREFIX+'/images/jobs/'+ident+'/file',headers=auth(u)).status_code==409
        assert len(sent)==1


def test_model_allowlist_and_restarted_job_not_replayed(tmp_path):
    app,u,sent=setup(tmp_path)
    with TestClient(app) as c:
        assert submit(c,u,model='unverified').status_code==409
        assert submit(c,u,prompt='   ').status_code==400
        assert c.patch(PREFIX+'/images/settings',headers=auth(u),json={'model':'unverified'}).status_code==409
        with app.state.store.tx() as db:
            db.execute("INSERT INTO image_jobs(id,uid,request_id,fingerprint,model,prompt,state,created,updated) VALUES(?,?,?,?,?,?,'running',?,?)",('a'*32,u['user_id'],'restart-request-123','fp','image-a','leaf',time.time(),time.time()))
    reopened=create_app(tmp_path,admin_token='test-admin-'+'x'*40)
    assert reopened.state.images.public(u['user_id'],'a'*32)['state']=='unknown' and not sent
    reopened.state.life.store.close();reopened.state.store.close()


def test_legacy_asset_cannot_fetch_other_origin_or_leak_provider_key(tmp_path):
    def handler(req):
        return httpx.Response(200,json={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'![image](https://evil.invalid/generated-images/'+'a'*64+'.png)'}]}]})
    app,u,sent=setup(tmp_path,handler,asset=True)
    with TestClient(app) as c:
        ident=submit(c,u).json()['job']['id'];assert wait(c,u,ident)['state']=='unknown'
        assert len(sent)==1
        assert app.state.store.wallet(u['user_id'])['reserved']==10


def test_completed_generation_with_asset_connection_failure_keeps_uncertain_reservation(tmp_path):
    app,u,sent=setup(tmp_path,asset=True)
    original=app.state.images.providers.transport.handler
    def broken_download(req):
        if req.url.host=='assets.example.invalid':raise httpx.ConnectError('fixture asset offline',request=req)
        return original(req)
    app.state.images.providers.transport=httpx.MockTransport(broken_download)
    with TestClient(app) as c:
        ident=submit(c,u).json()['job']['id'];assert wait(c,u,ident)['state']=='unknown'
        assert app.state.store.wallet(u['user_id'])['reserved']==10
        assert len(sent)==1


def test_reference_edit_queued_followup_uses_actual_parent_pixels_and_scopes_owner(tmp_path):
    import asyncio
    sent=[]
    first=png()
    def image(color):
        output=io.BytesIO();Image.new('RGB',(32,24),color).save(output,'PNG');return output.getvalue()
    changed=image('yellow');second=image('pink')
    async def upstream(req):
        if req.method=='GET':return httpx.Response(200,json={'data':[{'id':'chat'},{'id':'edit-a'},{'id':'edit-b'}]})
        assert req.url.path=='/v1/images/edits'
        raw=await req.aread();sent.append(raw)
        assert first in raw if len(sent)==1 else changed in raw
        await asyncio.sleep(.1)
        return httpx.Response(200,json={'data':[{'b64_json':base64.b64encode(changed if len(sent)==1 else second).decode()}]})
    p=Providers(ProviderConfig(model_base='https://fixture.invalid/v1',model_key='fixture-key',text_model='chat',image_edit_models=('edit-a','edit-b')),httpx.MockTransport(upstream))
    app=create_app(tmp_path,admin_token='test-admin-'+'x'*40,providers=p)
    with TestClient(app) as c:
        store=app.state.store;u=store.register('edit-user','edit-user-password',store.invite(100));uid=u['user_id'];photo=app.state.life.store.add_image(uid,first,32,24,secrets.token_hex(16))
        a=submit(c,u,image_id=photo['id']);assert a.status_code==200,a.text;a=a.json()['job'];assert a['operation']=='edit'
        b=submit(c,u,parent_job_id=a['id'],prompt='Warm it further');assert b.status_code==200,b.text;b=b.json()['job']
        assert b['parent_job_id']==a['id'] and b['root_job_id']==a['id'] and b['version']==2
        c.patch(PREFIX+'/images/settings',headers=auth(u),json={'edit_model':'edit-b'})
        assert wait(c,u,b['id'])['state']=='succeeded' and len(sent)==2
        assert b'edit-a' in sent[0] and b'edit-a' in sent[1]
        assert c.get(PREFIX+'/images/jobs/'+b['id']+'/file',headers=auth(u)).content==second
        other=store.register('edit-other','edit-other-password',store.invite(100))
        assert submit(c,other,parent_job_id=a['id']).status_code==404
        assert submit(c,other,image_id=photo['id']).status_code==404
        assert submit(c,u,image_id=photo['id'],model='chat').status_code==409
        assert store.wallet(uid)=={'balance':80,'reserved':0}


def test_failed_parent_releases_unsubmitted_followup_and_diagnostics_are_sanitized(tmp_path):
    import asyncio
    sent=[]
    async def upstream(req):
        if req.method=='GET':return httpx.Response(200,json={'data':[{'id':'chat'},{'id':'edit'}]})
        sent.append(req);await asyncio.sleep(.15)
        return httpx.Response(500,json={'secret':'not exposed'})
    p=Providers(ProviderConfig(model_base='https://fixture.invalid/v1',model_key='secret',text_model='chat',image_edit_models=('edit',)),httpx.MockTransport(upstream))
    app=create_app(tmp_path,admin_token='test-admin-'+'x'*40,providers=p)
    with TestClient(app) as c:
        store=app.state.store;u=store.register('edit-fail','edit-fail-password',store.invite(100));photo=app.state.life.store.add_image(u['user_id'],png(),32,24,secrets.token_hex(16))
        a=submit(c,u,image_id=photo['id']).json()['job'];b=submit(c,u,parent_job_id=a['id']).json()['job']
        job=wait(c,u,b['id']);assert job['state']=='failed' and job['error']=='image_parent_not_completed'
        assert len(sent)==1 and store.wallet(u['user_id'])=={'balance':90,'reserved':10}
        event={'stage':'edit_submit','code':'image_model_not_available'}
        assert c.post(PREFIX+'/images/client-events',headers=auth(u),json=event).status_code==200
        assert c.post(PREFIX+'/images/client-events',headers=auth(u),json={**event,'prompt':'never store content'}).status_code==422
        assert c.post(PREFIX+'/images/client-events',json=event).status_code==401


def test_capabilities_require_auth_and_separate_actual_task_protocols(tmp_path):
    app,u,_=setup(tmp_path)
    with TestClient(app) as c:
        assert c.get(PREFIX+'/models/capabilities').status_code==401
        data=c.get(PREFIX+'/models/capabilities',headers=auth(u)).json()['data']
        assert {m['id'] for m in data}=={'chat','image-a','image-b'}
        assert next(m for m in data if m['id']=='chat')['output_modalities']==['text']
        assert all(m['protocol']=='responses' and m['input_modalities']==['text'] for m in data if m['task']=='image_generate')
        assert not any(m['task']=='image_edit' for m in data)
        assert 'private-test' not in json.dumps(data)


def test_unlimited_generation_never_mutates_balance_but_tracks_usage(tmp_path):
    app,u,sent=setup(tmp_path)
    with TestClient(app) as c:
        store=app.state.store;store.set_unlimited(u['user_id'],True,secrets.token_hex(16))
        before=store.wallet(u['user_id']);ident=submit(c,u).json()['job']['id']
        assert wait(c,u,ident)['state']=='succeeded'
        assert store.wallet(u['user_id'])==before and len(sent)==1
        assert c.get(PREFIX+'/images/settings',headers=auth(u)).json()['unlimited']
        usage=store.db.execute('SELECT state,actual,unlimited FROM usage WHERE id=?',('image-'+ident,)).fetchone()
        assert dict(usage)=={'state':'settled','actual':10,'unlimited':1}


def test_simultaneous_retry_during_model_discovery_submits_once(tmp_path):
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    app,u,sent=setup(tmp_path)
    original=app.state.images.providers.models
    arrivals=0;gate=asyncio.Event()
    async def discover():
        nonlocal arrivals
        arrivals+=1
        if arrivals==2:gate.set()
        await asyncio.wait_for(gate.wait(),2)
        return await original()
    app.state.images.providers.models=discover
    with TestClient(app) as c:
        request=secrets.token_hex(16)
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(submit,c,u,request_id=request);b=pool.submit(submit,c,u,request_id=request)
            results=[f.result(timeout=5) for f in [a,b]]
        assert all(r.status_code==200 for r in results)
        ident=results[0].json()['job']['id'];assert results[1].json()['job']['id']==ident
        assert wait(c,u,ident)['state']=='succeeded' and len(sent)==1
