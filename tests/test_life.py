import asyncio
import io
import json
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from server.core_v2.app import create_app, PREFIX
from server.core_v2.life_store import LifeStore
from server.core_v2.providers import Providers, ProviderConfig
from server.core_v2.store import Fault


def record(store, uid='a', text='我今天在公园散步。', **extra):
    return store.record(uid,dict({'request_id':secrets.token_hex(16),'kind':'note','role':'user','text':text,'images':[]},**extra))


def today():return datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()


def output(entry):return {'summary':'今天去公园。','memories':[{'key':'park-'+today(),'text':'今天在公园散步。','kind':'event','sources':[entry['id']]}]}


def test_source_ownership_revision_and_deletion(tmp_path):
    s=LifeStore(tmp_path);r=record(s);j,claimed,_=s.claim('a',today());assert claimed
    bad=output(r);bad['memories'][0]['sources']=['other-user-record']
    with pytest.raises(Fault,match='invalid_memory_sources'):s.finish(j,bad)
    s.finish(j,output(r));m=s.memories('a')[0]
    assert not s.memories('b')
    with pytest.raises(Fault):s.edit_memory('b',m['id'],'new')
    s.delete_entry('a',r['id']);assert not s.memories('a')
    assert s.jobs('a')[0]['summary']==''
    assert s.db.execute('SELECT COUNT(*) FROM memory_history').fetchone()[0]==0
    s.close()


def test_revision_changed_inflight_never_publishes(tmp_path):
    s=LifeStore(tmp_path);r=record(s);j,_,_=s.claim('a',today());record(s,text='后来回家了。')
    s.finish(j,output(r));assert not s.memories('a');assert s.jobs('a')[0]['state']=='obsolete';s.close()


def test_manual_edit_and_tombstone_survive_consolidation(tmp_path):
    s=LifeStore(tmp_path);r=record(s);j,_,_=s.claim('a',today());s.finish(j,output(r));m=s.memories('a')[0]
    s.edit_memory('a',m['id'],'我修改的内容。')
    j,_,_=s.claim('a',today(),True);s.finish(j,output(r));assert s.memories('a')[0]['text']=='我修改的内容。'
    s.edit_memory('a',m['id']);j,_,_=s.claim('a',today(),True);s.finish(j,output(r));assert not s.memories('a');s.close()


def test_claim_restart_unknown_and_idempotency(tmp_path):
    s=LifeStore(tmp_path);r=record(s);j,_,_=s.claim('a',today());assert not s.claim('a',today())[1]
    s.close();s=LifeStore(tmp_path);assert s.jobs('a')[0]['state']=='unknown';assert not s.claim('a',today())[1]
    assert s.claim('a',today(),True)[0]['id']!=j['id'];s.close()


def test_photo_owner_retry_and_source_cleanup(tmp_path):
    s=LifeStore(tmp_path);im=s.add_image('a',b'test',1,1,'photo-request-id-123')
    assert s.add_image('a',b'test',1,1,'photo-request-id-123')['id']==im['id']
    with pytest.raises(Fault):s.add_image('a',b'changed',1,1,'photo-request-id-123')
    with pytest.raises(Fault):s.image('b',im['id'])
    with pytest.raises(Fault):record(s,'b',images=[im['id']])
    r=record(s,images=[im['id']]);s.delete_entry('a',r['id']);assert not (s.files/(im['id']+'.jpg')).exists();s.close()


def test_pagination_equal_timestamps_does_not_lose_entries(tmp_path):
    s=LifeStore(tmp_path)
    import time
    stamp=time.time()
    for i in range(61):record(s,text=str(i),created=stamp)
    first=s.entries('a');last=first[-1];second=s.entries('a',last['created'],before_id=last['id'])
    assert len(first)==50 and len(second)==11 and len({x['id'] for x in first+second})==61;s.close()


def test_capture_setting_and_authenticated_normalized_upload(tmp_path):
    app=create_app(tmp_path,admin_token='x'*40)
    a=app.state.store.register('life-test','isolated-password-123',app.state.store.invite(100))
    b=app.state.store.register('other-test','isolated-password-123',app.state.store.invite(100))
    headers={'Authorization':'Bearer '+a['token'],'X-Request-ID':'test-image-request-123'}
    raw=io.BytesIO();Image.new('RGB',(1800,400),'green').save(raw,format='PNG')
    with TestClient(app) as c:
        assert c.post(PREFIX+'/life/images',content=raw.getvalue()).status_code==401
        assert c.post(PREFIX+'/life/images',content=b'bad',headers=headers).status_code==415
        r=c.post(PREFIX+'/life/images',content=raw.getvalue(),headers=headers);assert r.status_code==200;im=r.json()['image'];assert im['width']==1600
        assert c.post(PREFIX+'/life/images',content=raw.getvalue(),headers=headers).json()['image']['id']==im['id']
        assert c.get(PREFIX+'/life/images/'+im['id'],headers={'Authorization':'Bearer '+b['token']}).status_code==404
        assert c.get(PREFIX+'/life/images/'+im['id'],headers=headers).content.startswith(b'\xff\xd8')
        assert c.patch(PREFIX+'/life/settings',json={'capture':False},headers=headers).status_code==200
        body={'request_id':'test-life-record-123','kind':'chat','text':'test'}
        assert c.post(PREFIX+'/life/entries',json=body,headers=headers).json()['skipped']
        body.update(kind='photo',images=[im['id']]);r=c.post(PREFIX+'/life/entries',json=body,headers=headers);assert r.status_code==200
        assert c.post(PREFIX+'/life/entries',json=body,headers=headers).json()['entry']['id']==r.json()['entry']['id']
        assert c.post(PREFIX+'/life/entries',content=b'x'*131073,headers=headers).status_code==413
        assert c.post(PREFIX+'/life/images',content=b'x'*(8*1024*1024+1),headers=headers).status_code==413


def test_vision_caption_and_memory_use_actual_image_and_settle_once(tmp_path):
    calls=[];entry=None
    def upstream(req):
        if req.method=='GET':return httpx.Response(200,json={'data':[{'id':'text'},{'id':'vision'}]})
        body=json.loads(req.content);calls.append(body)
        if body['model']=='vision':
            assert body['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/jpeg;base64,')
            content='白纸上有红色圆形。'
        else:
            content=json.dumps(output(entry),ensure_ascii=False)
            assert '白纸上有红色圆形' in body['messages'][1]['content']
            assert body['tool_choice']['function']['name']=='record_life_day'
            return httpx.Response(200,json={'choices':[{'message':{'content':None,'tool_calls':[{'function':{'name':'record_life_day','arguments':content}}]}}],'usage':{'total_tokens':20}})
        return httpx.Response(200,json={'choices':[{'message':{'content':content}}],'usage':{'total_tokens':20}})
    provider=Providers(ProviderConfig(model_base='https://model.invalid/v1',model_key='test-secret',text_model='text',vision_model='vision'),transport=httpx.MockTransport(upstream))
    app=create_app(tmp_path,admin_token='x'*40,providers=provider)
    a=app.state.store.register('vision-test','isolated-password-123',app.state.store.invite(100))
    life=app.state.life;s=life.store;im=s.add_image(a['user_id'],b'jpeg-test',1,1,'image-request-id-123');entry=record(s,a['user_id'],images=[im['id']])
    j,_,rows=s.claim(a['user_id'],today());asyncio.run(life.consolidate(j,rows))
    assert s.jobs(a['user_id'])[0]['state']=='succeeded';assert s.memories(a['user_id'])[0]['sources']==[entry['id']]
    assert len(calls)==2 and app.state.store.wallet(a['user_id'])=={'balance':98,'reserved':0}
    # Same revision has no new model call. A deliberate rerun reuses the cached image description.
    assert not s.claim(a['user_id'],today())[1]
    j,_,rows=s.claim(a['user_id'],today(),True);asyncio.run(life.consolidate(j,rows));assert len(calls)==3
    s.close();app.state.store.close()


def test_nightly_respects_clock_timezone_and_auto_opt_out(tmp_path,monkeypatch):
    from server.core_v2 import life as module
    class Fixed(datetime):
        @classmethod
        def now(cls,zone):return cls(2026,10,23,23,10,tzinfo=ZoneInfo('Asia/Shanghai')).astimezone(zone)
    service=module.LifeService(tmp_path,None,None)
    service.store.preferences('enabled');service.store.preferences('disabled',{'auto':False})
    service.store.preferences('later',{'clock':'23:59'})
    calls=[];service.launch=lambda uid,day:calls.append((uid,day))
    async def stop(_):raise asyncio.CancelledError()
    monkeypatch.setattr(module,'datetime',Fixed);monkeypatch.setattr(module.asyncio,'sleep',stop)
    with pytest.raises(asyncio.CancelledError):asyncio.run(service.nightly())
    assert ('enabled','2026-10-23') in calls and ('enabled','2026-10-22') in calls
    assert all(uid!='disabled' for uid,_ in calls) and ('later','2026-10-23') not in calls
    service.store.close()
