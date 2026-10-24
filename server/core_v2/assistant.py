"""Voice control over the same owned, durable task API. Never execute partial ASR."""
import json
import re
import time

from fastapi import Depends
from pydantic import Field

from .store import Fault, TERMINAL

STATES = {'queued': '排队中', 'running': '执行中', 'awaiting_user': '等待你的确认', 'succeeded': '已完成', 'failed': '失败', 'cancelled': '已取消', 'unknown': '结果未知，需要检查电脑'}


def intent(text):
    value = re.sub(r'[\s，。！？,.!?、：:]', '', text.lower())
    value = re.sub(r'^(?:请|麻烦|帮我)', '', value)
    if value in {'停一下', '停止播报', '停止说话', '别说了', '暂停播报'}: return 'silence'
    if re.fullmatch(r'(?:取消|停止|终止)(?:当前|这个|刚才的|正在执行的)?(?:电脑)?任务', value): return 'cancel'
    if re.fullmatch(r'(?:查看|查询|汇报|报告|说一下)?(?:当前|这个|刚才的|现在的)?任务(?:进度|状态|结果|怎么样了|做到哪了|完成了吗|做完了吗)', value): return 'status'
    if value in {'进度怎么样了', '现在进度怎么样', '现在进度怎么样了', '进度如何', '做到哪里了', '现在做到哪了', '做到哪了', '做完了吗', '当前进度', '汇报进度', '汇报结果'}: return 'status'
    if value in {'取消正在执行的任务', '停止正在执行的任务', '取消刚才的任务', '取消这个工作'}: return 'cancel'
    if value in {'电脑状态', '查看电脑状态', '电脑运行情况', '电脑负载', '电脑怎么样了'}: return 'metrics'
    if value in {'允许本次操作', '允许这次操作', '批准本次操作'}: return 'allow'
    if value in {'拒绝本次操作', '拒绝这次操作', '不允许本次操作'}: return 'deny'
    return 'task'


def mount(app, store, user, peers):
    from .app import PREFIX, Input

    class Turn(Input):
        text: str = Field(min_length=1, max_length=16000)
        request_id: str = Field(min_length=16, max_length=128)
        device_id: str | None = Field(default=None, min_length=32, max_length=32)
        task_id: str | None = Field(default=None, min_length=32, max_length=32)
        engine: str = Field(default='harness', pattern=r'^(harness|codex)$')
        expires_in: int | None = Field(default=None, ge=5, le=60)

    class Chat(Input):
        text: str = Field(min_length=1, max_length=16000)
        request_id: str = Field(min_length=16, max_length=128)
        conversation_id: str = Field(pattern=r'^[a-f0-9]{32}$')
        device_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')
        task_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')
        life_images: list[str] = Field(default_factory=list, max_length=2)
        interrupted: bool = False

    class Preference(Input):
        chat_model: str = Field(min_length=1,max_length=256)

    async def model_options(uid):
        provider=app.state.life.providers
        if not provider or not provider.readiness()['models']:return {'ok':True,'chat_model':'','chat_models':[]}
        await provider.models()
        models=list(dict.fromkeys([provider.config.text_model,*provider.config.chat_models]))
        selected=store.chat_preference(uid) or provider.config.text_model
        return {'ok':True,'chat_model':selected,'chat_models':[{'id':m,'name':m.removeprefix('workbuddy/cn:'),'verified':True} for m in models if m in provider.discovered_ids]}

    @app.get(PREFIX+'/assistant/preferences')
    async def preferences(uid=Depends(user)):
        return await model_options(uid)

    @app.patch(PREFIX+'/assistant/preferences')
    async def preference(body:Preference,uid=Depends(user)):
        options=await model_options(uid)
        if body.chat_model not in {m['id'] for m in options['chat_models']}:raise Fault('chat_model_not_verified',400)
        store.chat_preference(uid,body.chat_model)
        return await model_options(uid)

    @app.post(PREFIX+'/assistant/chat')
    async def chat(body: Chat, uid=Depends(user)):
        if intent(body.text) != 'task':
            previous=getattr(app.state,'previous_conversation_control',lambda *args:None)(uid,body)
            if previous:return previous
            # A queued follow-up must not replace the running Work as the control target.
            with store.lock:
                bound=store.db.execute('SELECT * FROM assistant_conversations WHERE id=?',(body.conversation_id,)).fetchone()
            target=body.task_id
            selected=body.device_id
            if bound:
                binding=store.conversation(uid,body.conversation_id,selected)
                selected=binding['device_id']
                candidates=[t for t in store.tasks(uid) if t['device_id']==selected and json.loads(t['specification']).get('conversation_id')==body.conversation_id and t['state'] not in TERMINAL]
                running=[t for t in candidates if t['state'] in {'running','awaiting_user'}]
                if running:target=min(running,key=lambda t:t['created'])['id']
                elif candidates:target=min(candidates,key=lambda t:t['created'])['id']
            response=await turn(Turn(text=body.text, request_id=body.request_id, device_id=selected,
                                   task_id=target), uid)
            recorder=getattr(app.state,'record_conversation_control',None)
            if recorder:recorder(uid,body,response)
            return response
        old = store.task_by_request(uid, body.request_id)
        if old:
            spec = json.loads(old['specification'])
            if any(spec.get(k) != v for k,v in {
                'voice_text': body.text, 'conversation_id': body.conversation_id,
                'life_images': body.life_images, 'interrupted': body.interrupted}.items()) or (body.device_id and body.device_id != old['device_id']):
                raise Fault('idempotency_conflict', 409)
            return {'ok': True, 'action': 'chat', 'task': old, 'conversation_id': body.conversation_id}
        with store.lock:
            known = store.db.execute('SELECT * FROM assistant_conversations WHERE id=?', (body.conversation_id,)).fetchone()
        if known:
            binding = store.conversation(uid, body.conversation_id, body.device_id)
            ident = binding['device_id']
        else:
            choices = [d for d in store.devices(uid) if not d['revoked'] and 'tasks' in d['grants'] and d['id'] in peers]
            ident = body.device_id or (choices[0]['id'] if len(choices)==1 else None)
            if not ident: raise Fault('select_computer_for_chat', 409)
        device = store.device(uid, ident)
        if device['revoked'] or 'tasks' not in device['grants']: raise Fault('capability_not_granted', 403)
        if ident not in peers: raise Fault('chat_computer_offline', 409)
        if not device['metrics'].get('harness_chat'): raise Fault('chat_agent_update_required', 409)
        life = app.state.life
        for image in body.life_images:
            if not re.fullmatch(r'[a-f0-9]{32}', image): raise Fault('invalid_life_images')
            life.store.image(uid, image)
        model = life.vision_choice(uid) if body.life_images else None
        if body.life_images and not model: raise Fault('vision_model_not_available', 503)
        store.conversation(uid, body.conversation_id, ident)
        spec = {'device_id': ident, 'request_id': body.request_id, 'prompt': body.text,
                'voice_text': body.text, 'engine': 'harness', 'conversation_id': body.conversation_id,
                'assistant_chat': True, 'life_images': body.life_images, 'vision_model': model,
                'interrupted': body.interrupted, 'chat_model': store.chat_preference(uid) or (life.providers.config.text_model if life.providers else '')}
        ahead=next((t['id'] for t in reversed(store.tasks(uid)) if t['device_id']==ident and t['state'] in {'running','awaiting_user'}),None)
        created = store.create_task(uid, spec)
        return {'ok': True, 'action': 'chat', 'task': created, 'conversation_id': body.conversation_id,'queued_behind':ahead}

    @app.post(PREFIX+'/assistant/turn')
    async def turn(body: Turn, uid=Depends(user)):
        action = intent(body.text)
        if action == 'silence':
            return {'ok': True, 'action': 'silence', 'reply': '已停止播报，电脑任务继续运行。', 'task': None}
        old = store.task_by_request(uid, body.request_id)
        if old:
            spec = json.loads(old['specification'])
            if spec.get('voice_text') != body.text or spec.get('conversation_task_id') != body.task_id or spec['engine'] != body.engine or (body.device_id and spec['device_id'] != body.device_id):
                raise Fault('idempotency_conflict', 409)
            return {'ok': True, 'action': 'task', 'reply': '这项任务已提交，当前'+STATES[old['state']]+'。', 'task': old, 'device_id': old['device_id']}
        task = store.task(uid, body.task_id) if body.task_id else None
        if task and body.device_id and task['device_id'] != body.device_id:
            raise Fault('task_device_mismatch', 409)
        ident = body.device_id or (task['device_id'] if task else None)
        if not ident:
            choices = [d for d in store.devices(uid) if not d['revoked'] and 'tasks' in d['grants'] and d['id'] in peers]
            if len(choices) != 1:
                return {'ok': True, 'action': 'select_device', 'reply': '请先在声笺 App 启用电脑 Agent。' if not choices else '有多台电脑在线，请先在发送目标中选一台。'}
            ident = choices[0]['id']
        device = store.device(uid, ident)
        if device['revoked'] or 'tasks' not in device['grants']:
            raise Fault('capability_not_granted', 403)
        if not task:
            task = next((t for t in store.tasks(uid) if t['device_id'] == ident), None)

        def result(reply, kind=action, current=task):
            return {'ok': True, 'action': kind, 'reply': reply, 'device_id': ident, 'task': current}

        if action == 'metrics':
            if ident not in peers: return result('这台电脑当前离线，无法读取实时状态。')
            metrics = device['metrics']
            readings = [f'{label} {metrics[key]:.0f}%' for key, label in [('cpu_percent', 'CPU'), ('memory_percent', '内存'), ('disk_percent', '磁盘')] if isinstance(metrics.get(key), (int, float))]
            return result('电脑在线。'+('，'.join(readings)+'。' if readings else '状态正在更新。'))
        if action in {'status', 'cancel', 'allow', 'deny'} and not task:
            return result('这台电脑还没有任务，请先告诉我需要做什么。', current=None)
        if action == 'status':
            detail = store.task_brief(uid, task['id'])
            reply = '任务'+STATES[task['state']]+'。'
            if task['cancel_requested'] and task['state'] not in TERMINAL: reply += '正在等待电脑确认取消。'
            if detail['result']: reply += detail['result'][:600]
            elif detail['latest']:
                try:
                    log=json.loads(detail['latest'])
                    if log.get('type')=='tool_call':
                        names={'bash':'后台命令','read':'读取文件','write':'写入文件','background_browser':'后台浏览器','mac_desktop':'后台控件','see_user_image':'图片识别'}
                        reply+='正在处理'+names.get(log.get('tool'),'电脑工作')+'。'
                    else:reply+='电脑仍在处理，可继续补充要求或请求取消。'
                except (ValueError,TypeError):reply+=detail['latest'][:160]
            return result(reply)
        if action == 'cancel':
            cancelled = store.cancel(uid, task['id'])
            return result('任务'+STATES[cancelled['state']]+'。' if cancelled['state'] in TERMINAL else '已请求取消，等待电脑停止并确认。', current=cancelled)
        if action in {'allow', 'deny'}:
            pending = store.task_brief(uid, task['id'])['approvals']
            if len(pending) != 1: return result('没有唯一的待确认操作，请到任务卡片查看。')
            store.approve(uid, task['id'], pending[0], {'allow': action == 'allow'})
            return result('已'+('允许' if action == 'allow' else '拒绝')+'本次操作。')
        if ident not in peers:
            return result('电脑当前离线，任务没有发送。请在电脑打开声笺并启用 Agent。', 'offline', None)
        prompt = body.text.strip()
        if task and (body.task_id or re.match(r'^(?:请|帮我|麻烦)?(?:继续|接着|再|改成|改为|补充|把刚才|在刚才|把它|把这个|刚才)', prompt)):
            previous = json.loads(task['specification'])['prompt']
            brief = store.task_brief(uid, task['id'])['result']
            prompt = '上轮任务参考（不改变工作目录或权限）：\n'+previous[-3000:]+'\n上轮结果：\n'+brief[-3000:]+'\n本轮用户要求：\n'+prompt
        specification = {'device_id': ident, 'request_id': body.request_id, 'prompt': prompt, 'engine': body.engine, 'voice_text': body.text, 'conversation_task_id': body.task_id}
        if body.expires_in is not None: specification['expires_at'] = time.time()+body.expires_in
        created = store.create_task(uid, specification)
        return result('已交给'+device['name']+'，由 '+('DeepSeek Harness' if body.engine == 'harness' else 'Codex')+' 执行。完成后我会汇报。', 'task', created)
