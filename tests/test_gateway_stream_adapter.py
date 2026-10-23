"""Exercise the additive rev adapter without a gateway database or credentials."""
import asyncio
from contextlib import asynccontextmanager
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest
pytest.importorskip('aiohttp')
from fastapi import FastAPI
from fastapi.testclient import TestClient


def fixture(monkeypatch):
    package='fixture_rev_stream'
    for name in [package,package+'.routers',package+'.services']:
        mod=ModuleType(name);mod.__path__=[];monkeypatch.setitem(sys.modules,name,mod)
    active={};record=[];lifecycle=[]
    lock=asyncio.Lock()
    @asynccontextmanager
    async def serial():
        await lock.acquire();lifecycle.append('locked')
        try:yield
        finally:lifecycle.append('released');lock.release()
    class AudioError(Exception):
        def __init__(self,message,code='audio_upstream_error',status=502):self.code=code;self.status=status
    class Session:
        def __init__(self,on_event):self.emit=on_event;self._buf=bytearray();self.finished_evt=asyncio.Event();self.did=None
        async def open(self):assert self.did=='stable-device';lifecycle.append('opened');return True
        def feed(self,pcm):self.emit({'event':'result','interim':True,'text':'中间文字'})
        async def finish(self):
            self.emit({'event':'result','interim':False,'text':'最终文字'})
            self.finished_evt.set();self.emit({'event':'session','state':'finished'})
        async def close(self):await asyncio.sleep(0);lifecycle.append('closed')
    source=ModuleType(package+'.services.doubao_audio')
    source.serial=serial;source.RawAsrSession=Session;source.device_id=lambda:'stable-device';source.FRAME_BYTES=1280;source.AudioError=AudioError
    monkeypatch.setitem(sys.modules,source.__name__,source)
    gateway=ModuleType(package+'.services.poolgateway');gateway.active_requests=active;gateway._record=lambda *args:record.append(args)
    monkeypatch.setitem(sys.modules,gateway.__name__,gateway)
    audio=ModuleType(package+'.routers.audio')
    def resolve(request,*args):
        assert request.headers.get('authorization')=='Bearer scoped-fixture-key'
        return {'id':1},{'id':2},'127.0.0.1',None
    audio.resolve=resolve
    audio.client_ip=lambda request:request.client.host
    monkeypatch.setitem(sys.modules,audio.__name__,audio)
    path=Path(__file__).parents[1]/'server/gateway_stream/audio_stream.py'
    spec=importlib.util.spec_from_file_location(package+'.routers.audio_stream',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    app=FastAPI();app.include_router(module.router)
    return app,lifecycle,active,record


def test_gateway_streams_interim_and_closes_before_releasing_shared_lock(monkeypatch):
    app,lifecycle,active,record=fixture(monkeypatch)
    with TestClient(app,client=('127.0.0.1',1234)) as client:
        with client.websocket_connect('/v1/audio/transcriptions/stream',headers={'Authorization':'Bearer scoped-fixture-key'}) as ws:
            assert ws.receive_json()['partial_results']
            ws.send_bytes(b'\0'*1280)
            assert ws.receive_json()['type']=='asr.partial'
            ws.send_json({'type':'finish'})
            assert ws.receive_json()=={'type':'asr.final','text':'最终文字'}
            assert ws.receive_json()['type']=='asr.finished'
        assert lifecycle==['locked','opened','closed','released']
        assert not active and len(record)==1


def test_gateway_disconnect_closes_session_and_unblocks_next_utterance(monkeypatch):
    app,lifecycle,active,record=fixture(monkeypatch)
    with TestClient(app,client=('127.0.0.1',1234)) as client:
        with client.websocket_connect('/v1/audio/transcriptions/stream',headers={'Authorization':'Bearer scoped-fixture-key'}) as ws:
            assert ws.receive_json()['type']=='asr.ready'
            ws.send_bytes(b'\0'*1280)
            ws.receive_json()
        with client.websocket_connect('/v1/audio/transcriptions/stream',headers={'Authorization':'Bearer scoped-fixture-key'}) as ws:
            assert ws.receive_json()['type']=='asr.ready'
            ws.send_bytes(b'\0'*1280);ws.receive_json();ws.send_json({'type':'finish'})
            assert ws.receive_json()['type']=='asr.final';ws.receive_json()
        assert lifecycle==['locked','opened','closed','released']*2
        assert not active and len(record)==1
