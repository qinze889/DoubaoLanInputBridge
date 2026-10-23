"""Isolated browser fixture. Never imported by the deployed service."""
from pathlib import Path
import sys
import asyncio
import json
import base64
import os
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import httpx
import uvicorn
from server.core_v2.app import create_app
from server.core_v2.providers import Providers,ProviderConfig

class Stream(httpx.AsyncByteStream):
    def __init__(self, audio=False): self.audio=audio
    async def __aiter__(self):
        if self.audio:
            yield (json.dumps({'type':'audio.ready','sample_rate':24000,'encoding':'pcm_s16le'})+'\n').encode()
            yield (json.dumps({'type':'audio.chunk','data':base64.b64encode(b'\0'*4800).decode()})+'\n').encode()
            await asyncio.sleep(.1)
            yield b'{"type":"audio.finished"}\n'
        else:
            yield ('data: '+json.dumps({'choices':[{'delta':{'content':'这是第一句实时回答。'}}]},ensure_ascii=False)+'\n\n').encode()
            await asyncio.sleep(1)
            yield ('data: '+json.dumps({'choices':[{'delta':{'content':'这是稍后才生成的第二句。'}}]},ensure_ascii=False)+'\n\n').encode()
            yield b'data: {"usage":{"total_tokens":5}}\n\ndata: [DONE]\n\n'

def upstream(request):
    if request.method=='GET':return httpx.Response(200,json={'data':[{'id':'fixture-text'}]})
    if request.url.path.endswith('/audio/speech/stream'):return httpx.Response(200,stream=Stream(audio=True))
    if json.loads(request.content).get('stream'):return httpx.Response(200,stream=Stream(),headers={'Content-Type':'text/event-stream'})
    return httpx.Response(200,json={'choices':[{'message':{'content':'已收到你的消息。'}}],'usage':{'total_tokens':5}})
app=create_app(sys.argv[1],admin_token='fixture-admin-'+'x'*40,providers=Providers(
    ProviderConfig(model_base='http://127.0.0.1:1/v1',model_key='fixture-only',text_model='fixture-text',audio_base='http://127.0.0.1:1/v1',audio_key='fixture-audio-only',audio_stream=os.getenv('SHENGJIAN_FIXTURE_STREAM')=='1'),httpx.MockTransport(upstream)))
@app.post('/__test/complete/{ident}')
async def complete_fixture(ident: str):
    store=app.state.store
    row=store.db.execute('SELECT * FROM tasks WHERE id=?',(ident,)).fetchone()
    assert row is not None and store.dispatch(row['device_id'])['id']==ident
    store.device_event(row['device_id'],ident,{'type':'task.state','state':'running'},'fixture-running')
    store.device_event(row['device_id'],ident,{'type':'task.result','text':'voice-task-report'},'fixture-result')
    store.device_event(row['device_id'],ident,{'type':'task.state','state':'succeeded'},'fixture-completed')
    return {'ok':True}

app.state.store.register('browser-test','browser-password-123',app.state.store.invite(100))
app.state.store.register('browser-second','browser-password-456',app.state.store.invite(100))
uvicorn.run(app,host='127.0.0.1',port=int(sys.argv[2]),access_log=False,log_level='error')
