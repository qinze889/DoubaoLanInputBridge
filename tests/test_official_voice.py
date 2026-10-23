import gzip
import json
import struct
import pytest
pytest.importorskip('fastapi')
from server.core_v2.voice import request_frame,response_frame
from server.core_v2.store import Fault


def test_official_asr_request_flags_and_round_trip_response():
    frame=request_frame(b'\x01\x00'*100,audio=True,last=True)
    assert frame[:4]==b'\x11\x22\x01\x00'
    assert gzip.decompress(frame[8:])==b'\x01\x00'*100
    payload=gzip.compress(json.dumps({'result':{'text':'测试'}}).encode())
    response=bytes([0x11,0x93,0x11,0])+struct.pack('>iI',-1,len(payload))+payload
    body,final=response_frame(response)
    assert final and body['result']['text']=='测试'


@pytest.mark.parametrize('frame',[b'',b'\x11\x90\x10\x00',b'\x11\xf0\x10\x00'+b'\0'*8,b'\x11\x90\x10\x00'+struct.pack('>I',100)+b'{}'])
def test_malformed_asr_frames_are_rejected(frame):
    with pytest.raises(Fault):response_frame(frame)


def test_asr_compression_bomb_is_bounded():
    payload=gzip.compress(b' '*2*1024*1024)
    frame=bytes([0x11,0x90,0x11,0])+struct.pack('>I',len(payload))+payload
    with pytest.raises(Fault):response_frame(frame)
