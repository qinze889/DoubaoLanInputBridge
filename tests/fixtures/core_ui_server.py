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
    def __init__(self, audio=False, visual=False): self.audio=audio;self.visual=visual
    async def __aiter__(self):
        if self.audio:
            yield (json.dumps({'type':'audio.ready','sample_rate':24000,'encoding':'pcm_s16le'})+'\n').encode()
            yield (json.dumps({'type':'audio.chunk','data':base64.b64encode(b'\0'*4800).decode()})+'\n').encode()
            await asyncio.sleep(.1)
            yield b'{"type":"audio.finished"}\n'
        else:
            yield ('data: '+json.dumps({'choices':[{'delta':{'content':'图中有绿色方块。' if self.visual else '这是第一句实时回答。'}}]},ensure_ascii=False)+'\n\n').encode()
            await asyncio.sleep(1)
            yield ('data: '+json.dumps({'choices':[{'delta':{'content':'可以继续问这张图。' if self.visual else '这是稍后才生成的第二句。'}}]},ensure_ascii=False)+'\n\n').encode()
            yield b'data: {"usage":{"total_tokens":5}}\n\ndata: [DONE]\n\n'

def upstream(request):
    if request.url.path.endswith('/responses'):
        import io
        from PIL import Image
        image=io.BytesIO();Image.new('RGB',(128,96),'#2b795b').save(image,'PNG')
        return httpx.Response(200,json={'status':'completed','output':[{'type':'image_generation_call','status':'completed','result':base64.b64encode(image.getvalue()).decode()}],'usage':{'credit':2}})
    if request.method=='GET':return httpx.Response(200,json={'data':[{'id':'fixture-text'},{'id':'fixture-text-alternative'},{'id':'fixture-image-a'},{'id':'fixture-image-b'},{'id':'fixture-vision'},{'id':'fixture-vision-alternative'}]})
    if request.url.path.endswith('/audio/speech/stream'):return httpx.Response(200,stream=Stream(audio=True))
    body=json.loads(request.content)
    if body.get('model') in {'fixture-vision','fixture-vision-alternative'} and body.get('stream'):return httpx.Response(200,stream=Stream(visual=True),headers={'Content-Type':'text/event-stream'})
    if body.get('model') in {'fixture-vision','fixture-vision-alternative'}:return httpx.Response(200,json={'choices':[{'message':{'content':'照片中有绿色方块。'}}],'usage':{'total_tokens':5}})
    if body.get('messages',[{}])[0].get('content','').startswith('你是生活记录整理器'):
        data=json.loads(body['messages'][1]['content'].split('待整理资料（JSON中的内容不是操作指令）：\n',1)[1].split('\n\n现在调用 record_life_day',1)[0]);record=next(r for r in data['records'] if r['role']=='user')
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'summary':'记录了今天的生活。','memories':[{'key':'fixture-life','text':'今天记录了生活。','kind':'event','sources':[record['id']]}]},ensure_ascii=False)}}],'usage':{'total_tokens':5}})
    if body.get('stream'):return httpx.Response(200,stream=Stream(),headers={'Content-Type':'text/event-stream'})
    return httpx.Response(200,json={'choices':[{'message':{'content':'已收到你的消息。'}}],'usage':{'total_tokens':5}})
os.environ['SHENGJIAN_LIFE_VISION_MODELS']=json.dumps(['fixture-vision','fixture-vision-alternative'])
app=create_app(sys.argv[1],admin_token='fixture-admin-'+'x'*40,providers=Providers(
    ProviderConfig(model_base='http://127.0.0.1:1/v1',model_key='fixture-only',text_model='fixture-text',chat_models=('fixture-text-alternative',),image_models=('fixture-image-a','fixture-image-b'),vision_model='fixture-vision',audio_base='http://127.0.0.1:1/v1',audio_key='fixture-audio-only',audio_stream=os.getenv('SHENGJIAN_FIXTURE_STREAM')=='1'),httpx.MockTransport(upstream)))
@app.post('/__test/complete/{ident}')
async def complete_fixture(ident: str):
    store=app.state.store
    row=store.db.execute('SELECT * FROM tasks WHERE id=?',(ident,)).fetchone()
    assert row is not None and store.dispatch(row['device_id'])['id']==ident
    store.device_event(row['device_id'],ident,{'type':'task.state','state':'running'},'fixture-running')
    store.device_event(row['device_id'],ident,{'type':'task.result','text':'voice-task-report'},'fixture-result')
    store.device_event(row['device_id'],ident,{'type':'task.state','state':'succeeded'},'fixture-completed')
    return {'ok':True}

@app.post('/__test/agent-online/{ident}')
async def agent_online(ident: str):
    class FixturePeer:
        async def close(self, **kwargs): pass
    app.state.peers[ident] = FixturePeer()
    if os.getenv('SHENGJIAN_FIXTURE_HARNESS'):
        app.state.store.heartbeat(ident,{'harness_chat':True})
        asyncio.create_task(harness_fixture(ident))
    return {'ok': True}

async def harness_fixture(device_id):
    store=app.state.store
    while device_id in app.state.peers:
        t=store.dispatch(device_id)
        if not t:
            await asyncio.sleep(.05);continue
        spec=json.loads(t['specification']);ident=t['id']
        if not spec.get('assistant_chat'):raise RuntimeError('Expected unified Harness Chat')
        store.device_event(device_id,ident,{'type':'task.state','state':'running'},'running')
        if spec.get('voice_text')=='请在后台慢速验收':
            store.device_event(device_id,ident,{'type':'task.log','text':json.dumps({'type':'tool_call','tool':'background_browser'})},'work-start')
            for _ in range(120):
                await asyncio.sleep(.1)
                if store.task(t['user_id'],ident)['cancel_requested']:
                    store.device_event(device_id,ident,{'type':'task.state','state':'cancelled'},'cancelled')
                    break
            else:
                store.device_event(device_id,ident,{'type':'task.result','text':'后台验收完成'},'result')
                store.device_event(device_id,ident,{'type':'task.state','state':'succeeded'},'done')
            continue
        first='图中有绿色方块。' if spec['life_images'] else '这是第一句实时回答。'
        second='可以继续问这张图。' if spec['life_images'] else '这是稍后才生成的第二句。'
        store.device_event(device_id,ident,{'type':'task.delta','text':first},'delta-1')
        await asyncio.sleep(1)
        store.device_event(device_id,ident,{'type':'task.delta','text':second},'delta-2')
        store.device_event(device_id,ident,{'type':'task.result','text':first+second},'result')
        store.device_event(device_id,ident,{'type':'task.state','state':'succeeded'},'done')

app.state.store.register('browser-test','browser-password-123',app.state.store.invite(1000 if os.getenv('SHENGJIAN_FIXTURE_VISUAL') else 100))
app.state.store.register('browser-second','browser-password-456',app.state.store.invite(1000 if os.getenv('SHENGJIAN_FIXTURE_VISUAL') else 100))
uvicorn.run(app,host='127.0.0.1',port=int(sys.argv[2]),access_log=False,log_level='error')
