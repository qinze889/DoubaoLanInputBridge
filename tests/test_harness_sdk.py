import asyncio
import json
import sys
from pathlib import Path
from server.desktop_agent.sdk import SDKHarness


def test_warm_sdk_reuses_process_and_cancellation_can_resume_without_replay(tmp_path):
    server=tmp_path/'sdk_fixture.py'
    server.write_text('''import sys,json,os
from pathlib import Path
assert 'sdk' in sys.argv
for line in sys.stdin:
 m=json.loads(line);assert m['jsonrpc']=='2.0'
 method=m['method'];p=m.get('params',{});out={}
 if method=='initialize':out={'serverInfo':{'name':'deepseek-harness-sdk-runtime','version':'fixture'}}
 if method=='session/prompt':
  assert (Path(os.environ['DSH_HOME']).parent/'conversations'/('a'*32+'.json')).exists(), 'mapping must be durable before admission'
  text=p['contentBlocks'][0]['text']
  with open('calls.txt','a') as f:f.write(text+'\\n')
  sid=p['sessionId'];waiting=text=='wait'
  if not waiting:
   print(json.dumps({'type':'shengjian_delta','text':'实时回答。'}),flush=True)
   for event in [{'type':'assistant/message','data':{'message':{'content':[{'type':'text','text':'实时回答。'}]}}},{'type':'turn/end','data':{'reason':{'kind':'completed'}}}]:
    print(json.dumps({'jsonrpc':'2.0','method':'session.event','params':{'sessionId':sid,'event':event}}),flush=True)
  out={'messageId':'fixture'}
 if method=='session/wait' and waiting:continue
 print(json.dumps({'jsonrpc':'2.0','id':m['id'],'result':out}),flush=True)
''')
    async def check():
        events=[]
        async def emit(e):events.append(e)
        engine=SDKHarness([sys.executable,str(server)],tmp_path,emit,
            {'server':'http://localhost:1/shengjian/api/v2','token':'private-test-token','text_model':'fixture'},tmp_path/'runtime')
        engine.conversation_id='a'*32
        try:
            await engine.start();pid=engine.process.pid
            await engine.run('one');await engine.run('two')
            assert engine.process.pid==pid and engine.process.returncode is None
            assert sum(e['type']=='task.delta' for e in events)==2
            pending=asyncio.create_task(engine.run('wait'))
            for _ in range(200):
                if (tmp_path/'calls.txt').read_text().endswith('wait\n'):break
                await asyncio.sleep(.01)
            pending.cancel();await asyncio.gather(pending,return_exceptions=True)
            assert engine.process.returncode is not None,'Cancel must stop owned worker before acknowledgement'
            await engine.run('after cancel')
            assert engine.process.pid!=pid
            assert (tmp_path/'calls.txt').read_text().splitlines()==['one','two','wait','after cancel']
            assert json.loads((tmp_path/'runtime/conversations'/('a'*32+'.json')).read_text())['session_id']=='session-'+'a'*32
            assert events[-1]=={'type':'task.result','text':'实时回答。'}
        finally:await engine.close()
    asyncio.run(check())
