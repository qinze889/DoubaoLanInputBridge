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
