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
