import asyncio
import base64
from contextlib import asynccontextmanager
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
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


@pytest.mark.parametrize('pooled', [False, True])
def test_voice_requests_reuse_tcp_connection_and_close_on_shutdown(tmp_path, pooled):
    ports = []
    disconnected = threading.Event()
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *args): pass
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            ports.append(self.client_address[1])
            if self.path.endswith('/stream'):
                data = b'{"type":"audio.chunk","data":"AAA="}\n{"type":"audio.finished"}\n'
            else:
                data = b'ID3fixture'
            self.send_response(200)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        def finish(self):
            super().finish()
            disconnected.set()
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    provider = Providers(ProviderConfig(audio_base=f'http://127.0.0.1:{server.server_port}/v1', audio_key='fixture', audio_stream=True))
    if not pooled:
        @asynccontextmanager
        async def no_pool(): yield
        provider.voice_lifespan = no_pool
    app = create_app(tmp_path, admin_token='admin-'+'x'*40, providers=provider)
    user = app.state.store.register('pool-user', 'pool-password-123', app.state.store.invite(100))
    try:
        with TestClient(app) as client:
            for index in range(6):
                path = '/voice/speech' + ('/stream' if index % 2 else '')
                result = client.post(PREFIX+path, headers={'Authorization':'Bearer '+user['token']},
                                     json={'input':'复用连接', 'request_id':f'voice-pool-request-{index}'})
                assert result.status_code == 200
                if index % 2:
                    assert json.loads(result.text.splitlines()[-1])['type'] == 'audio.finished'
            assert len(ports) == 6 and len(set(ports)) == (1 if pooled else 6)
            if pooled:
                assert not disconnected.is_set()
            assert app.state.store.wallet(user['user_id']) == {'balance':94, 'reserved':0}
        assert disconnected.wait(2), 'app shutdown must close the pooled connection'
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_cancel_before_stream_body_closes_response_but_preserves_pool(tmp_path):
    from server.core_v2.stream_voice import streaming_speech
    closed = []
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            pytest.fail('body must not start after response headers are cancelled')
            yield b''
        async def aclose(self): closed.append(True)
    provider = Providers(ProviderConfig(audio_base='http://127.0.0.1:1/v1', audio_key='fixture', audio_stream=True),
                         httpx.MockTransport(lambda request: httpx.Response(200, stream=Stream())))
    app = create_app(tmp_path, admin_token='admin-'+'x'*40, providers=provider)
    user = app.state.store.register('cancel-user', 'cancel-password-123', app.state.store.invite(100))
    async def run():
        async with provider.voice_lifespan():
            client = provider._voice_client
            response = await streaming_speech(provider, app.state.store, user['user_id'],
                SimpleNamespace(input='不要重播', request_id='cancel-before-body-request'))
            async def send(message): raise asyncio.CancelledError()
            async def receive(): await asyncio.Future()
            with pytest.raises(asyncio.CancelledError):
                await response({'type':'http','asgi':{'spec_version':'2.4'}}, receive, send)
            assert closed == [True] and not client.is_closed
        assert client.is_closed
    try:
        asyncio.run(run())
        # The synthesis was dispatched: uncertain completion must not be retried or refunded.
        assert app.state.store.wallet(user['user_id']) == {'balance':99,'reserved':1}
    finally:
        app.state.store.close()


@pytest.mark.parametrize('trickle', [False, True])
def test_asr_receive_deadline_survives_trickle_and_refunds_only_unsent_audio(tmp_path, monkeypatch, trickle):
    import server.core_v2.stream_voice as module
    monkeypatch.setattr(module, 'ASR_MAX_RECEIVE_SECONDS', .15)
    closed = []
    class Link:
        def __init__(self): self.first = True
        def __aiter__(self): return self
        async def __anext__(self):
            if self.first:
                self.first = False
                return '{"type":"asr.ready"}'
            await asyncio.Future()
        async def send(self, value): pass
    class Connection:
        async def __aenter__(self): return Link()
        async def __aexit__(self, *args): closed.append(True)
    monkeypatch.setattr(module, 'connect', lambda *args, **kwargs: Connection())
    app, user = setup(tmp_path, lambda request: pytest.fail('unexpected HTTP'))
    with TestClient(app) as client:
        started = time.monotonic()
        with client.websocket_connect(PREFIX+'/voice/asr/stream') as ws:
            ws.send_json({'token':user['token'], 'request_id':'bounded-asr-receive-deadline'})
            assert ws.receive_json()['type'] == 'asr.ready'
            if trickle:
                for _ in range(3):
                    ws.send_bytes(b'\0'*320)
                    time.sleep(.02)
            assert ws.receive_json()['error'] == 'voice_receive_timeout'
        assert time.monotonic()-started < 2 and closed == [True]
        assert app.state.store.wallet(user['user_id']) == ({'balance':70,'reserved':30} if trickle else {'balance':100,'reserved':0})


@pytest.mark.parametrize('event', [[], {'type':'error','error':{}}, {'type':'error','error':[]}])
def test_malformed_audio_event_fails_cleanly_without_false_settlement(tmp_path, event):
    app, user = setup(tmp_path, lambda request: httpx.Response(200, content=json.dumps(event)+'\n'))
    with TestClient(app) as client:
        result = client.post(PREFIX+'/voice/speech/stream', headers={'Authorization':'Bearer '+user['token']},
                             json={'input':'验证异常', 'request_id':'invalid-audio-event-id'})
        assert result.status_code == 200 and result.json()['type'] == 'error'
        assert app.state.store.wallet(user['user_id']) == {'balance':99,'reserved':1}


def test_completed_audio_does_not_wait_indefinitely_for_http_eof(tmp_path):
    closed = []
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"type":"audio.chunk","data":"AAA="}\n{"type":"audio.finished"}\n'
            await asyncio.Future()
        async def aclose(self): closed.append(True)
    app, user = setup(tmp_path, lambda request: httpx.Response(200, stream=Stream()))
    with TestClient(app) as client:
        started = time.monotonic()
        result = client.post(PREFIX+'/voice/speech/stream', headers={'Authorization':'Bearer '+user['token']},
                             json={'input':'收尾验证', 'request_id':'bounded-audio-http-eof'})
        assert json.loads(result.text.splitlines()[-1])['type'] == 'audio.finished'
        assert time.monotonic()-started < 2 and closed == [True]
        assert app.state.store.wallet(user['user_id']) == {'balance':99,'reserved':0}


@pytest.mark.parametrize('failure', [httpx.ConnectTimeout, httpx.PoolTimeout])
def test_pre_dispatch_timeout_releases_reservation(tmp_path, failure):
    def upstream(request): raise failure('fixture connection never dispatched')
    app, user = setup(tmp_path, upstream)
    with TestClient(app) as client:
        result = client.post(PREFIX+'/voice/speech/stream', headers={'Authorization':'Bearer '+user['token']},
                             json={'input':'未发送', 'request_id':'timeout-before-dispatch'})
        assert result.status_code == 503 and result.json()['error'] == 'audio_connection_failed'
        assert app.state.store.wallet(user['user_id']) == {'balance':100,'reserved':0}
