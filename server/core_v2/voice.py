"""Official Doubao V3 streaming ASR. PCM is never persisted or logged."""
import asyncio
import gzip
import json
import math
import secrets
import struct
import time
import zlib

import anyio
from fastapi import WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from .store import Fault, digest

ASR_URL = 'wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async'


def request_frame(payload, audio=False, last=False):
    body = gzip.compress(payload if audio else json.dumps(payload).encode())
    header = bytes([0x11, (0x20 if audio else 0x10) | (2 if last else 0), 0x01 if audio else 0x11, 0])
    return header+struct.pack('>I',len(body))+body


def response_frame(raw):
    if not isinstance(raw,bytes) or len(raw)<8 or raw[0]>>4!=1:
        raise Fault('invalid_asr_frame',502)
    offset=(raw[0]&15)*4
    kind,flags=raw[1]>>4,raw[1]&15
    if offset<4 or offset>len(raw)-4:
        raise Fault('invalid_asr_header',502)
    if kind==15:
        raise Fault('asr_provider_error',502)
    if kind!=9:
        raise Fault('unsupported_asr_frame',502)
    if flags&1:
        offset+=4
    if offset+4>len(raw):
        raise Fault('truncated_asr_frame',502)
    size=struct.unpack('>I',raw[offset:offset+4])[0]
    payload=raw[offset+4:]
    if size!=len(payload) or size>1024*1024:
        raise Fault('invalid_asr_size',502)
    if raw[2]&15==1:
        decoder=zlib.decompressobj(16+zlib.MAX_WBITS)
        payload=decoder.decompress(payload,1024*1024+1)
        if len(payload)>1024*1024 or decoder.unconsumed_tail or not decoder.eof:
            raise Fault('asr_response_too_large',502)
    elif raw[2]&15:
        raise Fault('unsupported_asr_compression',502)
    return json.loads(payload),bool(flags&2)


def mount_asr(app,store,config):
    from .app import PREFIX

    @app.websocket(PREFIX+'/voice/asr')
    async def asr(ws: WebSocket):
        await ws.accept()
        usage_id=None;uid=None;received=0;reserved=0;completed=False;reader=None
        try:
            auth=await asyncio.wait_for(ws.receive_text(),10)
            if len(auth)>2048:raise Fault('invalid_auth')
            auth=json.loads(auth)
            token=auth['token'];uid=store.authenticate(token)['user_id']
            request_id=auth.get('request_id')
            if not isinstance(request_id,str) or not 16<=len(request_id)<=128:
                raise Fault('invalid_request_id')
            if not config.voice_key:
                raise Fault('asr_provider_not_configured',503)
            usage_id='asr-'+digest(uid+':'+request_id)
            # Reserve the bounded session once; only a completed upstream result settles usage.
            store.reserve(uid,usage_id,1800,digest(request_id))
            reserved=1800
            headers={'X-Api-Key':config.voice_key,'X-Api-Resource-Id':config.asr_resource,'X-Api-Connect-Id':secrets.token_hex(16)}
            async with connect(ASR_URL,additional_headers=headers,proxy=None,max_size=1024*1024,open_timeout=10,close_timeout=3) as upstream:
                await upstream.send(request_frame({'user':{'uid':uid},'audio':{'format':'pcm','codec':'raw','rate':16000,'bits':16,'channel':1},
                    'request':{'model_name':'bigmodel','enable_itn':True,'enable_punc':True,'show_utterances':True}}))
                seen=set()
                async def receive():
                    nonlocal completed
                    async for raw in upstream:
                        result,last=response_frame(raw)
                        if result.get('code',0) not in (0,20000000):raise Fault('asr_provider_error',502)
                        content=result.get('result') or {}
                        if isinstance(content,list):content=content[-1] if content else {}
                        text=content.get('text','')
                        if text:await ws.send_json({'type':'asr.partial','text':text[:16000]})
                        for utterance in content.get('utterances',[]):
                            ident=(utterance.get('start_time'),utterance.get('end_time'),utterance.get('text'))
                            if utterance.get('definite') and utterance.get('text') and ident not in seen:
                                seen.add(ident)
                                await ws.send_json({'type':'asr.final','text':utterance['text'][:16000]})
                        if last:
                            completed=True
                            await ws.send_json({'type':'asr.finished'})
                            return
                reader=asyncio.create_task(receive())
                await ws.send_json({'type':'asr.ready','sample_rate':16000,'channels':1,'encoding':'pcm_s16le'})
                started=time.monotonic()
                while time.monotonic()-started<1800:
                    message=await asyncio.wait_for(ws.receive(),35)
                    store.authenticate(token)
                    if message['type']=='websocket.disconnect':break
                    if message.get('text'):
                        if len(message['text'])>256:raise Fault('voice_control_too_large')
                        if json.loads(message['text']).get('type')!='finish':raise Fault('unsupported_voice_control')
                        await upstream.send(request_frame(b'',audio=True,last=True))
                        await asyncio.wait_for(reader,15)
                        break
                    data=message.get('bytes') or b''
                    if not 0<len(data)<=6400 or len(data)%2:
                        raise Fault('invalid_pcm_frame')
                    if (received+len(data))/32000>time.monotonic()-started+2:
                        raise Fault('audio_rate_exceeded',429)
                    if received+len(data)>reserved*32000:
                        raise Fault('voice_session_too_long')
                    received+=len(data)
                    await upstream.send(request_frame(data,audio=True))
                    if reader.done():
                        await reader
                        break
                if completed:
                    store.settle(uid,usage_id,math.ceil(received/32000))
        except (Fault, ValueError, KeyError, WebSocketException, WebSocketDisconnect, asyncio.TimeoutError) as error:
            with anyio.CancelScope(shield=True):
                try:
                    await ws.send_json({'type':'error','error':error.code if isinstance(error,Fault) else 'voice_connection_ended'})
                except (RuntimeError,WebSocketDisconnect):pass
        finally:
            if reader:
                reader.cancel()
                with anyio.CancelScope(shield=True):await asyncio.gather(reader,return_exceptions=True)
            with anyio.CancelScope(shield=True):
                try:await ws.close()
                except (RuntimeError,WebSocketDisconnect):pass
