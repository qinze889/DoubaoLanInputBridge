"""Authenticated streaming rev audio bridge with explicit completion accounting."""
import asyncio
import base64
from contextlib import AsyncExitStack
import json
import math
import logging
import time
from urllib.parse import urlsplit, urlunsplit

import anyio
import httpx
from fastapi import WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from .store import Fault, digest
from .gateway_voice import ASR_MAX_RECEIVE_SECONDS, REFUNDABLE


class SpeechResponse(StreamingResponse):
    def __init__(self, *args, resources, **kwargs):
        super().__init__(*args, **kwargs)
        self.resources = resources

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            # Also covers disconnects before the body iterator starts.
            with anyio.CancelScope(shield=True):
                await self.resources.aclose()


def encoded(item):
    return (json.dumps(item, separators=(',', ':')) + '\n').encode()


def mount_stream_asr(app, store, provider):
    from .app import PREFIX
    @app.websocket(PREFIX + '/voice/asr/stream')
    async def asr(ws: WebSocket):
        await ws.accept()
        uid = usage = None
        sent = received = 0
        settled = False
        reserved = False
        tasks = []
        try:
            raw = await asyncio.wait_for(ws.receive_text(), 10)
            if len(raw) > 2048:
                raise Fault('invalid_auth')
            auth = json.loads(raw)
            token = auth['token']
            uid = store.authenticate(token)['user_id']
            ident = auth.get('request_id')
            if not isinstance(ident, str) or not 16 <= len(ident) <= 128:
                raise Fault('invalid_request_id')
            if not provider.config.audio_stream:
                raise Fault('streaming_voice_not_configured', 503)
            usage = 'asr-' + digest(uid + ':' + ident)
            store.reserve(uid, usage, 30, digest(ident))
            reserved = True
            endpoint = urlsplit(provider.config.audio_base)
            url = urlunsplit(('wss' if endpoint.scheme == 'https' else 'ws', endpoint.netloc,
                             endpoint.path + '/audio/transcriptions/stream', '', ''))
            async with connect(url, additional_headers={'Authorization': 'Bearer ' + provider.config.audio_key},
                               proxy=None, max_size=65536, open_timeout=10, close_timeout=2) as upstream:
                ready = asyncio.Event()
                final = None
                async def results():
                    nonlocal final, settled, sent
                    async for raw in upstream:
                        store.authenticate(token)
                        event = json.loads(raw)
                        if not isinstance(event, dict):
                            raise Fault('invalid_audio_event', 502)
                        kind = event.get('type')
                        if kind == 'error':
                            code = event.get('error')
                            if not isinstance(code, str):
                                code = 'audio_result_unknown'
                            if code in REFUNDABLE and not received:
                                sent = 0
                            raise Fault(code if code in REFUNDABLE else 'audio_result_unknown', 502)
                        if kind == 'asr.ready':
                            ready.set()
                            await ws.send_json({'type': kind, 'partial_results': True, 'sample_rate': 16000, 'source': 'rev-stream'})
                        elif kind == 'asr.partial':
                            await ws.send_json({'type': kind, 'text': str(event.get('text', ''))[:16000]})
                        elif kind == 'asr.final':
                            final = str(event.get('text', ''))[:16000]
                        elif kind == 'asr.finished':
                            if not final:
                                raise Fault('audio_result_unknown', 502)
                            store.settle(uid, usage, math.ceil(received / 32000))
                            settled = True
                            await ws.send_json({'type': 'asr.final', 'text': final})
                            await ws.send_json({'type': kind})
                            return
                    raise Fault('audio_result_unknown', 502)
                async def audio():
                    nonlocal sent, received
                    await asyncio.wait_for(ready.wait(), 20)
                    clock = time.monotonic()
                    while True:
                        remaining = ASR_MAX_RECEIVE_SECONDS - (time.monotonic() - clock)
                        if remaining <= 0:
                            raise Fault('voice_receive_timeout', 408)
                        try:
                            message = await asyncio.wait_for(ws.receive(), min(35, remaining))
                        except asyncio.TimeoutError:
                            raise Fault('voice_receive_timeout', 408) from None
                        store.authenticate(token)
                        if message['type'] == 'websocket.disconnect':
                            raise WebSocketDisconnect()
                        if message.get('text') is not None:
                            text = message['text']
                            control = json.loads(text) if len(text) <= 256 else None
                            if not isinstance(control, dict) or control.get('type') != 'finish':
                                raise Fault('unsupported_voice_control')
                            await upstream.send(text)
                            return
                        pcm = message.get('bytes') or b''
                        if not 0 < len(pcm) <= 6400 or len(pcm) % 2:
                            raise Fault('invalid_pcm_frame')
                        received += len(pcm)
                        if received > 30*32000 or received/32000 > time.monotonic()-clock+2:
                            raise Fault('audio_rate_exceeded', 429)
                        sent += len(pcm)
                        await upstream.send(pcm)
                reader = asyncio.create_task(results())
                writer = asyncio.create_task(audio())
                tasks = [reader, writer]
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    await task
                if writer in done:
                    await asyncio.wait_for(reader, 20)
        except (Fault, ValueError, KeyError, TypeError, asyncio.TimeoutError, WebSocketException, WebSocketDisconnect) as exc:
            logging.getLogger(__name__).log(logging.INFO if isinstance(exc,WebSocketDisconnect) else logging.WARNING,'voice_asr_end code=%s received_bytes=%s sent_bytes=%s settled=%s',exc.code if isinstance(exc,Fault) else type(exc).__name__,received,sent,settled)
            with anyio.CancelScope(shield=True):
                try:
                    await ws.send_json({'type': 'error', 'error': exc.code if isinstance(exc, Fault) else 'voice_connection_ended'})
                except (RuntimeError, WebSocketDisconnect):
                    pass
        finally:
            for task in tasks:
                task.cancel()
            with anyio.CancelScope(shield=True):
                await asyncio.gather(*tasks, return_exceptions=True)
                if uid and usage and not sent and not settled:
                    # reserve may have rejected a duplicate ID. Never settle another call.
                    if reserved:
                        store.settle(uid, usage, 0)
                try:
                    await ws.close()
                except (RuntimeError, WebSocketDisconnect):
                    pass


async def streaming_speech(provider, store, uid, body):
    if not provider.config.audio_stream:
        raise Fault('streaming_voice_not_configured', 503)
    units = math.ceil(len(body.input) / 100)
    store.reserve(uid, body.request_id, units, digest(body.input))
    resources = AsyncExitStack()
    try:
        client = await resources.enter_async_context(provider.audio_client())
        upstream = await client.send(client.build_request('POST', provider.config.audio_base + '/audio/speech/stream',
            headers={'Authorization': 'Bearer ' + provider.config.audio_key},
            json={'model': 'doubao-voice/tts', 'input': body.input, 'voice': 'alloy'}), stream=True)
        resources.push_async_callback(upstream.aclose)
        if upstream.status_code != 200:
            code = 'audio_rejected' if 400 <= upstream.status_code < 500 else 'audio_result_unknown'
            raw = bytearray()
            try:
                async for chunk in upstream.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 8192:
                        break
                value = json.loads(raw)
                known = value.get('error', {}).get('code')
                if known in REFUNDABLE:
                    code = known
            except (ValueError, AttributeError, TypeError, httpx.HTTPError):
                pass
            if code in REFUNDABLE:
                store.settle(uid, body.request_id, 0)
            raise Fault(code, 503 if code in {'audio_busy', 'tts_login_required'} else 502)
    except BaseException as exc:
        with anyio.CancelScope(shield=True):
            await resources.aclose()
        if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)):
            store.settle(uid, body.request_id, 0)
            raise Fault('audio_connection_failed', 503) from None
        if isinstance(exc, httpx.HTTPError):
            raise Fault('audio_result_unknown', 502) from None
        raise
    async def generate():
        total = 0
        complete = False
        import codecs
        decoder = codecs.getincrementaldecoder('utf-8')()
        pending = ''
        upstream_reason = ''
        try:
            chunks = upstream.aiter_bytes()
            async for chunk in chunks:
                pending += decoder.decode(chunk)
                while '\n' in pending:
                    raw, pending = pending.split('\n', 1)
                    if len(raw)>128*1024:
                        raise Fault('audio_response_too_large',502)
                    if not raw:
                        continue
                    item = json.loads(raw)
                    if not isinstance(item, dict):
                        raise Fault('invalid_audio_event', 502)
                    kind = item.get('type')
                    if kind == 'error':
                        code = item.get('error')
                        if not isinstance(code, str):
                            code = 'audio_result_unknown'
                        if code in REFUNDABLE | {'tts_incomplete','tts_session_rejected','audio_result_unknown','audio_result_too_large'}:
                            upstream_reason=code
                        if code in REFUNDABLE and not total:
                            store.settle(uid, body.request_id, 0)
                        raise Fault(code if code in REFUNDABLE else 'audio_result_unknown', 502)
                    if kind == 'audio.ready':
                        if item.get('sample_rate') != 24000 or item.get('encoding') != 'pcm_s16le':
                            raise Fault('invalid_audio_format', 502)
                        yield encoded(item)
                    elif kind == 'audio.chunk':
                        pcm = base64.b64decode(item['data'], validate=True)
                        total += len(pcm)
                        if not pcm or total > 16*1024*1024:
                            raise Fault('audio_response_too_large', 502)
                        yield encoded({'type': kind, 'data': item['data']})
                    elif kind == 'audio.finished':
                        if not total:
                            raise Fault('empty_audio_response', 502)
                        store.settle(uid, body.request_id, units)
                        complete = True
                        yield encoded({'type': kind})
                        # Consume HTTP EOF so the next sentence can reuse the
                        # connection. A malformed open-ended tail must not stall it.
                        try:
                            async with asyncio.timeout(.25):
                                trailing = 0
                                async for tail in chunks:
                                    trailing += len(tail)
                                    if trailing > 8192:
                                        break
                        except (asyncio.TimeoutError, httpx.HTTPError):
                            pass
                        return
                if len(pending)>128*1024:
                    raise Fault('audio_response_too_large',502)
            if not complete:
                raise Fault('audio_result_unknown', 502)
        except (Fault, httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            logging.getLogger(__name__).warning('voice_tts_end code=%s cause=%s pcm_bytes=%s',
                exc.code if isinstance(exc,Fault) else type(exc).__name__,upstream_reason or 'transport_or_parse',total)
            yield encoded({'type': 'error', 'error': exc.code if isinstance(exc, Fault) else 'audio_result_unknown'})
    return SpeechResponse(generate(), resources=resources, media_type='application/x-ndjson', headers={'X-Usage-ID': body.request_id, 'X-Accel-Buffering': 'no'})
