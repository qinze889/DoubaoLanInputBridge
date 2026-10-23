"""Additive rev gateway routes. Install as server/routers/audio_stream.py.

Reuses the gateway's authorization, account pool, stable ASR device ID and
process-wide audio serial lock. No cookies or alternate identities are stored.
"""
import asyncio
import base64
import json
import time
import uuid
from contextlib import suppress

import aiohttp
import anyio
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from . import audio
from ..services import doubao_audio as source
from ..services import poolgateway

router = APIRouter()


@router.websocket('/v1/audio/transcriptions/stream')
async def transcriptions(ws: WebSocket):
    # This adapter is for the same-host voice service, never a cookie endpoint.
    if not ws.client or ws.client.host not in {'127.0.0.1', '::1'}:
        await ws.close(code=1008)
        return
    await ws.accept()
    session = sender = None
    guard = source.serial()
    locked = False
    received = 0
    ident = uuid.uuid4().hex
    started = time.time()
    upstream = key = ip = None
    try:
        request = Request({**ws.scope, 'type': 'http', 'method': 'GET', 'scheme': 'http'})
        if audio.client_ip(request) not in {'127.0.0.1', '::1'}:
            await ws.send_json({'type': 'error', 'error': 'audio_rejected'})
            return
        upstream, key, ip, failure = audio.resolve(request, 'doubao-voice/asr', 'asr', False)
        if failure:
            await ws.send_json({'type': 'error', 'error': 'audio_rejected'})
            return
        await guard.__aenter__()
        locked = True
        poolgateway.active_requests[ident] = started
        events = asyncio.Queue(maxsize=128)
        final = None
        failed = False
        def event(item):
            nonlocal failed
            if events.full():
                failed = True
                return
            events.put_nowait(item)
        session = source.RawAsrSession(on_event=event)
        session.did = source.device_id()  # Never rotate device identity after failure.
        if not await session.open():
            raise source.AudioError('ASR unavailable', 'asr_connection_failed', 503)
        async def send_results():
            nonlocal final, failed
            while True:
                item = await events.get()
                if item.get('event') == 'error':
                    failed = True
                    await ws.send_json({'type': 'error', 'error': 'asr_incomplete'})
                    return
                if item.get('event') == 'result' and item.get('text'):
                    if item.get('interim'):
                        await ws.send_json({'type': 'asr.partial', 'text': item['text'][:16000]})
                    else:
                        final = item['text'][:16000]
                if item.get('event') == 'session' and item.get('state') == 'finished':
                    return
        sender = asyncio.create_task(send_results())
        await ws.send_json({'type': 'asr.ready', 'partial_results': True, 'sample_rate': 16000})
        clock = time.monotonic()
        while True:
            message = await asyncio.wait_for(ws.receive(), 35)
            if message['type'] == 'websocket.disconnect':
                return
            if message.get('text') is not None:
                raw = message['text']
                if len(raw) > 256 or json.loads(raw).get('type') != 'finish':
                    raise source.AudioError('Invalid control', 'unsupported_voice_control', 400)
                break
            pcm = message.get('bytes') or b''
            if not 0 < len(pcm) <= 6400 or len(pcm) % 2:
                raise source.AudioError('Invalid PCM', 'invalid_pcm_frame', 400)
            received += len(pcm)
            if received > 30 * 32000 or received / 32000 > time.monotonic() - clock + 2:
                raise source.AudioError('Audio limit', 'audio_rate_exceeded', 400)
            session.feed(pcm)
            if failed:
                raise source.AudioError('ASR failed', 'asr_incomplete')
        # Flush only the tail; the bulk of the utterance was already sent live.
        tail = (-len(session._buf)) % source.FRAME_BYTES
        if tail:
            session.feed(b'\0' * tail)
        deadline = time.monotonic() + len(session._buf) / 32000 + 2
        while session._buf and time.monotonic() < deadline:
            await asyncio.sleep(.01)
        if session._buf:
            raise source.AudioError('Incomplete audio', 'asr_incomplete')
        await session.finish()
        await asyncio.wait_for(sender, 15)
        if failed or not final or not session.finished_evt.is_set():
            raise source.AudioError('No confirmed final', 'asr_incomplete')
        await ws.send_json({'type': 'asr.final', 'text': final})
        await ws.send_json({'type': 'asr.finished'})
        poolgateway._record(ident, upstream, key, ip, 'audio_transcriptions', 'doubao-voice/asr', 'doubao-voice/asr',
                            200, started, {'audio_seconds': received / 32000}, None, False, request.headers.get('user-agent'))
    except (source.AudioError, ValueError, asyncio.TimeoutError) as exc:
        with suppress(RuntimeError, WebSocketDisconnect):
            await ws.send_json({'type': 'error', 'error': exc.code if isinstance(exc, source.AudioError) else 'asr_incomplete'})
    except WebSocketDisconnect:
        pass
    finally:
        with anyio.CancelScope(shield=True):
            if sender:
                sender.cancel()
                await asyncio.gather(sender, return_exceptions=True)
            if session:
                await session.close()
            poolgateway.active_requests.pop(ident, None)
            if locked:
                await guard.__aexit__(None, None, None)
            with suppress(RuntimeError, WebSocketDisconnect):
                await ws.close()


def line(value):
    return (json.dumps(value, separators=(',', ':')) + '\n').encode()


@router.post('/v1/audio/speech/stream')
async def speech(request: Request):
    if not request.client or request.client.host not in {'127.0.0.1', '::1'} or audio.client_ip(request) not in {'127.0.0.1', '::1'}:
        return audio.error_response(source.AudioError('Loopback only', 'audio_rejected', 403))
    try:
        failure = audio.preauthorize(request)
        if failure:
            return failure
        raw = await audio.body_bytes(request, 64 * 1024)
        body = audio.SpeechIn.model_validate_json(raw)
        upstream, key, ip, failure = audio.resolve(request, body.model, 'tts', False)
        if failure:
            return failure
        credential = source.tts_credentials(upstream['id'])
        voice = source.DEFAULT_VOICE if body.voice in ('', 'alloy') else body.voice
        if voice not in source.VOICES or not .7 <= body.speed <= 2:
            raise source.AudioError('Unsupported voice', 'unsupported_voice', 400)
    except (source.AudioError, ValueError) as exc:
        return audio.error_response(exc if isinstance(exc, source.AudioError) else source.AudioError('Invalid body', 'invalid_speech_request', 400))
    ident = uuid.uuid4().hex
    started = time.time()
    async def generate():
        process = feeder = None
        complete = False
        total = 0
        guard = source.serial()
        locked = False
        try:
            await guard.__aenter__()
            locked = True
            poolgateway.active_requests[ident] = started
            wid = credential.get('web_id', '')
            params = {'version_code': 20800, 'language': credential.get('language') or 'zh', 'device_platform': 'web',
                      'aid': 497858, 'real_aid': 582478, 'pkg_type': 'release_version', 'device_id': wid, 'web_id': wid,
                      'tea_uuid': credential.get('tea_uuid', ''), 'use-olympus-account': 1, 'region': 'cn', 'sys_region': 'cn',
                      'samantha_web': 1, 'runtime': 'web', 'runtime_version': '2.22.3', 'pc_version': '0', 'fp': 'verify_' + wid,
                      'speaker': voice, 'format': 'aac', 'speech_rate': round((body.speed - 1) * 100), 'pitch': 0}
            headers = {'Cookie': credential['cookie'], 'Origin': 'https://www.doubao.com',
                       'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36'}
            url = 'wss://ws-samantha.doubao.com/samantha/audio/tts?' + source.urlencode(params)
            # Decode AAC incrementally. No temporary audio files and no network inputs to FFmpeg.
            process = await asyncio.create_subprocess_exec(source.shutil.which('ffmpeg') or 'ffmpeg', '-nostdin', '-hide_banner',
                '-loglevel', 'error', '-probesize', '32', '-analyzeduration', '0', '-protocol_whitelist', 'pipe,fd',
                '-f', 'aac', '-i', 'pipe:0', '-vn', '-f', 's16le', '-ar', '24000', '-ac', '1', '-flush_packets', '1', 'pipe:1',
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            async def feed():
                nonlocal complete
                count = 0
                try:
                    async with aiohttp.ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(total=90)) as client:
                        async with client.ws_connect(url, headers=headers, proxy=credential.get('proxy') or None,
                                                     max_msg_size=2*1024*1024, receive_timeout=30, timeout=5) as socket:
                            await socket.send_json({'event': 'text', 'text': body.input})
                            await socket.send_json({'event': 'finish'})
                            async for message in socket:
                                if message.type == aiohttp.WSMsgType.BINARY:
                                    count += len(message.data)
                                    if count > 10*1024*1024:
                                        raise source.AudioError('Audio limit', 'audio_result_too_large')
                                    process.stdin.write(message.data)
                                    await process.stdin.drain()
                                elif message.type == aiohttp.WSMsgType.TEXT:
                                    item = json.loads(message.data)
                                    if item.get('code') not in (None, 0, '0'):
                                        raise source.AudioError('TTS rejected', 'tts_session_rejected', 401)
                                    if item.get('event') == 'finish':
                                        complete = True
                                        break
                finally:
                    process.stdin.close()
            feeder = asyncio.create_task(feed())
            async with asyncio.timeout(95):
                yield line({'type': 'audio.ready', 'sample_rate': 24000, 'encoding': 'pcm_s16le'})
                while True:
                    chunk = await process.stdout.read(4096)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > 16*1024*1024:
                        raise source.AudioError('Audio limit', 'audio_result_too_large')
                    yield line({'type': 'audio.chunk', 'data': base64.b64encode(chunk).decode()})
                await feeder
                await process.wait()
                if not complete or not total or process.returncode:
                    raise source.AudioError('TTS incomplete', 'tts_incomplete')
                poolgateway._record(ident, upstream, key, ip, 'audio_speech', body.model, body.model, 200, started, {}, None, False, request.headers.get('user-agent'))
                yield line({'type': 'audio.finished'})
        except (source.AudioError, aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError) as exc:
            yield line({'type': 'error', 'error': exc.code if isinstance(exc, source.AudioError) else 'audio_result_unknown'})
        finally:
            with anyio.CancelScope(shield=True):
                if feeder:
                    feeder.cancel()
                    await asyncio.gather(feeder, return_exceptions=True)
                if process and process.returncode is None:
                    process.kill()
                    await process.wait()
                poolgateway.active_requests.pop(ident, None)
                if locked:
                    await guard.__aexit__(None, None, None)
    return StreamingResponse(generate(), media_type='application/x-ndjson', headers={'X-Accel-Buffering': 'no'})
