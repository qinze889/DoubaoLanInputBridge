import json
import secrets

import pytest
pytest.importorskip('fastapi')
from fastapi.testclient import TestClient
from server.core_v2.app import PREFIX, create_app
from server.core_v2.assistant import intent


@pytest.fixture
def agent(tmp_path):
    app = create_app(tmp_path, admin_token='test-admin-'+'x'*40)
    with TestClient(app) as client:
        store = app.state.store
        session = store.register('voice-agent', 'voice-agent-password-123', store.invite(100))
        auth = {'Authorization': 'Bearer '+session['token']}
        device = store.enroll(session['user_id'], '我的电脑', ['tasks', 'metrics'])
        store.authorize_device(session['user_id'], device['id'], ['tasks', 'metrics'])
        app.state.peers[device['id']] = object()
        yield client, store, auth, device, app
        app.state.peers.clear()


def turn(client, auth, text, **values):
    return client.post(PREFIX+'/assistant/turn', headers=auth, json={'text': text, 'request_id': secrets.token_hex(16), **values})


def test_task_status_followup_and_idempotency(agent):
    client, store, auth, device, _ = agent
    created = turn(client, auth, '让电脑写一份测试说明').json()
    assert created['action'] == 'task' and 'DeepSeek Harness' in created['reply']
    task = created['task']
    ident, uid = task['id'], task['user_id']
    assert turn(client, auth, '汇报进度', task_id=ident).json()['task']['id'] == ident
    store.dispatch(device['id'])
    store.device_event(device['id'], ident, {'type': 'task.state', 'state': 'running'}, 'running')
    store.device_event(device['id'], ident, {'type': 'task.result', 'text': '已写入说明.txt'}, 'result')
    store.device_event(device['id'], ident, {'type': 'task.state', 'state': 'succeeded'}, 'done')
    assert '已写入说明.txt' in turn(client, auth, '汇报结果', task_id=ident).json()['reply']
    request_id = secrets.token_hex(16)
    follow = turn(client, auth, '继续补充用法', task_id=ident, request_id=request_id).json()['task']
    assert '已写入说明.txt' in json.loads(follow['specification'])['prompt']
    assert turn(client, auth, '继续补充用法', task_id=ident, request_id=request_id).json()['task']['id'] == follow['id']
    assert turn(client, auth, '改成别的', task_id=ident, request_id=request_id).status_code == 409
    assert len(store.tasks(uid)) == 2
    reference = turn(client, auth, '把它改成更清楚的步骤', task_id=ident).json()['task']
    assert '已写入说明.txt' in json.loads(reference['specification'])['prompt']


def test_offline_and_ambiguous_device_do_not_dispatch(agent):
    client, store, auth, device, app = agent
    app.state.peers.clear()
    assert turn(client, auth, '写个文件', device_id=device['id']).json()['action'] == 'offline'
    assert turn(client, auth, '写个文件').json()['action'] == 'select_device'
    other = store.enroll(store.authenticate(auth['Authorization'][7:])['user_id'], '另一台', ['tasks'])
    store.authorize_device(store.authenticate(auth['Authorization'][7:])['user_id'], other['id'], ['tasks'])
    app.state.peers.update({device['id']: object(), other['id']: object()})
    assert turn(client, auth, '写个文件').json()['action'] == 'select_device'
    assert store.db.execute('SELECT count(*) FROM tasks').fetchone()[0] == 0


def test_cancel_waits_for_ack_silence_never_cancels(agent):
    client, store, auth, device, _ = agent
    task = turn(client, auth, '写文件').json()['task']
    store.dispatch(device['id'])
    store.device_event(device['id'], task['id'], {'type': 'task.state', 'state': 'running'}, 'running')
    assert turn(client, auth, '停止播报', task_id=task['id']).json()['action'] == 'silence'
    assert not store.task(task['user_id'], task['id'])['cancel_requested']
    reply = turn(client, auth, '取消当前任务', task_id=task['id']).json()
    assert '等待电脑' in reply['reply'] and reply['task']['state'] == 'running'
    store.device_event(device['id'], task['id'], {'type': 'task.state', 'state': 'cancelled'}, 'cancelled')
    assert '已取消' in turn(client, auth, '任务状态', task_id=task['id']).json()['reply']


def test_voice_approval_is_exact_one_shot_and_owner_only(agent):
    client, store, auth, device, _ = agent
    task = turn(client, auth, '执行任务').json()['task']
    store.dispatch(device['id'])
    store.device_event(device['id'], task['id'], {'type': 'task.state', 'state': 'running'}, 'running')
    store.device_event(device['id'], task['id'], {'type': 'task.approval', 'approval_id': 'one', 'text': '操作预览'}, 'approval')
    session = store.register('other-owner', 'other-owner-password-123', store.invite())
    other = {'Authorization': 'Bearer '+session['token']}
    assert turn(client, other, '允许本次操作', task_id=task['id']).status_code == 404
    assert intent('好的') == 'task'
    assert turn(client, auth, '允许本次操作', task_id=task['id']).json()['action'] == 'allow'
    assert store.decisions(device['id'])[0]['decision'] == '{"allow":true}'
    assert '没有唯一' in turn(client, auth, '允许本次操作', task_id=task['id']).json()['reply']


def test_metrics_and_task_device_mismatch(agent):
    client, store, auth, device, _ = agent
    uid = store.authenticate(auth['Authorization'][7:])['user_id']
    store.heartbeat(device['id'], {'cpu_percent': 12.5, 'memory_percent': 30})
    assert 'CPU 12%' in turn(client, auth, '查看电脑状态').json()['reply']
    task = turn(client, auth, '执行任务').json()['task']
    second = store.enroll(uid, '另一台', ['tasks'])
    assert turn(client, auth, '任务状态', device_id=second['id'], task_id=task['id']).status_code == 409
