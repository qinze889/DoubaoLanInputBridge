"""Owned, durable Chat/Work conversations and narrowly scoped visual delegation."""
import json
import secrets
import asyncio
import sys
import pytest
from test_voice_agent import agent, turn
from server.core_v2.app import PREFIX
from server.desktop_agent.harness import HarnessEngine


def chat(client, auth, conv, **values):
    return client.post(PREFIX+'/assistant/chat',headers=auth,json={'text':'你好，直接聊聊','request_id':secrets.token_hex(16),'conversation_id':conv,**values})


def test_owned_conversation_reuses_binding_and_idempotent_work(agent):
    client,store,auth,device,app=agent
    store.heartbeat(device['id'],{'harness_chat':True})
    conv=secrets.token_hex(16);request=secrets.token_hex(16)
    first=chat(client,auth,conv,request_id=request)
    assert first.status_code==200,first.text
    task=first.json()['task'];spec=json.loads(task['specification'])
    assert spec['assistant_chat'] and spec['conversation_id']==conv and spec['engine']=='harness'
    assert chat(client,auth,conv,request_id=request).json()['task']['id']==task['id']
    assert chat(client,auth,conv,request_id=request,text='变更要求').status_code==409
    # No dispatch keyword or separate task mode is required.
    next_task=chat(client,auth,conv,text='把刚才的内容写成说明.txt').json()['task']
    assert json.loads(next_task['specification'])['conversation_id']==conv
    other=store.register('chat-intruder','chat-intruder-password',store.invite())
    assert chat(client,{'Authorization':'Bearer '+other['token']},conv).status_code==404
    second=store.enroll(task['user_id'],'第二台',['tasks']);store.authorize_device(task['user_id'],second['id'],['tasks'])
    assert chat(client,auth,conv,device_id=second['id']).status_code==409
    app.state.peers.clear()
    assert chat(client,auth,conv).json()['error']=='chat_computer_offline'


def test_chat_requires_updated_computer_and_scopes_photos(agent):
    client,store,auth,device,app=agent
    conv=secrets.token_hex(16)
    assert chat(client,auth,conv).json()['error']=='chat_agent_update_required'
    store.heartbeat(device['id'],{'harness_chat':True})
    assert chat(client,auth,conv,life_images=['bad']).status_code==400
    assert chat(client,auth,conv,life_images=['a'*32]).status_code==404
    t=chat(client,auth,conv).json()['task']
    controlled=chat(client,auth,conv,text='取消当前任务',task_id=t['id']).json()
    assert controlled['action']=='cancel' and controlled['task']['cancel_requested']


def test_harness_continues_real_session_id_and_streams_only_text(tmp_path):
    script=tmp_path/'fixture.py'
    script.write_text('''import sys,json
if '--session-id' in sys.argv:assert sys.argv[sys.argv.index('--session-id')+1]=='session-fixture'
sys.stdin.read()
for x in [{'type':'session','sessionId':'session-fixture'},{'type':'shengjian_delta','text':'实时回答。'},{'type':'final','text':'实时回答。'}]:print(json.dumps(x),flush=True)
''')
    async def run():
        events=[]
        async def emit(e):events.append(e)
        for i in range(2):
            e=HarnessEngine([sys.executable,str(script)],tmp_path,emit,{'text_model':'fixture','server':'http://localhost:1/shengjian/api/v2','token':'private-fixture'},tmp_path/'runtime')
            e.conversation_id='a'*32
            await e.run('hello')
        assert sum(e['type']=='task.delta' for e in events)==2
        assert json.loads((tmp_path/'runtime/conversations'/('a'*32+'.json')).read_text())['session_id']=='session-fixture'
    asyncio.run(run())


def test_chat_capability_survives_real_device_protocol_without_metrics_grant(agent):
    client,store,auth,device,app=agent
    uid=store.authenticate(auth['Authorization'][7:])['user_id']
    store.authorize_device(uid,device['id'],['tasks'])
    app.state.peers.clear()
    with client.websocket_connect(PREFIX+'/device/ws') as ws:
        ws.send_json({'token':device['token']})
        assert ws.receive_json()['type']=='ready'
        ws.send_json({'type':'heartbeat','metrics':{'harness_chat':True,'cpu_percent':10}})
        assert ws.receive_json()['type']=='heartbeat'
        assert store.device(uid,device['id'])['metrics']=={'harness_chat':True}
        assert chat(client,auth,secrets.token_hex(16)).status_code==200
