"""Run: python -m server.core_v2 --data /private/shengjian-core --port 18767."""
import asyncio
import anyio
from collections import OrderedDict, deque
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import secrets
import time
from typing import Literal

from fastapi import Depends, FastAPI, Header, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .store import CAPABILITIES, Fault, Store

PREFIX = '/shengjian/api/v2'


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Login(Input):
    username: str = Field(min_length=3, max_length=64, pattern=r'^[A-Za-z0-9_.-]+$')
    password: str = Field(min_length=12, max_length=128)


class Register(Login):
    invite: str = Field(min_length=16, max_length=128)


class Invite(Input):
    credits: int = Field(default=0, ge=0, le=1_000_000)
    uses: int = Field(default=1, ge=1, le=100)
    lifetime: int = Field(default=86400, ge=60, le=30*86400)


class Credit(Input):
    user_id: str = Field(min_length=32, max_length=32)
    amount: int = Field(gt=0, le=1_000_000)
    request_id: str = Field(min_length=16, max_length=128)


class Settlement(Input):
    user_id: str = Field(min_length=32, max_length=32)
    actual: int = Field(ge=0, le=1_000_000)


class Device(Input):
    name: str = Field(min_length=1, max_length=80)
    capabilities: list[Literal['tasks', 'screen', 'input', 'files', 'metrics']] = Field(max_length=5)


class Grants(Input):
    grants: list[Literal['tasks', 'screen', 'input', 'files', 'metrics']] = Field(max_length=5)


class Task(Input):
    device_id: str = Field(min_length=32, max_length=32)
    request_id: str = Field(min_length=16, max_length=128)
    prompt: str = Field(min_length=1, max_length=16000)
    engine: Literal['harness', 'codex'] = 'harness'


class DeviceEvent(Input):
    type: Literal['task.state', 'task.log', 'task.result', 'task.approval']
    state: Literal['running', 'awaiting_user', 'succeeded', 'failed', 'cancelled', 'unknown'] | None = None
    text: str | None = Field(default=None, max_length=24000)
    approval_id: str | None = Field(default=None, max_length=128)


class Approval(Input):
    allow: bool
    answer: str | None = Field(default=None, max_length=4000)


class RateLimit:
    def __init__(self):
        self.entries = OrderedDict()

    def check(self, key):
        now = time.monotonic()
        attempts = self.entries.setdefault(key, deque())
        self.entries.move_to_end(key)
        while attempts and attempts[0] < now-60:
            attempts.popleft()
        if len(attempts) >= 10:
            raise Fault('rate_limited', 429)
        attempts.append(now)
        while len(self.entries) > 4096:
            self.entries.popitem(last=False)


def create_app(directory, admin_token=None, providers=None):
    directory = Path(directory)
    store = Store(directory)
    if admin_token is None:
        path = directory/'admin.token'
        if not path.exists():
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as output:
                output.write(secrets.token_urlsafe(48))
        admin_token = path.read_text().strip()
    if len(admin_token) < 32:
        raise ValueError('Admin token must be at least 32 characters')
    peers = {}
    limiter = RateLimit()
    auth_slots = asyncio.Semaphore(4)

    @asynccontextmanager
    async def lifespan(app):
        yield
        for ws in list(peers.values()):
            try:
                await ws.close(code=1012)
            except (RuntimeError, WebSocketDisconnect):
                pass
        store.close()

    app = FastAPI(title='Shengjian Core v2', docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.store = store
    app.state.peers = peers

    @app.exception_handler(Fault)
    async def fault_handler(request, error):
        return JSONResponse({'ok': False, 'error': error.code}, status_code=error.status)

    @app.middleware('http')
    async def boundaries(request, call_next):
        total, chunks = 0, []
        async for chunk in request.stream():
            total += len(chunk)
            if total > 128*1024:
                return JSONResponse({'ok': False, 'error': 'body_too_large'}, status_code=413)
            chunks.append(chunk)
        request._body = b''.join(chunks)
        response = await call_next(request)
        response.headers.update({'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff',
                                 'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'"})
        return response

    def token_from(authorization):
        if not authorization or not authorization.startswith('Bearer '):
            raise Fault('unauthorized', 401)
        return authorization[7:]

    def user(authorization: str | None = Header(default=None)):
        return store.authenticate(token_from(authorization))['user_id']

    def admin(authorization: str | None = Header(default=None)):
        if not secrets.compare_digest(token_from(authorization), admin_token):
            raise Fault('unauthorized', 401)

    @app.get(PREFIX+'/health')
    async def health():
        return {'ok': True, 'version': 2, 'providers': providers.readiness() if providers else {'models': False, 'voice': False}}

    @app.post(PREFIX+'/auth/register')
    async def register(body: Register, request: Request):
        limiter.check(request.client.host)
        async with auth_slots:
            return {'ok': True, **await asyncio.to_thread(store.register, body.username, body.password, body.invite)}

    @app.post(PREFIX+'/auth/login')
    async def login(body: Login, request: Request):
        limiter.check(request.client.host)
        async with auth_slots:
            return {'ok': True, **await asyncio.to_thread(store.login, body.username, body.password)}

    @app.post(PREFIX+'/auth/logout')
    async def logout(uid=Depends(user), authorization: str | None = Header(default=None)):
        store.logout(token_from(authorization))
        return {'ok': True}

    @app.post(PREFIX+'/admin/invites', dependencies=[Depends(admin)])
    async def invite(body: Invite):
        return {'ok': True, 'invite': store.invite(body.credits, body.uses, body.lifetime)}

    @app.post(PREFIX+'/admin/credits', dependencies=[Depends(admin)])
    async def credit(body: Credit):
        store.credit(body.user_id, body.amount, body.request_id)
        return {'ok': True}

    @app.get(PREFIX+'/usage')
    async def usage(uid=Depends(user)):
        return {'ok': True, 'usage': store.usages(uid)}

    @app.post(PREFIX+'/admin/usage/{usage_id}/settle', dependencies=[Depends(admin)])
    async def reconcile(usage_id: str, body: Settlement):
        store.settle(body.user_id, usage_id, body.actual)
        return {'ok': True}

    @app.get(PREFIX+'/me')
    async def me(uid=Depends(user)):
        return {'ok': True, 'user_id': uid, **store.wallet(uid)}

    @app.post(PREFIX+'/devices')
    async def enroll(body: Device, uid=Depends(user)):
        return {'ok': True, **store.enroll(uid, body.name, sorted(set(body.capabilities)))}

    @app.get(PREFIX+'/devices')
    async def devices(uid=Depends(user)):
        return {'ok': True, 'devices': [{**d, 'online': d['id'] in peers} for d in store.devices(uid)]}

    @app.patch(PREFIX+'/devices/{ident}')
    async def grant(ident: str, body: Grants, uid=Depends(user)):
        previous = store.device(uid, ident)
        store.authorize_device(uid, ident, body.grants)
        if set(previous['grants']) - set(body.grants) and ident in peers:
            await peers[ident].close(code=1008)
        return {'ok': True}

    @app.delete(PREFIX+'/devices/{ident}')
    async def revoke(ident: str, uid=Depends(user)):
        store.revoke(uid, ident)
        ws = peers.get(ident)
        if ws:
            await ws.close(code=1008)
        return {'ok': True}

    @app.get(PREFIX+'/tasks')
    async def tasks(uid=Depends(user)):
        return {'ok': True, 'tasks': store.tasks(uid)}

    @app.post(PREFIX+'/tasks')
    async def task(body: Task, uid=Depends(user)):
        return {'ok': True, 'task': store.create_task(uid, body.model_dump())}

    @app.get(PREFIX+'/tasks/{ident}')
    async def task_state(ident: str, uid=Depends(user)):
        return {'ok': True, 'task': store.task(uid, ident)}

    @app.get(PREFIX+'/tasks/{ident}/events')
    async def events(ident: str, after: int = 0, uid=Depends(user)):
        if after < 0:
            raise Fault('invalid_cursor')
        return {'ok': True, 'events': store.events(uid, ident, after)}

    @app.post(PREFIX+'/tasks/{ident}/cancel')
    async def cancel(ident: str, uid=Depends(user)):
        return {'ok': True, 'task': store.cancel(uid, ident)}

    @app.post(PREFIX+'/tasks/{ident}/approvals/{approval_id}')
    async def approve(ident: str, approval_id: str, body: Approval, uid=Depends(user)):
        store.approve(uid, ident, approval_id, body.model_dump(exclude_none=True))
        return {'ok': True}

    async def ws_auth(ws, device=False):
        await ws.accept()
        message = await asyncio.wait_for(ws.receive_text(), 10)
        if len(message) > 2048:
            raise Fault('invalid_auth')
        data = json.loads(message)
        principal = store.authenticate(data['token'], device=device)
        return data['token'], principal, data

    @app.websocket(PREFIX+'/tasks/{ident}/stream')
    async def stream(ws: WebSocket, ident: str):
        try:
            token, principal, data = await ws_auth(ws)
            cursor = int(data.get('after', 0))
            if cursor < 0:
                raise Fault('invalid_cursor')
            while True:
                store.authenticate(token)
                for event in store.events(principal['user_id'], ident, cursor):
                    await ws.send_json(event)
                    cursor = event['seq']
                await ws.send_json({'type': 'heartbeat', 'after': cursor})
                await asyncio.sleep(1)
        except (Fault, ValueError, KeyError, WebSocketDisconnect, asyncio.TimeoutError):
            await ws.close(code=1008)

    @app.websocket(PREFIX+'/device/ws')
    async def device_socket(ws: WebSocket):
        ident, sender = None, None
        async def dispatch_loop(device_id, token):
            sent_cancellations = set()
            sent_decisions = set()
            while True:
                principal = store.authenticate(token, device=True)
                grant = set(json.loads(principal['grants']))
                if 'tasks' in grant:
                    task = store.dispatch(device_id)
                    if task:
                        await ws.send_json({'type': 'task.start', 'task_id': task['id'], **json.loads(task['specification'])})
                for task in store.pending_cancellations(device_id):
                    if task['id'] not in sent_cancellations:
                        await ws.send_json({'type': 'task.cancel', 'task_id': task['id']})
                        sent_cancellations.add(task['id'])
                for answer in store.decisions(device_id):
                    if answer['id'] not in sent_decisions:
                        await ws.send_json({'type': 'approval.answer', 'task_id': answer['task_id'], 'approval_id': answer['id'], **json.loads(answer['decision'])})
                        sent_decisions.add(answer['id'])
                await asyncio.sleep(.25)
        try:
            token, principal, _ = await ws_auth(ws, device=True)
            ident = principal['id']
            if ident in peers:
                raise Fault('device_already_connected', 409)
            peers[ident] = ws
            store.heartbeat(ident, {})
            await ws.send_json({'type': 'ready', 'device_id': ident})
            sender = asyncio.create_task(dispatch_loop(ident, token))
            while True:
                message = await asyncio.wait_for(ws.receive_text(), 35)
                if len(message) > 65536:
                    raise Fault('message_too_large')
                principal = store.authenticate(token, device=True)
                data = json.loads(message)
                if data.get('type') == 'heartbeat':
                    if not isinstance(data.get('metrics',{}),dict):
                        raise Fault('invalid_metrics')
                    metrics = {k: v for k, v in data.get('metrics', {}).items() if k in {'cpu_percent','memory_percent','disk_percent','network_sent','network_received','agent_status','screen_available','input_available'}}
                    if 'metrics' not in json.loads(principal['grants']):
                        metrics = {}
                    if len(json.dumps(metrics)) > 4096:
                        raise Fault('metrics_too_large')
                    store.heartbeat(ident, metrics)
                    await ws.send_json({'type': 'heartbeat'})
                elif data.get('type') == 'task.event':
                    event = DeviceEvent.model_validate(data['event']).model_dump(exclude_none=True)
                    if (event['type'] != 'task.state' and 'state' in event) or (event['type'] != 'task.approval' and 'approval_id' in event):
                        raise Fault('invalid_event_fields')
                    if event['type'] == 'task.state' and 'state' not in event:
                        raise Fault('missing_task_state')
                    if len(data['event_id']) > 128:
                        raise Fault('invalid_event_id')
                    store.device_event(ident, data['task_id'], event, data['event_id'])
                    await ws.send_json({'type': 'event.ack', 'event_id': data['event_id']})
                else:
                    raise Fault('unsupported_device_message')
                if sender.done():
                    await sender
        except (Fault, ValueError, KeyError, TypeError, WebSocketDisconnect, asyncio.TimeoutError, asyncio.CancelledError):
            with anyio.CancelScope(shield=True):
                try:
                    await ws.close(code=1008)
                except (RuntimeError, WebSocketDisconnect):
                    pass
        finally:
            if ident and peers.get(ident) is ws:
                peers.pop(ident, None)
                store.disconnect(ident)
            if sender:
                sender.cancel()
                with anyio.CancelScope(shield=True):
                    await asyncio.gather(sender, return_exceptions=True)

    if providers:
        providers.mount(app, store, user)
    static = Path(__file__).parent/'web'
    if static.exists():
        @app.get(PREFIX+'/console')
        async def console():
            return FileResponse(static/'index.html')
        @app.get(PREFIX+'/console/{asset}')
        async def asset(asset: str):
            if asset not in {'app.js', 'app.css', 'pcm.js'}:
                raise Fault('not_found', 404)
            return FileResponse(static/asset)
    return app
