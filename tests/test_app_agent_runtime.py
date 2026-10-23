import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]/'src'))
import agent_runtime


def test_enrollment_is_scoped_private_and_reusable(tmp_path, monkeypatch):
    calls = []
    class Account:
        vault = type('Vault', (), {'read': lambda self: 'private-session'})()
        def __init__(self, directory): pass
        def request(self, path, body=None, token='', method=None):
            calls.append((path, body, method))
            if path == '/models': return {'data': [{'id': 'actual-model', 'input_modalities': ['text']}]}
            if path == '/devices' and body: return {'id': 'device', 'token': 'private-device-token'}
            if path == '/devices': return {'devices': [{'id': 'device', 'revoked': False, 'grants': ['tasks']}]}
            return {'ok': True}
    monkeypatch.setattr(agent_runtime, 'CloudAccount', Account)
    node, npm = tmp_path/'node', tmp_path/'npm-cli.js'
    node.touch(); npm.touch()
    monkeypatch.setattr(agent_runtime.shutil, 'which', lambda name, **kwargs: str(node if name == 'node' else npm))
    runtime = agent_runtime.AgentRuntime(tmp_path)
    runtime.workspace = tmp_path/'workspace'
    package = runtime.root/'harness/node_modules/@deepseek-ai/dsh/package.json'
    package.parent.mkdir(parents=True)
    package.write_text(json.dumps({'version': agent_runtime.VERSION}))
    config = runtime.prepare(True)
    assert config['text_model'] == 'actual-model'
    assert runtime.config_path.stat().st_mode & 0o077 == 0
    assert 'private-device-token' not in str(runtime.status())
    assert any(body == {'grants': ['tasks', 'metrics']} and method == 'PATCH' for _, body, method in calls)
    assert runtime.prepare(True) == config
    assert sum(path == '/devices' and body is not None for path, body, _ in calls) == 1
    runtime.enabled_path.touch()
    runtime.stop(persist=False)
    assert runtime.enabled_path.exists()
    runtime.stop()
    assert not runtime.enabled_path.exists()


def test_no_login_does_not_enroll_or_install(tmp_path, monkeypatch):
    class Account:
        vault = type('Vault', (), {'read': lambda self: ''})()
        def __init__(self, directory): pass
    monkeypatch.setattr(agent_runtime, 'CloudAccount', Account)
    with pytest.raises(RuntimeError, match='先在账号区登录'):
        agent_runtime.AgentRuntime(tmp_path).prepare(True)
    assert not (tmp_path/'agent/device.json').exists()
