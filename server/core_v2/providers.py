"""Server-only model/voice credentials; bounded streaming and explicit usage states."""
import asyncio
import base64
from dataclasses import dataclass
import json
import math
import os
import secrets
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .store import Fault, digest, encode


@dataclass
class ProviderConfig:
    model_base: str = ''
    model_key: str = ''
    text_model: str = ''
    vision_model: str = ''
    voice_key: str = ''
    voice_effort: str = ''
    audio_base: str = ''
    audio_key: str = ''
    audio_stream: bool = False
    asr_resource: str = 'volc.seedasr.sauc.duration'
    tts_resource: str = 'seed-tts-2.0'
    speaker: str = ''
    token_credits: int = 1

    @classmethod
    def from_environment(cls):
        return cls(model_base=os.getenv('SHENGJIAN_MODEL_BASE_URL','').rstrip('/'), model_key=os.getenv('SHENGJIAN_MODEL_API_KEY',''),
                   text_model=os.getenv('SHENGJIAN_TEXT_MODEL',''), vision_model=os.getenv('SHENGJIAN_VISION_MODEL',''),
                   audio_base=os.getenv('SHENGJIAN_AUDIO_BASE_URL','').rstrip('/'), audio_key=os.getenv('SHENGJIAN_AUDIO_API_KEY',''),
                   audio_stream=os.getenv('SHENGJIAN_AUDIO_STREAM','')=='1',
                   voice_key=os.getenv('SHENGJIAN_DOUBAO_API_KEY',''), voice_effort=os.getenv('SHENGJIAN_VOICE_REASONING_EFFORT',''), speaker=os.getenv('SHENGJIAN_DOUBAO_SPEAKER',''),
                   asr_resource=os.getenv('SHENGJIAN_DOUBAO_ASR_RESOURCE','volc.seedasr.sauc.duration'),
                   tts_resource=os.getenv('SHENGJIAN_DOUBAO_TTS_RESOURCE','seed-tts-2.0'))


class Providers:
    def __init__(self, config, transport=None):
        self.config, self.transport = config, transport
        for endpoint in (config.model_base, config.audio_base):
            if not endpoint:
                continue
            url = urlsplit(endpoint)
            if url.username or url.password or url.query or url.fragment or not url.hostname or (url.scheme != 'https' and not (url.scheme == 'http' and url.hostname in {'127.0.0.1','localhost','::1'})):
                raise ValueError('Model endpoint must be HTTPS or loopback HTTP without URL credentials')
        if not 1 <= config.token_credits <= 10000:
            raise ValueError('Invalid credit rate')
        if config.voice_effort not in {'', 'low'}:
            raise ValueError('Voice effort must be empty or an upstream-verified low profile')
        self.cached_models = None
        self.models_at = 0
        self.discovery_lock = asyncio.Lock()

    def readiness(self):
        return {'models': bool(self.config.model_base and self.config.model_key and self.config.text_model),
                'voice': bool(self.config.audio_base and self.config.audio_key) or bool(self.config.voice_key and self.config.speaker),
                'asr': bool(self.config.audio_base and self.config.audio_key) or bool(self.config.voice_key),
                'tts': bool(self.config.audio_base and self.config.audio_key) or bool(self.config.voice_key and self.config.speaker),
                'streaming_asr': self.config.audio_stream, 'streaming_tts': self.config.audio_stream,
                'voice_source': 'rev-gateway' if self.config.audio_base and self.config.audio_key else 'official' if self.config.voice_key else 'unconfigured'}

    def client(self):
        return httpx.AsyncClient(transport=self.transport, timeout=httpx.Timeout(60,connect=10), trust_env=False,
                                 follow_redirects=False, limits=httpx.Limits(max_connections=16,max_keepalive_connections=8))

    async def models(self):
        if not self.readiness()['models']:
            raise Fault('model_provider_not_configured', 503)
        async with self.discovery_lock:
            if self.cached_models is not None and self.models_at > asyncio.get_running_loop().time()-60:
                return self.cached_models
            try:
                async with self.client() as client:
                    async with client.stream('GET',self.config.model_base+'/models',headers={'Authorization':'Bearer '+self.config.model_key}) as response:
                        if response.status_code != 200:
                            raise Fault('model_discovery_failed', 503)
                        chunks=bytearray()
                        async for chunk in response.aiter_bytes():
                            chunks.extend(chunk)
                            if len(chunks)>1024*1024:
                                raise Fault('model_directory_too_large', 502)
                        data=json.loads(chunks)
                        if not isinstance(data,dict) or not isinstance(data.get('data'),list):
                            raise Fault('invalid_model_directory',502)
            except (httpx.HTTPError, ValueError):
                raise Fault('model_discovery_failed', 503) from None
            ids={r['id'] for r in data.get('data',[]) if isinstance(r,dict) and isinstance(r.get('id'),str) and len(r['id'])<=256}
            selected={m for m in [self.config.text_model,self.config.vision_model] if m}
            if not selected <= ids:
                raise Fault('configured_model_not_available', 503)
            self.cached_models=[{'id':m,'object':'model','input_modalities':['text','image'] if m==self.config.vision_model else ['text']} for m in sorted(selected)]
            self.models_at=asyncio.get_running_loop().time()
            return self.cached_models

    def mount(self, app, store, user):
        from .app import PREFIX, Input
        class Speech(Input):
            input: str = Field(min_length=1,max_length=1000)
            request_id: str = Field(min_length=16,max_length=128)

        def principal(authorization: str | None = Header(default=None)):
            if not authorization or not authorization.startswith('Bearer '):
                raise Fault('unauthorized',401)
            token=authorization[7:]
            try:
                return store.authenticate(token)['user_id']
            except Fault:
                identity=store.authenticate(token,device=True)
                if 'tasks' not in json.loads(identity['grants']):
                    raise Fault('capability_not_granted',403)
                return identity['user_id']

        @app.get(PREFIX+'/models')
        @app.get(PREFIX+'/model/v1/models')
        async def directory(uid=Depends(principal)):
            return {'object':'list','data':await self.models()}

        @app.post(PREFIX+'/model/v1/chat/completions')
        async def complete(request: Request, uid=Depends(principal)):
            try:
                data=await request.json()
            except ValueError:
                raise Fault('invalid_json') from None
            if not isinstance(data,dict) or set(data)-{'model','messages','max_tokens','max_completion_tokens','temperature','stream','stream_options','tools','tool_choice','parallel_tool_calls','reasoning_effort'}:
                raise Fault('unsupported_model_request')
            models=await self.models()
            if data.get('model') not in {m['id'] for m in models}:
                raise Fault('model_not_allowed',403)
            if 'reasoning_effort' in data and (self.config.voice_effort != 'low' or data['reasoning_effort'] != 'low' or data['model'] != self.config.text_model):
                raise Fault('unsupported_reasoning_effort')
            messages=data.get('messages')
            if not isinstance(messages,list) or not 1<=len(messages)<=100 or any(not isinstance(m,dict) or m.get('role') not in {'system','developer','user','assistant','tool'} for m in messages):
                raise Fault('invalid_messages')
            if any(isinstance(m.get('content'),list) for m in messages) and data['model']!=self.config.vision_model:
                raise Fault('model_does_not_accept_images')
            maximum=data.get('max_completion_tokens',data.get('max_tokens',2048))
            if type(maximum) is not int or not 1<=maximum<=8192:
                raise Fault('invalid_max_tokens')
            if 'max_tokens' not in data and 'max_completion_tokens' not in data:
                data['max_tokens']=maximum
            for message in messages:
                if isinstance(message.get('content'),list):
                    for part in message['content']:
                        if not isinstance(part,dict):
                            raise Fault('invalid_image_content')
                        if part.get('type')=='image_url':
                            if not isinstance(part.get('image_url'),dict):
                                raise Fault('invalid_image_content')
                            image=part['image_url'].get('url','')
                            if not isinstance(image,str):
                                raise Fault('invalid_image_content')
                            if not image.startswith(('data:image/jpeg;base64,','data:image/png;base64,')):
                                raise Fault('inline_images_required')
            usage_id=request.headers.get('X-Request-ID') or secrets.token_hex(16)
            if not 16<=len(usage_id)<=128:
                raise Fault('invalid_request_id')
            reserve=math.ceil((len(encode(data).encode())+8192+maximum)/1000)*self.config.token_credits
            store.reserve(uid,usage_id,reserve,digest(encode(data)))
            headers={'Authorization':'Bearer '+self.config.model_key,'Content-Type':'application/json','X-Request-ID':usage_id}
            if data.get('stream'):
                data['stream_options']={'include_usage':True}
            def settle(usage):
                total=usage.get('total_tokens') if isinstance(usage,dict) else None
                if type(total) is int and total>=0:
                    store.settle(uid,usage_id,math.ceil(total/1000)*self.config.token_credits)
            client = self.client()
            try:
                upstream = await client.send(client.build_request('POST',self.config.model_base+'/chat/completions',headers=headers,json=data),stream=True)
            except httpx.ConnectError:
                await client.aclose()
                store.settle(uid,usage_id,0)
                raise Fault('model_connection_failed',503) from None
            except httpx.HTTPError:
                await client.aclose()
                raise Fault('model_result_unknown',502) from None
            if upstream.status_code != 200:
                if 400<=upstream.status_code<500:
                    store.settle(uid,usage_id,0)
                await upstream.aclose()
                await client.aclose()
                raise Fault('model_upstream_failed',502)
            async def generate():
                usage=None;pending='';done=False;received=0;buffer=bytearray()
                import codecs
                decoder=codecs.getincrementaldecoder('utf-8')()
                try:
                    async for chunk in upstream.aiter_bytes():
                        received+=len(chunk)
                        if received>16*1024*1024:
                            raise Fault('model_response_too_large',502)
                        if data.get('stream'):
                            pending+=decoder.decode(chunk)
                            if len(pending)>256*1024:
                                raise Fault('model_event_too_large',502)
                            while '\n' in pending:
                                line,pending=pending.split('\n',1)
                                if line.startswith('data: '):
                                    if line.strip()=='data: [DONE]':done=True
                                    else:
                                        try:
                                            item=json.loads(line[6:])
                                            if item.get('usage'):usage=item['usage']
                                        except ValueError:pass
                            yield chunk
                        else:
                            buffer.extend(chunk)
                    if not data.get('stream'):
                        result=json.loads(buffer)
                        settle(result.get('usage'))
                        yield encode(result).encode()
                    elif done:
                        settle(usage)
                    else:
                        yield b'data: {"error":{"message":"model_result_unknown"}}\n\n'
                except (httpx.HTTPError,ValueError,Fault):
                    yield b'data: {"error":{"message":"model_result_unknown"}}\n\n' if data.get('stream') else b'{"error":"model_result_unknown"}'
                finally:
                    import anyio
                    with anyio.CancelScope(shield=True):
                        await upstream.aclose()
                        await client.aclose()
            return StreamingResponse(generate(),media_type='text/event-stream' if data.get('stream') else 'application/json',headers={'X-Usage-ID':usage_id})

        @app.get(PREFIX+'/voice/capabilities')
        async def voice_capabilities(uid=Depends(user)):
            return {'partial_results': self.config.audio_stream, 'streaming_audio': self.config.audio_stream, 'early_audio': self.config.audio_stream,
                    'reasoning_effort': self.config.voice_effort or None,
                    'asr_path': '/voice/asr/stream' if self.config.audio_stream else '/voice/asr', 'sample_rate': 24000}

        @app.post(PREFIX+'/voice/speech/stream')
        async def stream_speech(body: Speech, uid=Depends(user)):
            from .stream_voice import streaming_speech
            return await streaming_speech(self, store, uid, body)

        @app.post(PREFIX+'/voice/speech')
        async def speech(body: Speech, uid=Depends(user)):
            if not self.readiness()['tts']:
                raise Fault('tts_provider_not_configured',503)
            if self.config.audio_base and self.config.audio_key:
                from .gateway_voice import gateway_speech
                return await gateway_speech(self, store, uid, body)
            units=math.ceil(len(body.input)/100)
            store.reserve(uid,body.request_id,units,digest(body.input))
            async def audio():
                completed=False
                try:
                    async with self.client() as client:
                        headers={'X-Api-Key':self.config.voice_key,'X-Api-Resource-Id':self.config.tts_resource,'X-Api-Request-Id':body.request_id}
                        data={'user':{'uid':uid},'req_params':{'text':body.input,'speaker':self.config.speaker,'audio_params':{'format':'pcm','sample_rate':24000}}}
                        async with client.stream('POST','https://openspeech.bytedance.com/api/v3/tts/unidirectional',headers=headers,json=data) as response:
                            if response.status_code!=200:
                                if 400<=response.status_code<500:store.settle(uid,body.request_id,0)
                                return
                            received=0
                            async for line in response.aiter_lines():
                                if not line:continue
                                if len(line)>2*1024*1024:raise Fault('tts_chunk_too_large',502)
                                result=json.loads(line.removeprefix('data:').strip())
                                code=result.get('code')
                                if code==20000000:
                                    completed=True;break
                                if code not in (0,None):raise Fault('tts_provider_error',502)
                                if result.get('data'):
                                    chunk=base64.b64decode(result['data'],validate=True)
                                    received+=len(chunk)
                                    if received>16*1024*1024:raise Fault('tts_response_too_large',502)
                                    yield chunk
                    if completed:store.settle(uid,body.request_id,units)
                except (httpx.HTTPError,ValueError,Fault):
                    return
            return StreamingResponse(audio(),media_type='audio/pcm',headers={'X-Audio-Sample-Rate':'24000','X-Usage-ID':body.request_id})
        from .voice import mount_asr
        if self.config.audio_base and self.config.audio_key:
            from .gateway_voice import mount_gateway_asr
            mount_gateway_asr(app, store, self)
            from .stream_voice import mount_stream_asr
            mount_stream_asr(app, store, self)
        else:
            mount_asr(app,store,self.config)
