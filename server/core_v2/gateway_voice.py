"""rev gateway audio adapter. Login cookies stay in the gateway account pool.

The current rev HTTP API returns completed utterances, not partial ASR or
streaming synthesis. Advertise that distinction to clients explicitly.
"""
import asyncio
import io
import json
import math
import time
import wave

import anyio
import httpx
from fastapi import WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from .store import Fault, digest

REFUNDABLE = {'audio_rejected', 'audio_connection_failed', 'audio_busy', 'tts_login_required'}


async def call(provider, path, **kwargs):
    try:
        async with provider.client() as client:
            async with client.stream('POST', provider.config.audio_base + path, timeout=httpx.Timeout(100, connect=10),
                                     headers={'Authorization': 'Bearer ' + provider.config.audio_key}, **kwargs) as response:
                if response.status_code != 200:
                    # Only documented pre-execution failures are disclosed or refunded.
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw)>8192:
                            break
                    try:
                        data=json.loads(raw)
                        code=data.get('error',{}).get('code')
                    except (ValueError,AttributeError):
                        code=None
                    if isinstance(code,str) and code in {'audio_busy','tts_login_required'}:
                        raise Fault(code,503)
                    raise Fault('audio_rejected' if 400 <= response.status_code < 500 else 'audio_result_unknown', 502)
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 16 * 1024 * 1024:
                        raise Fault('audio_response_too_large', 502)
                return bytes(body)
    except httpx.ConnectError:
        raise Fault('audio_connection_failed', 503) from None
    except httpx.HTTPError:
        raise Fault('audio_result_unknown', 502) from None


async def gateway_speech(provider, store, uid, body):
    units = math.ceil(len(body.input) / 100)
    store.reserve(uid, body.request_id, units, digest(body.input))
    try:
        audio = await call(provider, '/audio/speech', json={
            'model': 'doubao-voice/tts', 'input': body.input, 'voice': 'alloy', 'response_format': 'mp3'})
        if not audio:
            raise Fault('empty_audio_response', 502)
        store.settle(uid, body.request_id, units)
        return Response(audio, media_type='audio/mpeg', headers={'X-Usage-ID': body.request_id, 'X-Voice-Source': 'rev-gateway'})
    except Fault as error:
        if error.code in REFUNDABLE:
            store.settle(uid, body.request_id, 0)
        raise


def mount_gateway_asr(app, store, provider):
    from .app import PREFIX

    @app.websocket(PREFIX + '/voice/asr')
    async def asr(ws: WebSocket):
        await ws.accept()
        uid = usage_id = None
        dispatched = False
        settled = False
        reserved = False
        try:
            raw = await asyncio.wait_for(ws.receive_text(), 10)
            if len(raw) > 2048:
                raise Fault('invalid_auth')
            auth = json.loads(raw)
            token = auth['token']
            uid = store.authenticate(token)['user_id']
            request_id = auth.get('request_id')
            if not isinstance(request_id, str) or not 16 <= len(request_id) <= 128:
                raise Fault('invalid_request_id')
            # Scope caller IDs by account and operation; no reconnect can replay a paid request.
            usage_id = 'asr-' + digest(uid + ':' + request_id)
            store.reserve(uid, usage_id, 30, digest(request_id))
            reserved = True
            await ws.send_json({'type': 'asr.ready', 'sample_rate': 16000, 'channels': 1,
                                'encoding': 'pcm_s16le', 'partial_results': False,
                                'max_utterance_seconds': 30, 'source': 'rev-gateway'})
            pcm = bytearray()
            started = time.monotonic()
            while True:
                message = await asyncio.wait_for(ws.receive(), 35)
                store.authenticate(token)
                if message['type'] == 'websocket.disconnect':
                    return
                text = message.get('text')
                if text is not None:
                    if len(text) > 256 or json.loads(text).get('type') != 'finish':
                        raise Fault('unsupported_voice_control')
                    break
                data = message.get('bytes') or b''
                if not 0 < len(data) <= 6400 or len(data) % 2:
                    raise Fault('invalid_pcm_frame')
                if len(pcm) + len(data) > 30 * 32000:
                    raise Fault('utterance_too_long')
                if (len(pcm) + len(data)) / 32000 > time.monotonic() - started + 2:
                    raise Fault('audio_rate_exceeded', 429)
                pcm.extend(data)
            if not pcm:
                raise Fault('empty_audio')
            output = io.BytesIO()
            with wave.open(output, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(pcm)
            dispatched = True
            result = json.loads(await call(provider, '/audio/transcriptions',
                data={'model': 'doubao-voice/asr', 'response_format': 'json'},
                files={'file': ('utterance.wav', output.getvalue(), 'audio/wav')}))
            if not isinstance(result, dict) or not isinstance(result.get('text'), str):
                raise Fault('invalid_asr_response', 502)
            # A session revoked while the upstream was busy must receive no transcript.
            store.authenticate(token)
            store.settle(uid, usage_id, math.ceil(len(pcm) / 32000))
            settled = True
            await ws.send_json({'type': 'asr.final', 'text': result['text'][:16000]})
            await ws.send_json({'type': 'asr.finished'})
        except (Fault, ValueError, KeyError, TypeError, WebSocketDisconnect, asyncio.TimeoutError) as error:
            if isinstance(error, Fault) and error.code in REFUNDABLE:
                dispatched = False
            with anyio.CancelScope(shield=True):
                try:
                    await ws.send_json({'type': 'error', 'error': error.code if isinstance(error, Fault) else 'voice_connection_ended'})
                except (RuntimeError, WebSocketDisconnect):
                    pass
        finally:
            if reserved and not dispatched and not settled:
                store.settle(uid, usage_id, 0)
            with anyio.CancelScope(shield=True):
                try:
                    await ws.close()
                except (RuntimeError, WebSocketDisconnect):
                    pass
