"""Authenticated WebRTC data channels: signaling only on the relay, no TURN.

Frames are limited to 16 KiB, reassembly to 32 MiB, and requests are never
replayed on a new connection after an ambiguous timeout.
"""
import asyncio
import base64
import concurrent.futures
import hashlib
import importlib.util
import json
import re
import threading
import time
import uuid

FRAME_BYTES = 16 * 1024
MAX_MESSAGE = 32 * 1024 * 1024
STUN = 'stun:stun.cloudflare.com:3478'


def available():
    return importlib.util.find_spec('aiortc') is not None


class FramedChannel:
    def __init__(self, channel, receive):
        self.channel, self.receive = channel, receive
        self.buffers = {}
        self.inflight = 0
        self.send_lock = asyncio.Lock()
        channel.on('message', self.on_message)

    def on_message(self, message):
        try:
            if isinstance(message, bytes):
                if len(message) < 33 or len(message) > FRAME_BYTES + 33:
                    raise ValueError('frame')
                ident = message[1:33].decode('ascii')
                expected, body, started = self.buffers[ident]
                if message[:1] != b'D' or len(body) + len(message) - 33 > expected:
                    raise ValueError('size')
                body.extend(message[33:])
                return
            if len(message) > 512:
                raise ValueError('control')
            control = json.loads(message)
            ident = control['id']
            if not re.fullmatch(r'[a-f0-9]{32}', ident):
                raise ValueError('id')
            if control['type'] == 'start':
                size = int(control['bytes'])
                now = time.monotonic()
                self.buffers = {k: v for k, v in self.buffers.items() if now - v[2] < 90}
                if ident in self.buffers or len(self.buffers) >= 2 or not 0 < size <= MAX_MESSAGE:
                    raise ValueError('limits')
                if sum(v[0] for v in self.buffers.values()) + size > MAX_MESSAGE:
                    raise ValueError('budget')
                self.buffers[ident] = (size, bytearray(), now)
            elif control['type'] == 'end':
                size, body, _ = self.buffers.pop(ident)
                if len(body) != size:
                    raise ValueError('incomplete')
                result = json.loads(body)
                if result.get('id') != ident:
                    raise ValueError('mismatch')
                if self.inflight >= 2:
                    raise ValueError('too many requests')
                self.inflight += 1
                asyncio.create_task(self.deliver(result))
            else:
                raise ValueError('control')
        except (ValueError, KeyError, TypeError, UnicodeError):
            self.buffers.clear()
            self.channel.close()

    async def deliver(self, result):
        try:
            await self.receive(result)
        finally:
            self.inflight -= 1

    async def send(self, value):
        data = json.dumps(value, ensure_ascii=True, separators=(',', ':')).encode()
        if len(data) > MAX_MESSAGE:
            raise ValueError('单次 P2P 内容超过上限')
        ident = value['id']
        async with self.send_lock:
            if self.channel.readyState != 'open':
                raise ConnectionError('P2P 直连已断开')
            self.channel.send(json.dumps({'type': 'start', 'id': ident, 'bytes': len(data)}))
            for offset in range(0, len(data), FRAME_BYTES):
                deadline = time.monotonic() + 30
                while self.channel.bufferedAmount > 512 * 1024:
                    if self.channel.readyState != 'open' or time.monotonic() > deadline:
                        raise ConnectionError('P2P 连接发送超时')
                    await asyncio.sleep(.01)
                self.channel.send(b'D' + ident.encode() + data[offset:offset + FRAME_BYTES])
            self.channel.send(json.dumps({'type': 'end', 'id': ident}))


class RTCBridge:
    def __init__(self, execute=None, stun=STUN):
        if not available():
            raise ValueError('当前安装包缺少 P2P 组件，请安装完整版本')
        self.execute = execute
        self.stun = stun
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.peers = set()
        self.links = {}
        self.connect_lock = asyncio.Lock()
        self.watchdogs = set()
        self.status = {'available': True, 'connections': 0, 'route': 'direct', 'error': ''}
        self.closed = False

    def wait(self, coroutine, timeout=45):
        if self.closed:
            coroutine.close()
            raise ConnectionError('P2P 已关闭')
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        try:
            return future.result(timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise TimeoutError('P2P 打洞超时，请切换固定公网或 CF 隧道') from None

    def connection(self):
        from aiortc import RTCPeerConnection, RTCConfiguration, RTCIceServer
        if len(self.peers) >= 8:
            raise ValueError('P2P 连接数量已达上限')
        pc = RTCPeerConnection(RTCConfiguration(iceServers=[RTCIceServer(urls=self.stun)] if self.stun else []))
        self.peers.add(pc)
        async def expire_unconnected():
            await asyncio.sleep(25)
            if pc.connectionState not in ('connected', 'closed'):
                self.peers.discard(pc)
                await pc.close()
        task = asyncio.create_task(expire_unconnected())
        self.watchdogs.add(task)
        task.add_done_callback(self.watchdogs.discard)
        @pc.on('connectionstatechange')
        async def changed():
            self.status['connections'] = sum(p.connectionState == 'connected' for p in self.peers)
            if pc.connectionState in ('failed', 'closed'):
                self.peers.discard(pc)
                if pc.connectionState != 'closed':
                    await pc.close()
        return pc

    async def _answer(self, offer, execute=None):
        from aiortc import RTCSessionDescription
        if offer.get('type') != 'offer' or not isinstance(offer.get('sdp'), str) or len(offer['sdp']) > 65536:
            raise ValueError('无效的 P2P 握手')
        if '\nm=audio ' in offer['sdp'] or '\nm=video ' in offer['sdp']:
            raise ValueError('P2P 仅支持文件和文字数据通道')
        pc = self.connection()
        executor = execute or self.execute
        accepted = False
        @pc.on('datachannel')
        def channel_open(channel):
            nonlocal accepted
            if accepted or channel.label != 'shengjian' or not channel.ordered or channel.maxRetransmits is not None or channel.maxPacketLifeTime is not None:
                channel.close()
                return
            accepted = True
            async def receive(job):
                if not executor:
                    channel.close()
                    return
                try:
                    result = await asyncio.to_thread(executor, job)
                    await framed.send({'id': job['id'], 'response': result})
                except (ValueError, KeyError, OSError, RuntimeError):
                    payload = {'ok': False, 'error': 'P2P 请求失败，请在电脑确认结果后再发送'}
                    try:
                        await framed.send({'id': job['id'], 'response': {'status': 400, 'content_type': 'application/json', 'body': base64.b64encode(json.dumps(payload).encode()).decode()}})
                    except Exception:
                        channel.close()
            framed = FramedChannel(channel, receive)
        try:
            await pc.setRemoteDescription(RTCSessionDescription(sdp=offer['sdp'], type='offer'))
            await pc.setLocalDescription(await pc.createAnswer())
            return {'type': pc.localDescription.type, 'sdp': pc.localDescription.sdp}
        except BaseException:
            self.peers.discard(pc)
            await pc.close()
            raise

    def answer(self, offer, execute=None):
        return self.wait(self._answer(offer, execute))

    async def _link(self, key, signal):
        from aiortc import RTCSessionDescription
        old = self.links.get(key)
        if old and old['pc'].connectionState == 'connected' and old['channel'].readyState == 'open':
            return old
        if old:
            await old['pc'].close()
        pc = self.connection()
        channel = pc.createDataChannel('shengjian', ordered=True)
        opened = self.loop.create_future()
        pending = {}
        @channel.on('open')
        def on_open():
            if not opened.done(): opened.set_result(True)
        @channel.on('close')
        def on_close():
            for future in list(pending.values()):
                if not future.done(): future.set_exception(ConnectionError('P2P 已断开，结果可能未知，请确认后再发送'))
        async def receive(result):
            future = pending.get(result.get('id'))
            if future and not future.done() and 'response' in result:
                future.set_result(result['response'])
        framed = FramedChannel(channel, receive)
        try:
            await pc.setLocalDescription(await pc.createOffer())
            answer = await asyncio.to_thread(signal, {'sdp': pc.localDescription.sdp, 'type': 'offer'})
            await pc.setRemoteDescription(RTCSessionDescription(**answer))
            await asyncio.wait_for(opened, 20)
            link = {'pc': pc, 'channel': channel, 'framed': framed, 'pending': pending, 'lock': asyncio.Lock()}
            self.links[key] = link
            return link
        except BaseException:
            self.peers.discard(pc)
            await pc.close()
            raise

    async def _request(self, key, signal, job):
        async with self.connect_lock:
            link = await self._link(key, signal)
        async with link['lock']:
            ident = job['id']
            future = self.loop.create_future()
            link['pending'][ident] = future
            try:
                await link['framed'].send(job)
                return await asyncio.wait_for(future, 90)
            finally:
                link['pending'].pop(ident, None)

    def request(self, key, signal, job):
        return self.wait(self._request(key, signal, job), timeout=120)

    async def _close(self):
        for task in list(self.watchdogs): task.cancel()
        await asyncio.gather(*list(self.watchdogs), return_exceptions=True)
        self.watchdogs.clear()
        await asyncio.gather(*(p.close() for p in list(self.peers)), return_exceptions=True)
        self.peers.clear()
        self.links.clear()

    def close(self):
        if self.closed: return
        self.wait(self._close(), timeout=5)
        self.closed = True
        self.loop.call_soon_threadsafe(self.loop.stop)
        if threading.current_thread() is not self.thread:
            self.thread.join(timeout=2)
        if not self.thread.is_alive(): self.loop.close()
