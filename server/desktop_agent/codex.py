"""Codex App Server stdio adapter; approval decisions are relayed per operation."""
import asyncio
import json
import os
from pathlib import Path
import signal
import subprocess
import uuid


class EngineError(Exception):
    pass


class CodexEngine:
    def __init__(self, executable, workspace, emit):
        self.executable, self.workspace, self.emit = executable, workspace, emit
        self.command = [str(part) for part in executable] if isinstance(executable, (list,tuple)) else [str(executable)]
        self.process = None
        self.pending = {}
        self.approvals = {}
        self.counter = 0
        self.thread = self.turn = None
        self.finished = asyncio.get_running_loop().create_future()
        self.reader = None
        self.write_lock = asyncio.Lock()

    async def spawn(self, *command, **options):
        # Cancellation can arrive after the OS spawned a child but before asyncio
        # returns its handle. Always obtain that handle before acknowledging stop.
        launch = asyncio.create_task(asyncio.create_subprocess_exec(*command, **options))
        try:
            self.process = await asyncio.shield(launch)
        except asyncio.CancelledError:
            self.process = await launch
            await self.close()
            raise

    async def write(self, message):
        async with self.write_lock:
            self.process.stdin.write((json.dumps(message, ensure_ascii=False) + '\n').encode())
            await self.process.stdin.drain()

    async def rpc(self, method, params):
        self.counter += 1
        ident = self.counter
        future = asyncio.get_running_loop().create_future()
        self.pending[ident] = future
        await self.write({'id': ident, 'method': method, 'params': params})
        try:
            return await asyncio.wait_for(future, 45)
        finally:
            self.pending.pop(ident, None)

    async def answer(self, approval_id, allow, answer=None):
        ident = self.approvals.pop(approval_id, None)
        if ident is not None:
            await self.write({'id': ident, 'result': {'decision': 'accept' if allow else 'decline'}})
            await self.emit({'type': 'task.state', 'state': 'running'})

    async def read(self):
        try:
            while True:
                raw = await self.process.stdout.readline()
                if not raw:
                    raise EngineError('codex_process_exited')
                message = json.loads(raw)
                if 'method' not in message:
                    future = self.pending.get(message.get('id'))
                    if future is not None and not future.done():
                        if 'error' in message:
                            future.set_exception(EngineError('codex_rpc_failed'))
                        else:
                            future.set_result(message.get('result', {}))
                    continue
                method, params = message['method'], message.get('params', {})
                if 'id' in message:
                    if method in {'item/commandExecution/requestApproval', 'item/fileChange/requestApproval'}:
                        approval_id = uuid.uuid4().hex
                        self.approvals[approval_id] = message['id']
                        # Only the relevant operation preview goes to the owner; never raw environment.
                        preview = {k: params[k] for k in ['command', 'cwd', 'reason', 'itemId'] if k in params}
                        await self.emit({'type': 'task.approval', 'approval_id': approval_id,
                                         'text': json.dumps(preview, ensure_ascii=False)[:16000]})
                    else:
                        await self.write({'id': message['id'], 'error': {'code': -32601, 'message': 'Unsupported desktop interaction'}})
                        await self.emit({'type': 'task.log', 'text': '此操作需要当前连接器尚未支持的交互：' + method[:160]})
                    continue
                if method == 'item/agentMessage/delta':
                    await self.emit({'type': 'task.log', 'text': str(params.get('delta', ''))[:16000]})
                elif method == 'item/completed':
                    item = params.get('item', {})
                    if item.get('type') == 'agentMessage':
                        await self.emit({'type': 'task.result', 'text': str(item.get('text', ''))[:24000]})
                elif method == 'turn/completed':
                    turn = params.get('turn', {})
                    if not self.finished.done():
                        self.finished.set_result(turn.get('status'))
                    return
        except (EngineError, ValueError, OSError, asyncio.LimitOverrunError) as error:
            failure = EngineError(str(error) if isinstance(error, EngineError) else 'codex_protocol_ended')
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(failure)
            if not self.finished.done():
                self.finished.set_exception(failure)

    async def run(self, prompt):
        options = {'start_new_session': True} if os.name != 'nt' else {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}
        await self.spawn(
            *self.command, 'app-server', '--stdio', cwd=self.workspace,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, limit=2 * 1024 * 1024, **options)
        self.reader = asyncio.create_task(self.read())
        try:
            await self.rpc('initialize', {'clientInfo': {'name': 'shengjian-desktop', 'version': '2.0.0'},
                                          'capabilities': {'experimentalApi': False}})
            await self.write({'method': 'initialized', 'params': {}})
            thread = await self.rpc('thread/start', {'cwd': str(self.workspace), 'sandbox': 'workspace-write',
                                                    'approvalPolicy': 'on-request', 'ephemeral': True})
            self.thread = thread['thread']['id']
            turn = await self.rpc('turn/start', {'threadId': self.thread, 'input': [{'type': 'text', 'text': prompt}]})
            self.turn = turn['turn']['id']
            status = await self.finished
            if status != 'completed':
                raise EngineError('codex_turn_' + str(status))
        finally:
            await self.close()

    async def close(self):
        if self.process and self.process.returncode is None:
            # Only this adapter's own process group is stopped; unrelated Codex sessions are untouched.
            if os.name == 'nt':
                killer = await asyncio.create_subprocess_exec('taskkill', '/PID', str(self.process.pid), '/T', '/F',
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                await killer.wait()
            else:
                try:
                    os.killpg(self.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            try:
                await asyncio.wait_for(self.process.wait(), 8)
            except asyncio.TimeoutError:
                if os.name != 'nt':
                    try:
                        os.killpg(self.process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    self.process.kill()
                await self.process.wait()
        if self.reader:
            self.reader.cancel()
            await asyncio.gather(self.reader, return_exceptions=True)
        # Retrieve abandoned RPC errors, preventing unhandled-future warnings on early exit.
        if self.finished.done() and not self.finished.cancelled():
            self.finished.exception()
