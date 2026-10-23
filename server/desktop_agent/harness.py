"""Pinned DSH headless JSON runner plus a loopback, one-shot approval bridge."""
import asyncio
import json
import os
from pathlib import Path
import secrets
import subprocess
import uuid

from .codex import CodexEngine, EngineError


class HarnessEngine(CodexEngine):
    def __init__(self, executable, workspace, emit, config, data):
        super().__init__(executable, workspace, emit)
        self.config = config
        self.data = Path(data)
        self.data.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.decisions = {}
        self.approval_token = secrets.token_urlsafe(48)

    async def answer(self, approval_id, allow, answer=None):
        future = self.decisions.get(approval_id)
        if future is not None and not future.done():
            future.set_result(bool(allow))
            await self.emit({'type': 'task.state', 'state': 'running'})

    async def approval(self, reader, writer):
        ident = None
        try:
            header = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 5)
            lines = header.decode('ascii').split('\r\n')
            fields = dict(line.split(':', 1) for line in lines[1:] if ':' in line)
            fields = {k.lower(): v.strip() for k, v in fields.items()}
            if lines[0] != 'POST /approval HTTP/1.1' or not secrets.compare_digest(fields.get('authorization', ''), 'Bearer ' + self.approval_token):
                raise EngineError('approval_unauthorized')
            size = int(fields.get('content-length', '0'))
            if not 0 < size <= 32768 or len(self.decisions) >= 8:
                raise EngineError('invalid_approval')
            preview = json.loads(await asyncio.wait_for(reader.readexactly(size), 5))
            ident = uuid.uuid4().hex
            future = asyncio.get_running_loop().create_future()
            self.decisions[ident] = future
            await self.emit({'type': 'task.approval', 'approval_id': ident, 'text': json.dumps(preview, ensure_ascii=False)[:20000]})
            allow = await asyncio.wait_for(future, 1800)
            body = json.dumps({'allow': allow}).encode()
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)
            await writer.drain()
        except (EngineError, OSError, ValueError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError):
            writer.write(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
        finally:
            if ident:
                self.decisions.pop(ident, None)
            writer.close()
            await writer.wait_closed()

    def overlay(self):
        model = self.config['text_model']
        plugin = str(Path(__file__).with_name('dsh_approval.mjs').resolve())
        # JSON is valid YAML. No model or account secret is written to the profile.
        return [
            {'id': 'agent-default-model', 'config': {'provider': 'shengjian', 'model': model}},
            {'id': 'llm-pi-ai', 'config': {'providers': {'shengjian': {
                'api': 'openai-completions', 'apiKeyEnv': 'SHENGJIAN_DEVICE_TOKEN',
                'compat': {'supportsStore': False, 'supportsDeveloperRole': False, 'supportsReasoningEffort': False, 'maxTokensField': 'max_tokens'},
                'baseURL': self.config['server'].rstrip('/') + '/model/v1',
                'models': [{'id': model, 'name': '声笺模型', 'contextWindow': 32768, 'maxTokens': 2048, 'input': ['text'], 'reasoning': False}],
                'retryPolicy': {'mode': 'normal', 'maxRetries': 0}}}}},
            {'insert': [{'id': 'shengjian-approval', 'name': plugin}]},
        ]

    async def run(self, prompt):
        overlay = self.data / 'shengjian.patch.json'
        overlay.write_text(json.dumps(self.overlay(), ensure_ascii=False))
        overlay.chmod(0o600)
        server = await asyncio.start_server(self.approval, '127.0.0.1', 0, limit=32768)
        port = server.sockets[0].getsockname()[1]
        env = os.environ.copy()
        env.update(DSH_HOME=str(self.data / 'home'), DSH_PERMISSION_MODE='workspace-write',
                   SHENGJIAN_DEVICE_TOKEN=self.config['token'],
                   SHENGJIAN_APPROVAL_URL=f'http://127.0.0.1:{port}/approval',
                   SHENGJIAN_APPROVAL_TOKEN=self.approval_token)
        options = {'start_new_session': True} if os.name != 'nt' else {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}
        final = False
        try:
            self.process = await asyncio.create_subprocess_exec(*self.command, 'headless', '--patch', str(overlay), '--json', '-',
                cwd=self.workspace, env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, limit=2*1024*1024, **options)
            self.process.stdin.write(prompt.encode())
            await self.process.stdin.drain()
            self.process.stdin.close()
            total = 0
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    break
                event = json.loads(line)
                kind = event.get('type')
                if kind == 'error':
                    raise EngineError('harness_run_failed')
                if kind == 'final':
                    final = True
                    await self.emit({'type': 'task.result', 'text': str(event.get('text', ''))[:24000]})
                elif kind in {'text', 'tool_call', 'tool_result', 'status'}:
                    text = event.get('text') if kind == 'text' else json.dumps(event, ensure_ascii=False)
                    if total < 512*1024:
                        total += len(text)
                        await self.emit({'type': 'task.log', 'text': text[:16000]})
            code = await self.process.wait()
            if code or not final:
                raise EngineError('harness_run_failed')
        finally:
            server.close()
            await server.wait_closed()
            for future in self.decisions.values():
                if not future.done():
                    future.set_result(False)
            await self.close()
