import json
import pytest
pytest.importorskip('fastapi')
import httpx
from fastapi.testclient import TestClient
from server.core_v2.app import create_app, PREFIX
from server.core_v2.providers import Providers, ProviderConfig


def setup(tmp_path, handler):
    provider = Providers(ProviderConfig(audio_base='http://127.0.0.1:7864/v1',audio_key='server-only-test-key'), transport=httpx.MockTransport(handler))
    app = create_app(tmp_path,admin_token='admin-'+'x'*40,providers=provider)
    user = app.state.store.register('voice-user','voice-password-123',app.state.store.invite(100))
    return app,user


def test_gateway_tts_prefers_login_pool_and_settles_once(tmp_path):
    def upstream(req):
        assert req.headers['Authorization']=='Bearer server-only-test-key'
        assert req.url.path=='/v1/audio/speech'
        assert json.loads(req.content)['model']=='doubao-voice/tts'
        return httpx.Response(200,content=b'ID3test-audio')
    app,user=setup(tmp_path,upstream)
    with TestClient(app) as client:
        body={'input':'你好','request_id':'tts-request-unique-123'}
        headers={'Authorization':'Bearer '+user['token']}
        r=client.post(PREFIX+'/voice/speech',json=body,headers=headers)
        assert r.status_code==200 and r.headers['content-type']=='audio/mpeg'
        assert r.headers['x-voice-source']=='rev-gateway'
        assert app.state.store.wallet(user['user_id'])=={'balance':99,'reserved':0}
        assert client.post(PREFIX+'/voice/speech',json=body,headers=headers).status_code==409


def test_gateway_asr_auth_pcm_wav_final_and_no_replay(tmp_path):
    calls=[]
    def upstream(req):
        calls.append(req)
        assert b'RIFF' in req.content and b'WAVE' in req.content
        assert b'doubao-voice/asr' in req.content
        return httpx.Response(200,json={'text':'打开任务列表'})
    app,user=setup(tmp_path,upstream)
    with TestClient(app) as client:
        def open_asr():
            return client.websocket_connect(PREFIX+'/voice/asr')
        auth={'token':user['token'],'request_id':'asr-request-unique-123'}
        with open_asr() as ws:
            ws.send_json(auth)
            ready=ws.receive_json()
            assert ready['partial_results'] is False and ready['source']=='rev-gateway'
            ws.send_bytes(b'\0'*3200)
            ws.send_json({'type':'finish'})
            assert ws.receive_json()=={'type':'asr.final','text':'打开任务列表'}
            assert ws.receive_json()['type']=='asr.finished'
        assert app.state.store.wallet(user['user_id'])=={'balance':99,'reserved':0}
        with open_asr() as ws:
            ws.send_json(auth)
            assert ws.receive_json()['type']=='error'
        assert len(calls)==1
        assert app.state.store.wallet(user['user_id'])=={'balance':99,'reserved':0}


def test_pre_dispatch_disconnect_refunds_and_server_error_holds(tmp_path):
    def upstream(req):return httpx.Response(500)
    app,user=setup(tmp_path,upstream)
    with TestClient(app) as client:
        with client.websocket_connect(PREFIX+'/voice/asr') as ws:
            ws.send_json({'token':user['token'],'request_id':'asr-disconnect-unique'})
            assert ws.receive_json()['type']=='asr.ready'
        # A fresh websocket waits for previous teardown before testing the wallet.
        with client.websocket_connect(PREFIX+'/voice/asr') as ws:
            ws.send_json({'token':user['token'],'request_id':'asr-failure-unique-123'})
            assert ws.receive_json()['type']=='asr.ready'
            ws.send_bytes(b'\0'*3200);ws.send_json({'type':'finish'})
            assert ws.receive_json()['error']=='audio_result_unknown'
        assert app.state.store.wallet(user['user_id'])=={'balance':70,'reserved':30}


def test_bad_pcm_does_not_call_gateway_or_hold_credits(tmp_path):
    def upstream(req):pytest.fail('invalid PCM reached upstream')
    app,user=setup(tmp_path,upstream)
    with TestClient(app) as client:
        with client.websocket_connect(PREFIX+'/voice/asr') as ws:
            ws.send_json({'token':user['token'],'request_id':'asr-invalid-frame-123'})
            ws.receive_json();ws.send_bytes(b'odd')
            assert ws.receive_json()['error']=='invalid_pcm_frame'
        assert app.state.store.wallet(user['user_id'])=={'balance':100,'reserved':0}


@pytest.mark.parametrize('code',['audio_busy','tts_login_required'])
def test_documented_pre_execution_gateway_failure_releases_reservation(tmp_path,code):
    def upstream(req):return httpx.Response(503,json={'error':{'code':code,'message':'private gateway detail'}})
    app,user=setup(tmp_path,upstream)
    with TestClient(app) as client:
        r=client.post(PREFIX+'/voice/speech',headers={'Authorization':'Bearer '+user['token']},json={'input':'你好','request_id':'rejected-before-execution'})
        assert r.status_code==503 and r.json()['error']==code
        assert 'private gateway detail' not in r.text
        assert app.state.store.wallet(user['user_id'])=={'balance':100,'reserved':0}


def test_legacy_asr_receive_deadline_releases_undispatched_audio(tmp_path, monkeypatch):
    import server.core_v2.gateway_voice as module
    monkeypatch.setattr(module, 'ASR_MAX_RECEIVE_SECONDS', .1)
    app, user = setup(tmp_path, lambda request: pytest.fail('uncompleted audio must not be sent'))
    with TestClient(app) as client:
        with client.websocket_connect(PREFIX+'/voice/asr') as ws:
            ws.send_json({'token':user['token'], 'request_id':'bounded-legacy-asr-id'})
            assert ws.receive_json()['type'] == 'asr.ready'
            ws.send_bytes(b'\0'*320)
            assert ws.receive_json()['error'] == 'voice_receive_timeout'
        assert app.state.store.wallet(user['user_id']) == {'balance':100,'reserved':0}
