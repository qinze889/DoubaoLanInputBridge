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
            assert ws.receive_json()['partial_results'] is True
            ws.send_bytes(b'\0'*3200)
            assert ws.receive_json()=={'type':'asr.partial','text':'正在识别'}
            ws.send_json({'type':'finish'})
            assert ws.receive_json()=={'type':'asr.final','text':'最终识别结果'}
            assert ws.receive_json()['type']=='asr.finished'
        assert app.state.store.wallet(user['user_id'])=={'balance':99,'reserved':0}
        with client.websocket_connect(PREFIX+'/voice/asr/stream') as ws:
            ws.send_json(auth)
            assert ws.receive_json()['error']=='usage_already_submitted'
        assert app.state.store.wallet(user['user_id'])=={'balance':99,'reserved':0}
        assert len(links)==1
