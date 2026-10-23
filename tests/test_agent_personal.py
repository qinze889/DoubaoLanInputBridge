from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from server.desktop_agent.personal import PersonalStore
from server.desktop_agent.local_tools import LocalTools


def test_memory_persistence_scope_delete_and_context(tmp_path):
    with PersonalStore(tmp_path, 'device-a') as a, PersonalStore(tmp_path, 'device-b') as b:
        ident = a.remember('回复先讲结果')
        assert a.remember('回复先讲结果') == ident
        assert not b.memories()
        with pytest.raises(ValueError): b.delete_memory(ident)
        assert '先讲结果' in a.context('汇报')
        a.configure({'memory_context': False})
        assert a.context('汇报') == ''
        a.delete_memory(ident)
        assert not a.memories()
        a.delete_memory(ident, restore=True)
        with pytest.raises(ValueError): a.remember('我的密码是示例')
    with PersonalStore(tmp_path, 'device-a') as a:
        assert a.memories()[0]['id'] == ident
        assert not a.settings()['memory_context']


def test_schedule_restart_claims_are_never_replayed(tmp_path):
    with PersonalStore(tmp_path, 'a') as store:
        ident = store.schedule({'title': 'fixture', 'prompt': 'test', 'kind': 'once', 'at': 110, 'enabled': True}, now=100)
        assert not store.claim_due(109)
        run = store.claim_due(110)[0]
        assert run['id'] == ident
        assert not store.claim_due(115)
    with PersonalStore(tmp_path, 'a') as store:
        store.recover_runs()
        assert store.runs()[0]['state'] == 'unknown'
        assert not store.claim_due(120)
        missed = store.schedule({'title': 'late', 'prompt': 'test', 'kind': 'once', 'at': 130, 'enabled': True}, now=120)
        assert not store.claim_due(200)
        assert next(r for r in store.runs() if r['schedule_id'] == missed)['state'] == 'missed'


def test_daily_timezone_and_dst_missing_hour(tmp_path):
    with PersonalStore(tmp_path, 'a') as store:
        store.schedule({'title': 'daily', 'prompt': 'test', 'kind': 'daily', 'local_time': '09:00', 'enabled': True})
        instant = datetime(2026, 10, 23, 9, 0, tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
        assert len(store.claim_due(instant)) == 1
        assert not store.claim_due(instant+10)
        assert len(store.claim_due(instant+86400)) == 1
    with PersonalStore(tmp_path/'dst', 'a') as store:
        store.schedule({'title': 'dst', 'prompt': 'test', 'kind': 'daily', 'local_time': '02:30', 'timezone': 'America/New_York', 'enabled': True})
        instant = datetime(2026, 3, 8, 3, 30, tzinfo=ZoneInfo('America/New_York')).timestamp()
        assert not store.claim_due(instant)
        assert store.runs()[0]['state'] == 'missed'


def test_native_tools_require_local_toggle_and_app_scope(tmp_path, monkeypatch):
    with PersonalStore(tmp_path, 'a') as store:
        tools = LocalTools(store)
        calls = []
        monkeypatch.setattr('server.desktop_agent.local_tools.native', lambda request: calls.append(request) or {'ok': True})
        request = {'action': 'observe', 'application': 'com.apple.calculator'}
        assert not tools.perform(request)['ok']
        store.configure({'desktop_enabled': True})
        assert not tools.perform({**request, 'application': 'unapproved.app'})['ok']
        assert not calls
        assert tools.perform(request)['ok']
        assert calls == [request]
        assert not tools.perform({**request, 'action': 'shell'})['ok']


@pytest.mark.parametrize('values', [{'title': 1}, {'title': None, 'prompt': 'x'}, {'title': 'x', 'prompt': 'x', 'kind': 'once', 'at': float('nan')}, {'title': 'x', 'prompt': 'x', 'kind': 'daily', 'local_time': '25:00'}])
def test_invalid_schedule_input_is_rejected(tmp_path, values):
    with PersonalStore(tmp_path, 'a') as store:
        with pytest.raises(ValueError): store.schedule(values)


def test_native_snapshots_compact_noise_without_changing_ids(tmp_path, monkeypatch):
    snapshot = {'ok': True, 'generation': 'fresh', 'nodes': [
        {'id': '1', 'role': 'AXGroup', 'title': '', 'value': '', 'actions': [], 'editable': False},
        {'id': '2', 'role': 'AXButton', 'description': '2', 'title': '', 'actions': ['AXPress'], 'editable': False},
        {'id': '3', 'role': 'AXMenuItem', 'title': 'Close', 'actions': ['AXPress']},
    ]}
    monkeypatch.setattr('server.desktop_agent.local_tools.native', lambda _: dict(snapshot))
    with PersonalStore(tmp_path, 'a') as store:
        store.configure({'desktop_enabled': True})
        result = LocalTools(store).perform({'action': 'observe', 'application': 'com.apple.calculator'})
        assert result['generation'] == 'fresh'
        assert [row['id'] for row in result['nodes']] == ['2']
        assert 'title' not in result['nodes'][0]


def test_parallel_children_have_distinct_background_profiles_and_no_native_input(tmp_path, monkeypatch):
    class Browser:
        def __init__(self, root): self.root, self.closed = root, False
        def perform(self, _): return {'ok': True, 'profile': str(self.root)}
        def close(self): self.closed = True
    monkeypatch.setattr('server.desktop_agent.local_tools.BackgroundBrowser', Browser)
    with PersonalStore(tmp_path, 'a') as store:
        store.configure({'desktop_enabled': True})
        main = Browser(tmp_path/'browser'); tools = LocalTools(store, main)
        one = tools.perform({'tool': 'browser', 'action': 'observe', '_agent_id': 'child-a'})
        two = tools.perform({'tool': 'browser', 'action': 'observe', '_agent_id': 'child-b'})
        assert one['profile'] != two['profile'] != str(main.root)
        assert not tools.perform({'action': 'press', 'application': 'com.apple.calculator', '_agent_id': 'child-a'})['ok']
        assert tools.perform({'tool': 'browser', 'action': 'observe', '_agent_id': 'child-c'})['ok']
        assert not tools.perform({'tool': 'browser', 'action': 'observe', '_agent_id': 'child-d'})['ok']
        children = list(tools.children.values()); tools.close_children()
        assert all(child.closed for child in children) and not tools.children


def test_cloud_life_snapshot_is_scoped_and_deletions_retract_context(tmp_path):
    rows=[{'id':'life-a','text':'喜欢简短回答','day':'2026-10-23','sources':['record-a']}]
    with PersonalStore(tmp_path,'device-a') as a,PersonalStore(tmp_path,'device-b') as b:
        a.sync_life(rows)
        assert '简短回答' in a.context('回答') and not b.life_memories()
        assert 'sources' in a.life_memories()[0]
        a.configure({'memory_context':False});assert a.context('回答')==''
        a.sync_life([]);assert not a.life_memories()
        with pytest.raises(ValueError):a.sync_life([{'id':'broken'}])
