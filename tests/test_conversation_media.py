import asyncio,base64,io,json,secrets
import httpx
from PIL import Image
from fastapi.testclient import TestClient
from server.core_v2.app import PREFIX,create_app
from server.core_v2.providers import ProviderConfig,Providers


def fixture(tmp_path):
    sent=[];release=asyncio.Event()
    raw=io.BytesIO();Image.new('RGB',(40,30),'red').save(raw,'PNG');png=raw.getvalue()
    async def upstream(request):
        if request.url.path.endswith('/models'):return httpx.Response(200,json={'data':[{'id':'chat','context_length':1000000,'max_output_tokens':128000},{'id':'vision'},{'id':'gen-a'},{'id':'gen-b'},{'id':'edit-a'}]})
        if request.url.path.endswith('/responses'):
            sent.append(json.loads(request.content));await release.wait()
            return httpx.Response(200,json={'status':'completed','output':[{'type':'image_generation_call','status':'completed','result':base64.b64encode(png).decode()}]})
        if request.url.path.endswith('/images/edits'):
            sent.append({'edit':True});return httpx.Response(200,json={'data':[{'b64_json':base64.b64encode(png).decode()}]})
        return httpx.Response(200,json={'choices':[{'message':{'content':'这是一张红色的图。'}}],'usage':{'total_tokens':5}})
    provider=Providers(ProviderConfig(model_base='https://fixture.invalid/v1',model_key='fixture-only',text_model='chat',vision_model='vision',image_models=('gen-a','gen-b'),image_edit_models=('edit-a',)),httpx.MockTransport(upstream))
    app=create_app(tmp_path,admin_token='fixture-admin-'+'x'*40,providers=provider);s=app.state.store
    class Peer:
        async def close(self,**kwargs):pass
    u=s.register('media-user','media-password-123',s.invite(10000));d=s.enroll(u['user_id'],'Mac',['tasks','metrics']);s.authorize_device(u['user_id'],d['id'],['tasks','metrics']);s.heartbeat(d['id'],{'harness_chat':True});app.state.peers[d['id']]=Peer()
    return app,u,d,s,sent,release


def test_model_tools_are_async_owned_inline_and_use_full_model_prompt(tmp_path):
    app,u,d,s,sent,release=fixture(tmp_path);auth={'Authorization':'Bearer '+u['token']};device={'Authorization':'Bearer '+d['token']};cid=secrets.token_hex(16)
    with TestClient(app) as c:
        r=c.post(PREFIX+'/assistant/chat',headers=auth,json={'text':'我们前面讨论了红色纸雕和柔和灯光，请按这个风格画一只猫。','conversation_id':cid,'request_id':secrets.token_hex(16)})
        assert r.status_code==200;r=r.json()['task'];s.dispatch(d['id']);s.device_event(d['id'],r['id'],{'type':'task.state','state':'running'},'start')
        caps=c.post(PREFIX+'/assistant/media-tool',headers=device,json={'action':'models','call_id':'models-call'}).json();assert {m['id'] for m in caps['generation']}=={'gen-a','gen-b'} and caps['selected_vision']=='vision'
        context=c.get(PREFIX+'/assistant/media-capabilities',headers=device).json();assert context['context_window']==1000000
        prompt='红色纸雕风格的小猫，柔和侧光，延续刚才讨论的立体层次。'
        body={'action':'generate','call_id':'create-call','prompt':prompt,'model':'gen-b'}
        result=c.post(PREFIX+'/assistant/media-tool',headers=device,json=body);assert result.status_code==200,result.text
        job=result.json()['job'];assert job['state'] in {'queued','running'} and not release.is_set()
        assert c.post(PREFIX+'/assistant/media-tool',headers=device,json=body).json()['job']['id']==job['id']
        listing=c.get(PREFIX+f'/assistant/conversations/{cid}/images',headers=auth).json()['jobs'];assert len(listing)==1 and listing[0]['task_id']==r['id']
        follow=c.post(PREFIX+'/assistant/chat',headers=auth,json={'text':'图片慢慢生成，我们继续聊灯光。','conversation_id':cid,'request_id':secrets.token_hex(16)})
        assert follow.status_code==200,'image generation must not block the next Chat turn'
        c.portal.call(release.set)
        for _ in range(100):
            current=c.get(PREFIX+'/images/jobs/'+job['id'],headers=auth).json()['job']
            if current['state']=='succeeded':break
            import time;time.sleep(.01)
        assert current['state']=='succeeded' and sent[0]['input']==prompt and sent[0]['model']=='gen-b'
        view=c.post(PREFIX+'/assistant/media-tool',headers=device,json={'action':'view','call_id':'view-call','prompt':'看看生成图的颜色','job_id':job['id']});assert view.status_code==200,view.text;assert '红色' in view.json()['observation']
        edit=c.post(PREFIX+'/assistant/media-tool',headers=device,json={'action':'edit','call_id':'edit-call','prompt':'保持纸雕层次，把光线再柔和一些','job_id':job['id']});assert edit.status_code==200,edit.text
        assert edit.json()['job']['parent_job_id']==job['id'] and edit.json()['job']['model']=='edit-a'
        by_image={'action':'edit','call_id':'edit-image-id','prompt':'把背景调亮一点','image_id':current['image_id']}
        version=c.post(PREFIX+'/assistant/media-tool',headers=device,json=by_image).json()['job']
        assert version['parent_job_id']==job['id'] and version['version']==2
        assert c.post(PREFIX+'/assistant/media-tool',headers=device,json=by_image).json()['job']['id']==version['id']
        implicit={'action':'edit','call_id':'edit-latest','prompt':'继续柔化光线'}
        latest=c.post(PREFIX+'/assistant/media-tool',headers=device,json=implicit).json()['job']
        assert c.post(PREFIX+'/assistant/media-tool',headers=device,json=implicit).json()['job']['id']==latest['id']
        assert c.post(PREFIX+'/assistant/media-tool',headers=device,json={**implicit,'prompt':'换成另一幅画'}).status_code==409
        with s.tx() as db:
            specification=json.loads(db.execute('SELECT specification FROM tasks WHERE id=?',(r['id'],)).fetchone()[0])
            specification['life_images']=[current['image_id']]
            db.execute('UPDATE tasks SET specification=? WHERE id=?',(json.dumps(specification),r['id']))
        selected=c.post(PREFIX+'/assistant/media-tool',headers=device,json={'action':'edit','call_id':'selected-older-version','prompt':'仅修改我这次选中的图片'})
        assert selected.status_code==200 and selected.json()['job']['parent_job_id']==job['id']
        other=s.register('media-other','media-other-password',s.invite(100))
        assert c.get(PREFIX+f'/assistant/conversations/{cid}/images',headers={'Authorization':'Bearer '+other['token']}).status_code==404
        assert c.post(PREFIX+'/assistant/media-tool',headers=auth,json=body).status_code==401
        assert c.post(PREFIX+'/assistant/media-tool',headers=device,json={**body,'call_id':'wrong-model','model':'chat'}).status_code==409
        s.revoke(u['user_id'],d['id'])
        assert c.post(PREFIX+'/assistant/media-tool',headers=device,json={'action':'models','call_id':'revoked'}).status_code==401


def test_long_conversation_payload_is_not_limited_to_128kb_or_100_messages(tmp_path):
    app,u,d,s,sent,release=fixture(tmp_path)
    task=s.create_task(u['user_id'],{'device_id':d['id'],'request_id':secrets.token_hex(16),'prompt':'长会话测试','engine':'harness','assistant_chat':True})
    s.dispatch(d['id']);s.device_event(d['id'],task['id'],{'type':'task.state','state':'running'},'long-start')
    messages=[{'role':'user','content':f'第{i}轮历史：'+'context '*150} for i in range(250)]
    assert len(json.dumps(messages).encode())>128*1024
    with TestClient(app) as c:
        r=c.post(PREFIX+'/model/v1/chat/completions',headers={'Authorization':'Bearer '+d['token'],'X-Request-ID':secrets.token_hex(16)},json={'model':'chat','messages':messages,'max_tokens':2048})
        assert r.status_code==200,r.text
        r=c.post(PREFIX+'/model/v1/chat/completions',headers={'Authorization':'Bearer '+d['token'],'X-Request-ID':secrets.token_hex(16)},json={'model':'chat','messages':messages,'max_tokens':-1})
        assert r.status_code==400
        r=c.post(PREFIX+'/model/v1/chat/completions',json={'messages':messages})
        assert r.status_code==401
