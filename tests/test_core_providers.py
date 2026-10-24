import json
import secrets
import pytest
pytest.importorskip('fastapi')
import httpx
from fastapi.testclient import TestClient
from server.core_v2.app import PREFIX,create_app
from server.core_v2.providers import Providers,ProviderConfig


def setup(tmp_path,handler):
    provider=Providers(ProviderConfig(model_base='https://models.example.invalid/v1',model_key='isolated-upstream-key',text_model='test-text'),transport=httpx.MockTransport(handler))
    app=create_app(tmp_path,admin_token='test-admin-'+'x'*40,providers=provider)
    user=app.state.store.register('provider-user','isolated-password-123',app.state.store.invite(100))
    return app,user,provider


def request(client,user,**changes):
    payload={'model':'test-text','messages':[{'role':'user','content':'test'}],'max_tokens':50,**changes}
    return client.post(PREFIX+'/model/v1/chat/completions',headers={'Authorization':'Bearer '+user['token'],'X-Request-ID':'isolated-usage-id-123'},json=payload)


def test_model_credentials_stay_upstream_and_actual_usage_settles_once(tmp_path):
    def upstream(req):
        assert req.headers['Authorization']=='Bearer isolated-upstream-key'
        if req.url.path.endswith('/models'):return httpx.Response(200,json={'data':[{'id':'test-text'}]})
        return httpx.Response(200,json={'choices':[{'message':{'content':'完成'}}],'usage':{'total_tokens':5}})
    app,user,_=setup(tmp_path,upstream)
    with TestClient(app) as client:
        response=request(client,user)
        assert response.status_code==200 and response.json()['choices'][0]['message']['content']=='完成'
        assert app.state.store.wallet(user['user_id'])=={'balance':99,'reserved':0}
        assert request(client,user).status_code==409
        assert 'isolated-upstream-key' not in response.text


def test_missing_usage_holds_reservation_instead_of_inventing_cost(tmp_path):
    def upstream(req):
        return httpx.Response(200,json={'data':[{'id':'test-text'}]}) if req.method=='GET' else httpx.Response(200,json={'choices':[]})
    app,user,_=setup(tmp_path,upstream)
    with TestClient(app) as client:
        assert request(client,user).status_code==200
        assert app.state.store.wallet(user['user_id'])['reserved']>0


@pytest.mark.parametrize('structured',[False,True])
def test_concise_chat_policy_scoped_to_active_device_preserves_tools_and_full_output(tmp_path,structured):
    from server.core_v2.providers import RESPONSE_STYLE
    calls=[];complete_text='完整文稿内容。'*100
    def upstream(req):
        if req.method=='GET':return httpx.Response(200,json={'data':[{'id':'test-text'}]})
        calls.append(json.loads(req.content))
        return httpx.Response(200,json={'choices':[{'message':{'content':complete_text}}],'usage':{'total_tokens':5}})
    app,user,provider=setup(tmp_path,upstream);store=app.state.store
    if structured:provider.config.vision_model='test-text'
    devices=[store.enroll(user['user_id'],name,['tasks']) for name in ['chat','other']]
    for d in devices:store.authorize_device(user['user_id'],d['id'],['tasks'])
    task=store.create_task(user['user_id'],{'device_id':devices[0]['id'],'request_id':secrets.token_hex(16),'prompt':'详细写完整文稿','engine':'harness','assistant_chat':True})
    store.dispatch(devices[0]['id']);store.device_event(devices[0]['id'],task['id'],{'type':'task.state','state':'running'},'start')
    original='保留已有的工具权限规则'
    messages=[{'role':'system','content':[{'type':'text','text':original}] if structured else original},{'role':'user','content':'详细写完整文稿'}]
    tools=[{'type':'function','function':{'name':'write','parameters':{'type':'object','properties':{'content':{'type':'string'}}}}}]
    with TestClient(app) as client:
        for credential,expected in [(devices[0]['token'],True),(devices[1]['token'],False),(user['token'],False)]:
            result=client.post(PREFIX+'/model/v1/chat/completions',headers={'Authorization':'Bearer '+credential,'X-Request-ID':secrets.token_hex(16)},json={'model':'test-text','messages':messages,'tools':tools,'max_tokens':2048})
            assert result.status_code==200,result.text
            sent=calls[-1]
            first=sent['messages'][0]['content']
            assert (first[0]==messages[0]['content'][0] if structured else first.startswith(original))
            assert sent['messages'][-1]==messages[-1]
            instruction='\n'.join(p['text'] for p in first) if structured else first
            assert (RESPONSE_STYLE in instruction)==expected
            assert sent['tools']==tools and sent['max_tokens']==2048
            assert result.json()['choices'][0]['message']['content']==complete_text


def test_stream_usage_is_settled_after_complete_stream(tmp_path):
    def upstream(req):
        if req.method=='GET':return httpx.Response(200,json={'data':[{'id':'test-text'}]})
        assert json.loads(req.content)['stream_options']=={'include_usage':True}
        return httpx.Response(200,content=b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: {"choices":[],"usage":{"total_tokens":2}}\n\ndata: [DONE]\n\n')
    app,user,_=setup(tmp_path,upstream)
    with TestClient(app) as client:
        response=request(client,user,stream=True)
        assert '[DONE]' in response.text
        assert app.state.store.wallet(user['user_id'])=={'balance':99,'reserved':0}


@pytest.mark.parametrize('status,held',[(401,False),(429,False),(500,True)])
def test_upstream_failures_are_sanitized_and_uncertain_cost_is_held(tmp_path,status,held):
    def upstream(req):
        return httpx.Response(200,json={'data':[{'id':'test-text'}]}) if req.method=='GET' else httpx.Response(status,json={'error':'private upstream details'})
    app,user,_=setup(tmp_path,upstream)
    with TestClient(app) as client:
        response=request(client,user)
        assert response.status_code==502
        assert 'private upstream details' not in response.text
        assert (app.state.store.wallet(user['user_id'])['reserved']>0)==held


def test_unavailable_or_image_incompatible_model_never_dispatches(tmp_path):
    calls=[]
    def upstream(req):
        calls.append(req.method)
        return httpx.Response(200,json={'data':[{'id':'test-text'}]})
    app,user,_=setup(tmp_path,upstream)
    with TestClient(app) as client:
        assert request(client,user,model='not-listed').status_code==403
        assert request(client,user,messages=[{'role':'user','content':[{'type':'image_url','image_url':{'url':'data:image/png;base64,AA=='}}]}]).status_code==400
        assert calls==['GET']
        assert app.state.store.wallet(user['user_id'])=={'balance':100,'reserved':0}


def test_official_voice_is_explicitly_unconfigured(tmp_path):
    app,user,_=setup(tmp_path,lambda req:httpx.Response(200,json={'data':[{'id':'test-text'}]}))
    with TestClient(app) as client:
        response=client.post(PREFIX+'/voice/speech',headers={'Authorization':'Bearer '+user['token']},json={'input':'test','request_id':'isolated-speech-request'})
        assert response.status_code==503
        with client.websocket_connect(PREFIX+'/voice/asr') as ws:
            ws.send_json({'token':user['token'],'request_id':'isolated-asr-request'})
            assert ws.receive_json()=={'type':'error','error':'asr_provider_not_configured'}
        assert app.state.store.wallet(user['user_id'])=={'balance':100,'reserved':0}



def test_verified_voice_effort_is_opt_in_and_leaves_task_requests_unchanged(tmp_path):
    captured=[]
    def upstream(request):
        if request.method=='GET':return httpx.Response(200,json={'data':[{'id':'fixture-text'}]})
        captured.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':{'content':'好的'}}],'usage':{'total_tokens':2}})
    provider=Providers(ProviderConfig(model_base='http://127.0.0.1:1/v1',model_key='fixture',text_model='fixture-text',voice_effort='low'),httpx.MockTransport(upstream))
    app=create_app(tmp_path,admin_token='admin-'+'x'*40,providers=provider)
    identity=app.state.store.register('voice-effort-user','voice-effort-password',app.state.store.invite(100))
    with TestClient(app) as client:
        headers={'Authorization':'Bearer '+identity['token']}
        assert client.get(PREFIX+'/voice/capabilities',headers=headers).json()['reasoning_effort']=='low'
        body={'model':'fixture-text','messages':[{'role':'user','content':'你好'}],'max_tokens':64}
        assert client.post(PREFIX+'/model/v1/chat/completions',headers=headers,json={**body,'reasoning_effort':'high'}).status_code==400
        assert not captured
        assert client.post(PREFIX+'/model/v1/chat/completions',headers=headers,json={**body,'reasoning_effort':'low'}).status_code==200
        assert captured[-1]['reasoning_effort']=='low'
        assert client.post(PREFIX+'/model/v1/chat/completions',headers=headers,json=body).status_code==200
        assert 'reasoning_effort' not in captured[-1]


def test_active_harness_chat_gets_verified_low_effort_without_changing_other_clients(tmp_path):
    seen=[]
    def upstream(req):
        if req.method=='GET':return httpx.Response(200,json={'data':[{'id':'test-text'}]})
        seen.append(json.loads(req.content))
        return httpx.Response(200,content=b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: {"usage":{"total_tokens":1}}\n\ndata: [DONE]\n\n')
    app,user,provider=setup(tmp_path,upstream);provider.config.voice_effort='low'
    with TestClient(app) as c:
        store=app.state.store;device=store.enroll(user['user_id'],'desktop',['tasks']);store.authorize_device(user['user_id'],device['id'],['tasks'])
        t=store.create_task(user['user_id'],{'device_id':device['id'],'request_id':'low-profile-test-123','engine':'harness','prompt':'hello','assistant_chat':True})
        store.dispatch(device['id']);store.device_event(device['id'],t['id'],{'type':'task.state','state':'running'},'run')
        assert request(c,device,stream=True).status_code==200
        assert seen[-1]['reasoning_effort']=='low'
        r=c.post(PREFIX+'/model/v1/chat/completions',headers={'Authorization':'Bearer '+user['token'],'X-Request-ID':'user-low-profile-test-123'},json={'model':'test-text','messages':[{'role':'user','content':'hello'}],'max_tokens':50,'stream':True})
        assert r.status_code==200
        assert 'reasoning_effort' not in seen[-1]
