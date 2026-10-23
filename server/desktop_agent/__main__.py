import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

import psutil
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from .codex import CodexEngine, EngineError
from .journal import Journal


class Connector:
    def __init__(self, config, data):
        self.config = config
        self.data = Path(data)
        server = config['server'].rstrip('/')
        url = urlsplit(server)
        if url.username or url.password or url.query or url.fragment or not url.hostname or (url.scheme != 'https' and not (url.scheme == 'http' and url.hostname in {'127.0.0.1','localhost','::1'})):
            raise ValueError('Use the HTTPS core service URL or loopback HTTP')
        if url.path != '/shengjian/api/v2':
            raise ValueError('Expected /shengjian/api/v2 URL')
        if not isinstance(config['token'], str) or len(config['token']) < 32:
            raise ValueError('Invalid device credential')
        self.url = server.replace('https://','wss://',1).replace('http://','ws://',1) + '/device/ws'
        self.workspace = Path(config['workspace']).expanduser().resolve(strict=True)
        if not self.workspace.is_dir() or self.workspace == Path(self.workspace.anchor) or self.workspace == Path.home():
            raise ValueError('Choose a dedicated workspace directory')
        self.journal = Journal(data)
        self.ws = None
        self.active = {}
        self.engines = {}
        self.lock = asyncio.Lock()
        self.execution_slot = asyncio.Semaphore(1)

    async def send(self, message):
        async with self.lock:
            await self.ws.send(json.dumps(message, ensure_ascii=False))

    async def emit(self, ident, body):
        if body['type'] == 'task.state':
            self.journal.state(ident, body['state'])
        await self.send(self.journal.event(ident, body))

    def metrics(self):
        network = psutil.net_io_counters()
        return {'cpu_percent': psutil.cpu_percent(), 'memory_percent': psutil.virtual_memory().percent,
                'disk_percent': psutil.disk_usage(str(self.workspace)).percent,
                'network_sent': network.bytes_sent, 'network_received': network.bytes_recv,
                'agent_status': 'running' if self.active else 'idle',
                'screen_available': False, 'input_available': False}

    async def heartbeat(self):
        while True:
            await self.send({'type':'heartbeat', 'metrics':self.metrics()})
            await asyncio.sleep(10)

    async def execute(self, task):
        try:
            async with self.execution_slot:
                await self.execute_owned(task)
        finally:
            self.engines.pop(task['task_id'], None)
            self.active.pop(task['task_id'], None)

    async def execute_owned(self, task):
        ident = task['task_id']
        try:
            await self.emit(ident, {'type':'task.state','state':'running'})
            if task['engine'] == 'harness' and self.config.get('harness_executable') and self.config.get('text_model'):
                from .harness import HarnessEngine
                engine = HarnessEngine(self.config['harness_executable'] if isinstance(self.config['harness_executable'],list) else Path(self.config['harness_executable']).expanduser(), self.workspace,
                    lambda body: self.emit(ident, body), self.config, self.data / 'harness')
            elif task['engine'] == 'codex' and self.config.get('codex_executable'):
                engine = CodexEngine(Path(self.config['codex_executable']).expanduser(), self.workspace,
                                     lambda body: self.emit(ident, body))
            else:
                raise EngineError('所选执行引擎尚未配置；任务没有执行。')
            self.engines[ident] = engine
            await engine.run(task['prompt'])
            await self.emit(ident, {'type':'task.state','state':'succeeded'})
        except asyncio.CancelledError:
            # Engine.run's finally must stop its owned process before this coroutine completes.
            self.journal.state(ident, 'unknown')
            raise
        except (EngineError, OSError, KeyError) as error:
            await self.emit(ident, {'type':'task.log','text':str(error)[:1000] if isinstance(error,EngineError) else '本地执行器启动失败，请检查配置。'})
            await self.emit(ident, {'type':'task.state','state':'failed'})

    async def cancel(self, ident):
        task = self.active.get(ident)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await self.emit(ident, {'type':'task.state','state':'cancelled'})
        # A completed or unknown operation is never retroactively labelled cancelled.

    async def session(self):
        async with connect(self.url, proxy=None, max_size=256*1024, open_timeout=15, close_timeout=5) as ws:
            self.ws = ws
            await self.send({'token':self.config['token']})
            ready = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if ready.get('type') != 'ready':
                raise EngineError('Device authentication failed')
            beat = asyncio.create_task(self.heartbeat())
            try:
                async for raw in ws:
                    message = json.loads(raw)
                    kind = message.get('type')
                    if kind == 'task.start':
                        if not self.journal.claim(message):
                            # Never repeat a command whose identity has already been observed.
                            await self.emit(message['task_id'], {'type':'task.state','state':'unknown'})
                        else:
                            self.active[message['task_id']] = asyncio.create_task(self.execute(message))
                    elif kind == 'task.cancel':
                        await self.cancel(message['task_id'])
                    elif kind == 'approval.answer':
                        engine = self.engines.get(message['task_id'])
                        if engine:
                            await engine.answer(message['approval_id'], message['allow'], message.get('answer'))
                    elif kind == 'event.ack':
                        self.journal.acknowledge(message['event_id'])
                    if beat.done():
                        await beat
            finally:
                beat.cancel()
                pending = list(self.active.values())
                for task in pending:
                    task.cancel()
                await asyncio.gather(beat, *pending, return_exceptions=True)
                self.ws = None

    async def run(self):
        delay = 1
        try:
            while True:
                try:
                    await self.session()
                    delay = 1
                except (OSError, WebSocketException, asyncio.TimeoutError, EngineError, ValueError):
                    # Do not log tokens, prompts, or raw provider errors.
                    print('声笺连接中断，任务不会重放；等待重新连接。', file=sys.stderr)
                await asyncio.sleep(delay)
                delay = min(delay*2, 30)
        finally:
            self.journal.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'nt' and args.config.stat().st_mode & 0o077:
        parser.error('Device config must be private (chmod 600)')
    asyncio.run(Connector(json.loads(args.config.read_text()), args.data).run())


if __name__ == '__main__':
    main()
