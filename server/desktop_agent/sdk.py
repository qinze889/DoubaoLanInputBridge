"""App-owned, serial SDK worker: keep the runtime warm; cancel its owned process group.

The pinned SDK has no per-prompt cancel, so cancellation closes the worker before
acknowledgement. Next turns resume durable sessions, never replay old prompts.
"""
import asyncio, json, os, subprocess
from pathlib import Path
from .harness import HarnessEngine
from .codex import EngineError, CodexEngine

class SDKHarness(HarnessEngine):

    def __init__(self, *args):
        super().__init__(*args)
        self.start_lock = asyncio.Lock()
        self.bridge = None

    async def start(self):
        async with self.start_lock:
            try:
                await self.start_owned()
            except BaseException:
                await self.close()
                raise

    async def write(self, message):
        await super().write({'jsonrpc': '2.0', **message})

    async def start_owned(self):
        if self.process and self.process.returncode is None:
            return
        overlay = self.data / 'sdk.patch.json'
        overlay.write_text(json.dumps(self.overlay()))
        overlay.chmod(384)
        self.bridge = await asyncio.start_server(self.approval, '127.0.0.1', 0, limit=32768)
        port = self.bridge.sockets[0].getsockname()[1]
        env = os.environ.copy()
        for k in ['SHENGJIAN_NATIVE_INPUT_SOCKET', 'SHENGJIAN_NATIVE_INPUT_TOKEN']:
            env.pop(k, None)
        env.update(DSH_HOME=str(self.data / 'home'), DSH_PERMISSION_MODE=self.config.get('permission_mode','workspace-write'), SHENGJIAN_DEVICE_TOKEN=self.config['token'], SHENGJIAN_APPROVAL_URL=f'http://127.0.0.1:{port}/approval', SHENGJIAN_APPROVAL_TOKEN=self.approval_token, SHENGJIAN_DESKTOP_URL=f'http://127.0.0.1:{port}/desktop-tool', SHENGJIAN_VISION_URL=f'http://127.0.0.1:{port}/vision-tool', SHENGJIAN_TOOLS_MODULE=str(Path(self.command[1]).resolve().parents[3] / '@deepseek-ai/dsh-tools/lib/index.js'))
        options = {'start_new_session': True} if os.name != 'nt' else {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}
        await self.spawn(*self.command, 'sdk', '--patch', str(overlay), cwd=self.workspace, env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=2 * 1024 * 1024, **options)
        self.sid = None
        self.answer_text = ''
        self.reason = None
        self.opened = set()
        self.reader = asyncio.create_task(self.read_sdk())
        await self.rpc('initialize', {'cwd': str(self.workspace), 'provider': 'shengjian', 'model': self.config['text_model'], 'maxTokens': 2048})

    async def read_sdk(self):
        try:
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    raise EngineError('sdk_process_exited')
                event = json.loads(line)
                if 'id' in event and 'method' not in event:
                    future = self.pending.get(event['id'])
                    if future and (not future.done()):
                        if 'error' in event:
                            future.set_exception(EngineError('sdk_rpc_failed'))
                        else:
                            future.set_result(event.get('result', {}))
                    continue
                if event.get('type') == 'shengjian_delta' and self.sid:
                    await self.emit({'type': 'task.delta', 'text': event['text'][:16000]})
                    continue
                if event.get('type') == 'shengjian_agent':
                    self.agents[str(event.get('id', ''))] = str(event.get('state', 'unknown'))
                    continue
                if event.get('method') == 'session.event':
                    params = event['params']
                    if params['sessionId'] != self.sid:
                        continue
                    item = params['event']
                    kind = item['type']
                    data = item.get('data', {})
                    if kind == 'assistant/message':
                        text = ''.join((p['text'] for p in data['message']['content'] if p['type'] == 'text'))
                        if text:
                            self.answer_text = text
                    elif kind == 'turn/end':
                        self.reason = data['reason']
                    elif kind == 'tool/call':
                        await self.emit({'type': 'task.log', 'text': json.dumps({'type': 'tool_call', 'tool': data.get('name')})})
        except Exception:
            for f in self.pending.values():
                if not f.done():
                    f.set_exception(EngineError('sdk_connection_lost'))

    async def run(self, prompt):
        try:
            await self.run_owned(prompt)
        except BaseException:
            await self.close()
            raise
        finally:
            self.sid = None
            if self.local_tools:
                await asyncio.to_thread(self.local_tools.close_children)

    async def run_owned(self, prompt):
        if not self.conversation_id or len(self.conversation_id) != 32 or any((c not in '0123456789abcdef' for c in self.conversation_id)):
            raise EngineError('invalid_conversation_id')
        if self.process and self.process.returncode is None and (len(self.opened) >= 16):
            folder = self.data / 'conversations'
            f = folder / (self.conversation_id + '.json')
            target = json.loads(f.read_text())['session_id'] if f.exists() else 'session-' + self.conversation_id
            if target not in self.opened:
                await self.close()
        await self.start()
        self.answer_text = ''
        self.reason = None
        folder = self.data / 'conversations'
        folder.mkdir(mode=448, exist_ok=True)
        f = folder / (self.conversation_id + '.json')
        exists = f.exists()
        self.sid = json.loads(f.read_text())['session_id'] if exists else 'session-' + self.conversation_id
        if self.sid not in self.opened:
            if exists:
                await self.rpc('session/resume', {'sessionId': self.sid})
            else:
                # Create the durable session without admitting a prompt. The mapping
                # must survive cancellation immediately after prompt admission.
                await self.rpc('session/working-directory/get', {'sessionId': self.sid})
            self.opened.add(self.sid)
        temporary = f.with_suffix('.next')
        temporary.write_text(json.dumps({'session_id': self.sid}))
        temporary.chmod(384)
        temporary.replace(f)
        await self.rpc('session/prompt', {'sessionId': self.sid, 'contentBlocks': [{'type': 'text', 'text': prompt}]})
        self.counter += 1
        ident = self.counter
        future = asyncio.get_running_loop().create_future()
        self.pending[ident] = future
        await self.write({'jsonrpc': '2.0', 'id': ident, 'method': 'session/wait', 'params': {'sessionId': self.sid}})
        try:
            await future
        finally:
            self.pending.pop(ident, None)
        if not self.answer_text or (self.reason or {}).get('kind') != 'completed':
            raise EngineError('sdk_turn_failed')
        await self.emit({'type': 'task.result', 'text': self.answer_text[:24000]})
        self.sid = None

    async def close(self):
        await CodexEngine.close(self)
        for future in self.decisions.values():
            if not future.done():
                future.set_result(False)
        self.decisions.clear()
        if getattr(self, 'bridge', None):
            self.bridge.close()
            await self.bridge.wait_closed()
