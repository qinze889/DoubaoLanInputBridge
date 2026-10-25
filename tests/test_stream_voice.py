import asyncio
import base64
import json
import pytest
pytest.importorskip('fastapi')
import httpx
from fastapi.testclient import TestClient
from server.core_v2.app import create_app, PREFIX
from server.core_v2.providers import Providers, ProviderConfig


def setup(tmp_path, handler):
    provider=Providers(ProviderConfig(audio_base='http://127.0.0.1:7864/v1',audio_key='private-fixture-key',audio_stream=True),httpx.MockTransport(handler))
    app=create_app(tmp_path,admin_token='admin-'+'x'*40,providers=provider)
    user=app.state.store.register('stream-user','stream-password-123',app.state.store.invite(100))
    return app,user


def test_stream_audio_completion_and_truncation_accounting(tmp_path):
    events=[{'type':'audio.ready','sample_rate':24000,'encoding':'pcm_s16le'},
            {'type':'audio.chunk','data':base64.b64encode(b'\0'*4800).decode()}, {'type':'audio.finished'}]
    def upstream(req):
        assert req.url.path=='/v1/audio/speech/stream'
        assert req.headers['Authorization']=='Bearer private-fixture-key'
        return httpx.Response(200,content=''.join(json.dumps(e)+'\n' for e in events))
    app,user=setup(tmp_path,upstream)
    headers={'Authorization':'Bearer '+user['token']}
    with TestClient(app) as client:
        assert client.get(PREFIX+'/voice/capabilities',headers=headers).json()['partial_results']
        assert client.get(PREFIX+'/voice/capabilities').status_code==401
        body={'input':'实时音频','request_id':'streaming-speech-unique-id'}
        response=client.post(PREFIX+'/voice/speech/stream',json=body,headers=headers)
        output=[json.loads(line) for line in response.text.splitlines()]
        assert [e['type'] for e in output]==['audio.ready','audio.chunk','audio.finished']
        assert 'private-fixture-key' not in response.text
        assert app.state.store.wallet(user['user_id'])=={'balance':99,'reserved':0}
        assert client.post(PREFIX+'/voice/speech/stream',json=body,headers=headers).status_code==409
        events.pop()
        response=client.post(PREFIX+'/voice/speech/stream',json={**body,'request_id':'streaming-speech-truncated'},headers=headers)
        assert json.loads(response.text.splitlines()[-1])['error']=='audio_result_unknown'
        assert app.state.store.wallet(user['user_id'])=={'balance':98,'reserved':1}


def test_stream_pre_execution_busy_refunded(tmp_path):
    app,user=setup(tmp_path,lambda r:httpx.Response(200,content='{"type":"error","error":"audio_busy"}\n'))
    with TestClient(app) as client:
        r=client.post(PREFIX+'/voice/speech/stream',headers={'Authorization':'Bearer '+user['token']},json={'input':'你好','request_id':'stream-pre-execution-busy'})
        assert r.json()['error']=='audio_busy'
        assert app.state.store.wallet(user['user_id'])=={'balance':100,'reserved':0}


def test_stream_asr_partial_before_finish_and_no_duplicate_settlement(tmp_path, monkeypatch):
    import server.core_v2.stream_voice as module
    links=[]
    class Link:
        def __init__(self):
            self.events=asyncio.Queue()
            self.events.put_nowait({'type':'asr.ready'})
            self.pcm=[]
        async def send(self, value):
            if isinstance(value,bytes):
                self.pcm.append(value)
                self.events.put_nowait({'type':'asr.partial','text':'正在识别'})
            else:
                assert json.loads(value)['type']=='finish'
                self.events.put_nowait({'type':'asr.final','text':'最终识别结果'})
                self.events.put_nowait({'type':'asr.finished'})
        def __aiter__(self):return self
        async def __anext__(self):return json.dumps(await self.events.get())
    class Connection:
        async def __aenter__(self):
            self.link=Link();links.append(self.link);return self.link
        async def __aexit__(self,*args):pass
    def connect(url, **options):
        assert url=='ws://127.0.0.1:7864/v1/audio/transcriptions/stream'
        assert options['additional_headers']['Authorization']=='Bearer private-fixture-key'
        return Connection()
    monkeypatch.setattr(module,'connect',connect)
    app,user=setup(tmp_path,lambda r:pytest.fail('HTTP ASR must not be used'))
    auth={'token':user['token'],'request_id':'stream-asr-partial-test'}
    with TestClient(app) as client:
        with client.websocket_connect(PREFIX+'/voice/asr/stream') as ws:
            ws.send_json(auth)
            ws.send_bytes(b'\0'*3200)  # sent immediately after auth, before ready
            assert ws.receive_json()['partial_results'] is True
            assert ws.receive_json()=={'type':'asr.partial','text':'正在识别'}
            ws.send_json({'type':'finish'})
            assert ws.receive_json()=={'type':'asr.final','text':'最终识别结果'}
            assert ws.receive_json()['type']=='asr.finished'
        assert app.state.store.wallet(user['user_id'])=={'balance':99,'reserved':0}
        with client.websocket_connect(PREFIX+'/voice/asr/stream') as ws:
            ws.send_json(auth)
            assert ws.receive_json()['error']=='usage_already_submitted'
        assert app.state.store.wallet(user['user_id'])=={'balance':99,'reserved':0}
        assert len(links)==1 and links[0].pcm==[b'\0'*3200]


@pytest.mark.parametrize('code',['audio_busy','tts_login_required'])
def test_stream_http_pre_execution_failure_refunds_without_private_details(tmp_path,code):
    app,user=setup(tmp_path,lambda r:httpx.Response(503,json={'error':{'code':code,'message':'private upstream account detail'}}))
    with TestClient(app) as client:
        r=client.post(PREFIX+'/voice/speech/stream',headers={'Authorization':'Bearer '+user['token']},json={'input':'你好','request_id':'http-pre-execution-failure'})
        assert r.status_code==503 and r.json()['error']==code
        assert 'private upstream' not in r.text
        assert app.state.store.wallet(user['user_id'])=={'balance':100,'reserved':0}


def test_stream_asr_failures_log_code_without_audio_or_auth(tmp_path,monkeypatch,caplog):
    import server.core_v2.stream_voice as module
    class Link:
        def __init__(self):self.first=True
        def __aiter__(self):return self
        async def __anext__(self):
            if self.first:self.first=False;return json.dumps({'type':'asr.ready'})
            await asyncio.Future()
        async def send(self,data):pass
    class Connection:
        async def __aenter__(self):return Link()
        async def __aexit__(self,*args):pass
    monkeypatch.setattr(module,'connect',lambda *args,**kwargs:Connection())
    app,user=setup(tmp_path,lambda r:pytest.fail('HTTP ASR must not be used'))
    with TestClient(app) as client,caplog.at_level('WARNING'):
        with client.websocket_connect(PREFIX+'/voice/asr/stream') as ws:
            ws.send_json({'token':user['token'],'request_id':'invalid-pcm-log-unique'})
            assert ws.receive_json()['type']=='asr.ready'
            ws.send_bytes(b'x')
            assert ws.receive_json()['error']=='invalid_pcm_frame'
    assert 'voice_asr_end code=invalid_pcm_frame' in caplog.text
    assert user['token'] not in caplog.text and 'private-fixture-key' not in caplog.text


def test_coalesced_network_chunk_keeps_each_audio_record_and_total_accounting(tmp_path):
    payload=base64.b64encode(b'\0'*2400).decode()
    events=[{'type':'audio.ready','sample_rate':24000,'encoding':'pcm_s16le'}]+[{'type':'audio.chunk','data':payload} for _ in range(120)]+[{'type':'audio.finished'}]
    wire=''.join(json.dumps(e)+'\n' for e in events)
    assert len(wire)>128*1024
    app,user=setup(tmp_path,lambda req:httpx.Response(200,content=wire))
    with TestClient(app) as client:
        response=client.post(PREFIX+'/voice/speech/stream',headers={'Authorization':'Bearer '+user['token']},json={'input':'完整播报','request_id':'coalesced-audio-request-id'})
        result=[json.loads(line) for line in response.text.splitlines()]
        assert sum(item['type']=='audio.chunk' for item in result)==120
        assert result[-1]['type']=='audio.finished'
        assert app.state.store.wallet(user['user_id'])=={'balance':99,'reserved':0}
