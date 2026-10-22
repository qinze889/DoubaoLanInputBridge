"""Real ICE/DTLS/SCTP transfers, not mocked WebRTC success states."""
import base64
import hashlib
import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from rtc_bridge import RTCBridge, FramedChannel, MAX_MESSAGE


def test_direct_channel_unicode_large_binary_and_single_handshake():
    signals, executions = [], []
    payload = bytes(range(256)) * 4097
    def execute(job):
        data = base64.b64decode(job['body'])
        executions.append(job['id'])
        return {'status': 200, 'body': base64.b64encode(data).decode(), 'content_type': 'application/octet-stream'}
    incoming, outgoing = RTCBridge(execute, stun=None), RTCBridge(stun=None)
    def signal(offer):
        signals.append(len(json.dumps(offer)))
        assert 'm=application' in offer['sdp']
        assert 'typ relay' not in offer['sdp']
        return incoming.answer(offer)
    try:
        def transfer(content):
            return outgoing.request('receiver', signal, {'id': uuid.uuid4().hex, 'method': 'POST', 'path': '/send', 'body': base64.b64encode(content).decode()})
        with ThreadPoolExecutor(2) as pool:
            large, text = list(pool.map(transfer, [payload, '中文、emoji 😀'.encode()]))
        assert hashlib.sha256(base64.b64decode(large['body'])).digest() == hashlib.sha256(payload).digest()
        assert base64.b64decode(text['body']).decode() == '中文、emoji 😀'
        assert len(signals) == 1 and len(executions) == 2
        assert incoming.status['connections'] == outgoing.status['connections'] == 1
        assert incoming.status['route'] == 'direct'
    finally:
        outgoing.close(); incoming.close()
    assert not outgoing.thread.is_alive() and not incoming.thread.is_alive()


def test_invalid_or_media_offer_does_not_allocate_connection():
    rtc = RTCBridge(stun=None)
    try:
        for offer in ({'type': 'answer', 'sdp': ''}, {'type': 'offer', 'sdp': 'v=0\nm=audio 9 UDP/TLS/RTP/SAVPF 111\n'}):
            with pytest.raises(ValueError): rtc.answer(offer)
        assert not rtc.peers
    finally: rtc.close()


def test_reassembly_limits_close_malformed_channel():
    class Channel:
        closed = False
        def on(self, *args): pass
        def close(self): self.closed = True
    channel = Channel()
    framed = FramedChannel(channel, None)
    framed.on_message(json.dumps({'type': 'start', 'id': 'a'*32, 'bytes': MAX_MESSAGE}))
    framed.on_message(json.dumps({'type': 'start', 'id': 'b'*32, 'bytes': 1}))
    assert channel.closed and not framed.buffers
