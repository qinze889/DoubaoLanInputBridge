"""App-owned Harness connector. Credentials and execution stay on this computer."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import secrets
import sys
import time

from cloud_account import BASE, CloudAccount

VERSION = '0.2.1-rc.2'
_instances = {}
_instances_lock = threading.Lock()


def bundled_command():
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))/'agent-runtime'
    node = root/('node.exe' if os.name == 'nt' else 'node')
    cli = root/'node_modules/@deepseek-ai/dsh/lib/bin.js'
    package = cli.parents[1]/'package.json'
    if node.is_file() and package.is_file() and json.loads(package.read_text())['version'] == VERSION:
        return [str(node), str(cli)]
    return None


def manager(directory):
    with _instances_lock:
        key = str(Path(directory).resolve())
        return _instances.setdefault(key, AgentRuntime(Path(directory)))


class AgentRuntime:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.root = self.directory/'agent'
        self.config_path = self.root/'device.json'
        self.enabled_path = self.root/'enabled'
        self.workspace = Path.home()/'Documents/声笺任务'
        self.lock = threading.RLock()
        self.thread = self.loop = self.task = self.connector = None
        self.phase, self.error = 'off', ''
        self.model = ''
        self.permission_mode = 'workspace-write'
        self.stopping = False

    def status(self):
        with self.lock:
            connector = self.connector
            return {'ok': True, 'phase': self.phase, 'error': self.error,
                    'engine': 'DeepSeek Harness', 'version': VERSION, 'model': self.model,
                    'workspace': str(self.workspace), 'enabled': self.enabled_path.exists(),
                    'connected': bool(connector and connector.ws),
                    'interaction_mode': 'background',
                    'permission_mode': self.permission_mode,
                    'subagents': [{'id': ident, 'state': state} for engine in (list(connector.engines.values()) if connector else []) for ident, state in dict(getattr(engine, 'agents', {})).items()],
                    'capabilities': {'subagents': True, 'max_subagents': 3, 'max_depth': 1, 'child_messages': True, 'skills': ['background-web', 'computer-report', 'task-workspace'], 'mcp_client': 'not_configured'},
                    'last_task': connector.last_task if connector else None,
                    'active_tasks': len(connector.active) if connector else 0}

    def personal(self, body=None):
        from server.desktop_agent.personal import PersonalStore
        if not self.config_path.exists(): raise RuntimeError('请先启用电脑 Agent。')
        scope = json.loads(self.config_path.read_text())['device_id']
        with PersonalStore(self.root/'personal', scope) as store:
            if body is not None:
                action = body.get('action')
                if action == 'configure': store.configure(body.get('settings', {}))
                elif action == 'remember': store.remember(body.get('text'))
                elif action == 'forget': store.delete_memory(body.get('id'))
                elif action == 'schedule': store.schedule(body.get('schedule', {}))
                elif action == 'schedule_state': store.change_schedule(body.get('id'), body.get('enabled', False), body.get('deleted', False))
                else: raise ValueError('unknown_personal_action')
            return {'ok': True, 'settings': store.settings(), 'memories': store.memories(), 'life_memories': store.life_memories(), 'schedules': store.schedules(), 'runs': store.runs()}

    def sync_life(self, connector):
        account = CloudAccount(self.directory)
        token = account.vault.read()
        if not token:
            connector.personal.sync_life([])
            return
        try:
            devices = account.request('/devices', token=token)['devices']
            if not any(d['id']==connector.config['device_id'] and not d['revoked'] and 'tasks' in d['grants'] for d in devices):
                connector.personal.sync_life([])
                return
            data = account.request('/life/memories', token=token)
            if account.vault.read()==token:connector.personal.sync_life(data['memories'])
            else:connector.personal.sync_life([])
        except PermissionError:
            connector.personal.sync_life([])

    async def life_sync(self, connector):
        while True:
            try:await asyncio.to_thread(self.sync_life, connector)
            except Exception:pass  # A network outage keeps the last verified account's snapshot.
            await asyncio.sleep(60)

    def submit(self, prompt, request_id=None, expires_in=None):
        if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 16000:
            raise RuntimeError('请输入 1 至 16000 字的任务。')
        if not self.connector or not self.connector.ws:
            raise RuntimeError('请先启用并连接电脑 Agent。')
        config = json.loads(self.config_path.read_text())
        account = CloudAccount(self.directory)
        token = account.vault.read()
        if not token:
            raise RuntimeError('请先登录声笺账号。')
        body = {'text': prompt.strip(), 'request_id': request_id or secrets.token_hex(16), 'device_id': config['device_id'], 'engine': 'harness'}
        if expires_in is not None: body['expires_in'] = expires_in
        return account.request('/assistant/turn', body, token)

    async def scheduler(self, connector):
        store = connector.personal
        store.recover_runs()
        while True:
            for run in store.claim_due():
                if not connector.ws:
                    store.finish_run(run['id'], run['slot'], 'missed')
                    continue
                try:
                    result = await asyncio.to_thread(self.submit, run['prompt'], run['request_id'], 30)
                    task = result.get('task') if result.get('action') == 'task' else None
                    store.finish_run(run['id'], run['slot'], 'submitted' if task else 'missed', task['id'] if task else None)
                except Exception:
                    # A timed-out submission may have reached the server. Never retry it.
                    store.finish_run(run['id'], run['slot'], 'unknown')
            await asyncio.sleep(5)

    def resume(self):
        if self.enabled_path.exists() and self.config_path.exists():
            self.start(enroll=False)

    def start(self, enroll=True):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return self.status()
            self.stopping = False
            self.phase, self.error = 'starting', ''
            self.thread = threading.Thread(target=self.run, args=(enroll,), daemon=True)
            self.thread.start()
            return self.status()

    def stop(self, persist=True):
        with self.lock:
            self.stopping = True
            if persist:
                self.enabled_path.unlink(missing_ok=True)
            loop, task, thread = self.loop, self.task, self.thread
            if loop and task and not loop.is_closed():
                loop.call_soon_threadsafe(task.cancel)
        if thread and thread is not threading.current_thread():
            thread.join(timeout=25)
        with self.lock:
            if thread and thread.is_alive():
                self.phase = 'stopping'
            else:
                self.phase = 'off'
        return self.status()

    def prepare(self, enroll):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        account = CloudAccount(self.directory)
        session = account.vault.read() if enroll else ''
        if enroll and not session:
            raise RuntimeError('请先在账号区登录与手机相同的声笺账号。')
        if self.config_path.exists():
            config = json.loads(self.config_path.read_text())
            mode=config.get('permission_mode','workspace-write')
            if mode not in {'workspace-write','danger-full-access'}:raise RuntimeError('无效的 Harness 权限模式。')
            self.permission_mode=mode
            if bundled_command():
                config['harness_executable'] = bundled_command()
            self.workspace = Path(config['workspace'])
            if enroll:
                devices = account.request('/devices', token=session)['devices']
                if not any(d['id'] == config['device_id'] and not d['revoked'] and 'tasks' in d['grants'] for d in devices):
                    raise RuntimeError('此连接器未授权给当前账号；请先检查设备授权，不会覆盖原设备凭据。')
            return config
        if not enroll:
            raise RuntimeError('电脑 Agent 尚未登记，请重新启用。')
        command = bundled_command()
        if not command:
            path = os.pathsep.join([os.environ.get('PATH', ''), str(Path.home()/'.local/bin'), '/opt/homebrew/bin', '/usr/local/bin'])
            node, npm = shutil.which('node', path=path), shutil.which('npm', path=path)
            if not node or not npm:
                raise RuntimeError('需要本机 Node.js（含 npm）；安装后重新启用 Agent。')
            node = str(Path(node).resolve())
            candidates = [Path(node).parent/'node_modules/npm/bin/npm-cli.js', Path(npm).resolve()]
            npm_cli = next((p for p in candidates if p.is_file() and p.suffix == '.js'), None)
            if not npm_cli:
                raise RuntimeError('无法找到 npm 运行入口，请检查 Node.js 安装。')
            harness = self.root/'harness'
            package = harness/'node_modules/@deepseek-ai/dsh/package.json'
            if not package.exists() or json.loads(package.read_text())['version'] != VERSION:
                self.phase = 'installing'
                env = {**os.environ, 'PATH': str(Path(node).parent)+os.pathsep+path}
                result = subprocess.run([node, str(npm_cli), 'install', '--prefix', str(harness), '--ignore-scripts', '--no-audit', '--no-fund', '--save-exact', '@deepseek-ai/dsh@'+VERSION], env=env,
                                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
                if result.returncode:
                    raise RuntimeError('Harness 安装失败，请检查网络后重试。')
            command = [node, str(harness/'node_modules/@deepseek-ai/dsh/lib/bin.js')]
        if self.stopping:
            raise RuntimeError('启用已停止。')
        models = account.request('/models', token=session)['data']
        model = next(m['id'] for m in models if 'text' in m['input_modalities'])
        device = account.request('/devices', {'name': '本机声笺 · '+('Mac' if os.name != 'nt' else 'Windows'), 'capabilities': ['tasks', 'metrics']}, session)
        try:
            self.workspace.mkdir(parents=True, exist_ok=True)
            config = {'server': BASE, 'device_id': device['id'], 'token': device['token'], 'workspace': str(self.workspace), 'text_model': model,
                      'harness_executable': command}
            account.request('/devices/'+device['id'], {'grants': ['tasks', 'metrics']}, session, method='PATCH')
            fd = os.open(self.config_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as output:
                json.dump(config, output)
            return config
        except BaseException:
            account.request('/devices/'+device['id'], token=session, method='DELETE')
            raise

    def run(self, enroll):
        try:
            config = self.prepare(enroll)
            self.model = config['text_model']
            with self.lock:
                if self.stopping:
                    return
                self.enabled_path.touch(mode=0o600)
            async def connect():
                from server.desktop_agent.__main__ import Connector
                self.loop = asyncio.get_running_loop()
                self.task = asyncio.current_task()
                self.connector = Connector(config, self.root/'state')
                self.phase = 'running'
                if self.stopping:
                    self.connector.journal.close()
                    return
                scheduled = asyncio.create_task(self.scheduler(self.connector))
                life = asyncio.create_task(self.life_sync(self.connector))
                try: await self.connector.run()
                finally:
                    scheduled.cancel();life.cancel()
                    await asyncio.gather(scheduled, life, return_exceptions=True)
            asyncio.run(connect())
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.error = str(exc) if isinstance(exc, RuntimeError) else 'Agent 未能启动，请检查登录、运行环境或设备授权。'
            self.phase = 'error'
        finally:
            self.connector = self.loop = self.task = None
            if self.phase != 'error':
                self.phase = 'off'
