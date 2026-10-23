import asyncio
import json
import os
from pathlib import Path
import sys
import pytest
pytest.importorskip('psutil')
pytest.importorskip('websockets')
from server.desktop_agent.codex import CodexEngine
from server.desktop_agent.journal import Journal


def test_journal_claim_survives_restart_without_command_replay(tmp_path):
    task={'task_id':'stable-id','engine':'codex','prompt':'safe fixture task'}
    journal=Journal(tmp_path)
    assert journal.claim(task)
    journal.state(task['task_id'],'running')
    event=journal.event(task['task_id'],{'type':'task.state','state':'running'})
    journal.acknowledge(event['event_id']);journal.close()
    journal=Journal(tmp_path)
    assert not journal.claim(task)
    assert journal.db.execute('select state from tasks').fetchone()[0]=='unknown'
    assert journal.db.execute('select acknowledged from events').fetchone()[0]==1
    journal.close()


@pytest.mark.skipif(os.name=='nt',reason='POSIX executable fixture; connector protocol is tested on Linux CI')
def test_codex_real_stdio_approval_waits_for_owner_and_only_accepts_once(tmp_path):
    executable=tmp_path/'fake-codex'
    executable.write_text('''#!/usr/bin/env python3
import sys,json
for line in sys.stdin:
 m=json.loads(line)
 method=m.get('method')
 if method=='initialize': out={'id':m['id'],'result':{}}
 elif method=='thread/start':
  assert m['params']['sandbox']=='workspace-write'
  assert m['params']['approvalPolicy']=='on-request'
  out={'id':m['id'],'result':{'thread':{'id':'test-thread'}}}
 elif method=='turn/start':
  print(json.dumps({'id':m['id'],'result':{'turn':{'id':'test-turn'}}}),flush=True)
  out={'id':'approval-rpc','method':'item/commandExecution/requestApproval','params':{'command':'fixture-only','reason':'owner confirmation'}}
 elif m.get('id')=='approval-rpc':
  assert m['result']=={'decision':'accept'}
  print(json.dumps({'method':'item/completed','params':{'item':{'type':'agentMessage','text':'完成'}}}),flush=True)
  out={'method':'turn/completed','params':{'threadId':'test-thread','turn':{'id':'test-turn','status':'completed'}}}
 else: continue
 print(json.dumps(out),flush=True)
''')
    executable.chmod(0o700)
    async def check():
        events=[];approval=asyncio.Event()
        async def emit(body):
            events.append(body)
            if body['type']=='task.approval':approval.set()
        engine=CodexEngine(executable,tmp_path,emit)
        run=asyncio.create_task(engine.run('test'))
        await asyncio.wait_for(approval.wait(),5)
        assert not run.done()
        ident=events[-1]['approval_id']
        await engine.answer(ident,True)
        await engine.answer(ident,True) # A repeated delivery cannot answer twice.
        await asyncio.wait_for(run,5)
        assert events[-1]=={'type':'task.result','text':'完成'}
        assert engine.process.returncode is not None
    asyncio.run(check())


@pytest.mark.skipif(os.name=='nt',reason='POSIX child process fixture')
def test_cancel_stops_owned_engine_before_ack_can_be_sent(tmp_path):
    executable=tmp_path/'waiting-codex'
    executable.write_text('''#!/usr/bin/env python3
import time
while True:time.sleep(1)
''');executable.chmod(0o700)
    async def check():
        async def emit(body):pass
        engine=CodexEngine(executable,tmp_path,emit)
        task=asyncio.create_task(engine.run('test'))
        for _ in range(100):
            if engine.process:break
            await asyncio.sleep(.01)
        task.cancel()
        await asyncio.gather(task,return_exceptions=True)
        assert engine.process.returncode is not None
    asyncio.run(check())


def test_harness_approval_bridge_auth_and_one_shot_decision(tmp_path):
    from server.desktop_agent.harness import HarnessEngine
    async def check():
        asked=asyncio.Event();events=[]
        async def emit(body):events.append(body);asked.set()
        engine=HarnessEngine(sys.executable,tmp_path,emit,{'text_model':'fixture','server':'http://127.0.0.1:1/shengjian/api/v2','token':'fixture-only'},tmp_path/'runtime')
        server=await asyncio.start_server(engine.approval,'127.0.0.1',0)
        port=server.sockets[0].getsockname()[1]
        async def request(token):
            reader,writer=await asyncio.open_connection('127.0.0.1',port)
            body=b'{"tool":"fixture","preview":{"command":"review me"}}'
            writer.write(b'POST /approval HTTP/1.1\r\nAuthorization: Bearer '+token.encode()+b'\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body)
            await writer.drain();reply=await reader.read();writer.close();await writer.wait_closed();return reply
        try:
            denied=await request('wrong-token');assert denied.startswith(b'HTTP/1.1 403') and not events
            pending=asyncio.create_task(request(engine.approval_token))
            await asyncio.wait_for(asked.wait(),2)
            assert not pending.done() and events[0]['type']=='task.approval'
            ident=events[0]['approval_id'];await engine.answer(ident,True);await engine.answer(ident,False)
            response=await asyncio.wait_for(pending,2)
            assert json.loads(response.split(b'\r\n\r\n',1)[1])=={'allow':True}
            assert not engine.decisions
        finally:server.close();await server.wait_closed()
    asyncio.run(check())


def test_harness_parses_committed_json_and_requires_successful_exit(tmp_path):
    from server.desktop_agent.harness import HarnessEngine
    script=tmp_path/'fixture_harness.py'
    script.write_text('''import sys,json
assert 'headless' in sys.argv and '--json' in sys.argv
assert sys.stdin.read()=='fixture task'
print(json.dumps({'type':'text','text':'working'}),flush=True)
print(json.dumps({'type':'final','text':'finished'}),flush=True)
''')
    async def check():
        events=[]
        async def emit(body):events.append(body)
        engine=HarnessEngine([sys.executable,str(script)],tmp_path,emit,
            {'text_model':'fixture','server':'http://127.0.0.1:1/shengjian/api/v2','token':'fixture-secret-123'},tmp_path/'runtime')
        await engine.run('fixture task')
        assert events[-1]=={'type':'task.result','text':'finished'}
        assert 'fixture-secret-123' not in (tmp_path/'runtime/shengjian.patch.json').read_text()
    asyncio.run(check())


@pytest.mark.skipif(os.name=='nt',reason='POSIX subprocess fixture')
def test_cancellation_during_process_creation_cannot_lose_child_handle(tmp_path,monkeypatch):
    script=tmp_path/'startup-race.py';script.write_text('import time\ntime.sleep(60)\n')
    original=asyncio.create_subprocess_exec
    async def delayed(*command,**kwargs):
        await asyncio.sleep(.05)
        return await original(*command,**kwargs)
    monkeypatch.setattr(asyncio,'create_subprocess_exec',delayed)
    async def check():
        async def emit(body):pass
        engine=CodexEngine([sys.executable,str(script)],tmp_path,emit)
        task=asyncio.create_task(engine.run('fixture'))
        await asyncio.sleep(.01);task.cancel()
        await asyncio.gather(task,return_exceptions=True)
        assert engine.process is not None and engine.process.returncode is not None
    asyncio.run(check())


def test_late_cancel_cannot_overwrite_completed_result_waiting_for_send(tmp_path):
    from server.desktop_agent.__main__ import Connector
    workspace=tmp_path/'workspace';workspace.mkdir()
    async def check():
        connector=Connector({'server':'https://fixture.invalid/shengjian/api/v2','token':'x'*48,'workspace':str(workspace)},tmp_path/'journal')
        task={'task_id':'already-completed','engine':'codex','prompt':'fixture'}
        connector.journal.claim(task);connector.journal.state(task['task_id'],'succeeded')
        pending=asyncio.create_task(asyncio.sleep(60));connector.active[task['task_id']]=pending
        await connector.cancel(task['task_id'])
        assert not pending.done() and connector.journal.task_state(task['task_id'])=='succeeded'
        pending.cancel();await asyncio.gather(pending,return_exceptions=True);connector.journal.close()
    asyncio.run(check())
