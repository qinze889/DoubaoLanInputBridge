"""Owned durable image jobs using verified Responses and Images Edits protocols.

Single submission: a timeout/restart is unknown, never an automatic second generation.
Only configured, independently verified image models are exposed.
"""
import asyncio
import base64
import io
import json
import math
import logging
import re
from urllib.parse import urlsplit
import secrets
import time

import httpx
from fastapi import Depends
from fastapi.responses import Response
from PIL import Image
from pydantic import Field

from .store import Fault, digest, encode


class ImageGeneration:
    def __init__(self, store, life, providers):
        self.store, self.life, self.providers = store, life, providers
        self.tasks = set()
        self.gate = asyncio.Semaphore(2)
        with store.lock:
            store.db.executescript('''
              CREATE TABLE IF NOT EXISTS image_preferences(uid TEXT PRIMARY KEY REFERENCES users(id),model TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS image_jobs(id TEXT PRIMARY KEY,uid TEXT NOT NULL REFERENCES users(id),request_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL,model TEXT NOT NULL,prompt TEXT NOT NULL,state TEXT NOT NULL,error TEXT NOT NULL DEFAULT '',
                image_id TEXT,entry_id TEXT,width INTEGER,height INTEGER,source TEXT NOT NULL DEFAULT '',usage TEXT NOT NULL DEFAULT '{}',
                created REAL NOT NULL,updated REAL NOT NULL,png BLOB,UNIQUE(uid,request_id));
              CREATE INDEX IF NOT EXISTS image_jobs_owner ON image_jobs(uid,created);
            ''')
            for table,columns in {'image_jobs':{'operation':"TEXT NOT NULL DEFAULT 'generate'",'input_image_id':"TEXT",'parent_job_id':"TEXT",'root_job_id':"TEXT",'version':"INTEGER NOT NULL DEFAULT 1",'diagnostic':"TEXT NOT NULL DEFAULT '{}'"},'image_preferences':{'edit_model':"TEXT NOT NULL DEFAULT ''"}}.items():
                present={r[1] for r in store.db.execute('PRAGMA table_info('+table+')')}
                for column,definition in columns.items():
                    if column not in present:store.db.execute('ALTER TABLE '+table+' ADD COLUMN '+column+' '+definition)
            store.db.execute("CREATE TABLE IF NOT EXISTS image_client_events(uid TEXT NOT NULL,stage TEXT NOT NULL,code TEXT NOT NULL,created REAL NOT NULL)")
            queued=store.db.execute("SELECT id,uid FROM image_jobs WHERE state='queued'").fetchall()
            store.db.execute("UPDATE image_jobs SET state='failed',error='service_stopped' WHERE state='queued'")
            store.db.execute("UPDATE image_jobs SET state='unknown',error='service_restarted' WHERE state='running'")
            for row in queued:
                if store.db.execute('SELECT 1 FROM usage WHERE id=?',('image-'+row['id'],)).fetchone():store.settle(row['uid'],'image-'+row['id'],0)

    async def catalog(self, uid):
        p = self.providers
        choices, edit_choices = [], []
        if p and p.readiness()['models'] and (p.config.image_models or p.config.image_edit_models):
            await p.models()
            names={'workbuddy/cn:hunyuan-image-alpha':'Hunyuan Image Alpha · WorkBuddy','minimax/image-01':'MiniMax Image-01','workbuddy/cn:hunyuan-image-alpha-edit':'Hunyuan Image Alpha Edit · WorkBuddy'}
            choices = [{'id': m, 'name': names.get(m,m.removeprefix('workbuddy/cn:').removeprefix('minimax/')),
                        'protocol': 'responses', 'verified': True} for m in p.config.image_models if m in p.discovered_ids]
            edit_choices = [{'id':m,'name':names.get(m,m.removeprefix('workbuddy/cn:')),'protocol':'images_edits','verified':True} for m in p.config.image_edit_models if m in p.discovered_ids]
        with self.store.lock:
            row = self.store.db.execute('SELECT model,edit_model FROM image_preferences WHERE uid=?', (uid,)).fetchone()
        return {'ok':True,'models':choices,'edit_models':edit_choices,'model':row['model'] if row and row['model'] else choices[0]['id'] if choices else '', 'edit_model':row['edit_model'] if row and row['edit_model'] else edit_choices[0]['id'] if edit_choices else ''}

    def public(self, uid, ident):
        with self.store.lock:
            row = self.store.db.execute('SELECT id,model,prompt,state,error,image_id,entry_id,width,height,source,usage,created,updated,operation,input_image_id,parent_job_id,root_job_id,version,diagnostic FROM image_jobs WHERE id=? AND uid=?', (ident, uid)).fetchone()
        if not row: raise Fault('image_job_not_found', 404)
        data = dict(row)
        data['usage'] = json.loads(data['usage'])
        data['diagnostic'] = json.loads(data['diagnostic'])
        return data

    async def submit(self, uid, prompt, request_id, model=None, image_id=None, parent_job_id=None):
        if not prompt.strip():raise Fault('image_prompt_required')
        if image_id and parent_job_id:raise Fault('image_reference_conflict')
        operation='edit' if image_id or parent_job_id else 'generate'
        # A repeated request recovers its original job, even after changing preferences.
        with self.store.lock:
            old = self.store.db.execute('SELECT id,prompt,model,input_image_id,parent_job_id FROM image_jobs WHERE uid=? AND request_id=?', (uid, request_id)).fetchone()
        if old:
            if prompt != old['prompt'] or (model and model != old['model']) or image_id!=old['input_image_id'] or parent_job_id!=old['parent_job_id']: raise Fault('idempotency_conflict', 409)
            return self.public(uid, old['id'])
        if image_id:self.life.store.image(uid,image_id)
        parent=self.public(uid,parent_job_id) if parent_job_id else None
        if parent and parent['state'] not in {'succeeded','queued','running'}:raise Fault('image_parent_not_completed',409)
        options = await self.catalog(uid)
        model = model or options['edit_model' if operation=='edit' else 'model']
        if model not in {m['id'] for m in options['edit_models' if operation=='edit' else 'models']}: raise Fault('image_model_not_available', 409)
        payload = {'model': model, 'input': prompt, 'tools': [{'type': 'image_generation'}],
                   'tool_choice': {'type': 'image_generation'}, 'stream': False}
        if operation=='edit':payload.update(operation='edit',input_image_id=image_id,parent_job_id=parent_job_id)
        ident = secrets.token_hex(16)
        with self.store.tx() as db:
            # Discovery awaits I/O: a concurrent retry may already have inserted
            # this request since the first idempotency lookup.
            old=db.execute('SELECT id,prompt,model,input_image_id,parent_job_id FROM image_jobs WHERE uid=? AND request_id=?',(uid,request_id)).fetchone()
            if old:
                if prompt!=old['prompt'] or model!=old['model'] or image_id!=old['input_image_id'] or parent_job_id!=old['parent_job_id']:raise Fault('idempotency_conflict',409)
                return self.public(uid,old['id'])
            pending=db.execute("SELECT id FROM image_jobs WHERE uid=? AND state IN ('queued','running')",(uid,)).fetchall()
            if len(pending)>=8 or (pending and operation=='generate'):raise Fault('image_job_busy',409)
            if db.execute('SELECT COALESCE(SUM(length(png)),0) FROM image_jobs WHERE uid=?', (uid,)).fetchone()[0] > 184*1024*1024: raise Fault('image_storage_full', 413)
            db.execute('INSERT INTO image_jobs(id,uid,request_id,fingerprint,model,prompt,state,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',
                       (ident, uid, request_id, digest(encode(payload)), model, prompt, 'queued', time.time(), time.time()))
        try:
            with self.store.tx() as db:
                db.execute('UPDATE image_jobs SET operation=?,input_image_id=?,parent_job_id=?,root_job_id=?,version=? WHERE id=?',(operation,image_id,parent_job_id,(parent.get('root_job_id') or parent['id']) if parent else ident,parent['version']+1 if parent else 1,ident))
            # Fixed application credits per successful image, separate from upstream money/credit units.
            self.store.reserve(uid, 'image-'+ident, self.providers.config.image_credits, digest(encode(payload)))
        except Fault:
            self.finish(ident, 'failed', 'insufficient_credits')
            raise
        task = asyncio.create_task(self.generate(uid, ident, payload))
        self.tasks.add(task); task.add_done_callback(self.tasks.discard)
        return self.public(uid, ident)

    def finish(self, ident, state, error='', diagnostic=None):
        with self.store.tx() as db:
            db.execute('UPDATE image_jobs SET state=?,error=?,updated=?,diagnostic=? WHERE id=?', (state, error, time.time(), encode(diagnostic or {}), ident))
        if error:logging.getLogger(__name__).warning('image_job_failed job=%s state=%s code=%s stage=%s',ident,state,error,(diagnostic or {}).get('stage','unspecified'))

    async def generate(self, uid, ident, payload):
        submitted = False
        response_received = False
        stage='reference_prepare';status=None
        edit=payload.get('operation')=='edit'
        try:
            reference=None
            if edit:
                if payload.get('parent_job_id'):
                    while True:
                        parent=self.public(uid,payload['parent_job_id'])
                        if parent['state']=='succeeded':
                            with self.store.lock:reference=self.store.db.execute('SELECT png FROM image_jobs WHERE id=? AND uid=?',(parent['id'],uid)).fetchone()['png']
                            break
                        if parent['state'] not in {'queued','running'}:raise Fault('image_parent_not_completed',409)
                        await asyncio.sleep(.1)
                else:
                    image=self.life.store.image(uid,payload['input_image_id'])
                    reference=(self.life.store.files/(image['id']+'.jpg')).read_bytes()
                if len(reference)>8*1024*1024:
                    picture=Image.open(io.BytesIO(reference));picture.thumbnail((1600,1600));out=io.BytesIO();picture.convert('RGB').save(out,'JPEG',quality=90);reference=out.getvalue()
                if len(reference)>8*1024*1024:raise Fault('image_reference_too_large',413)
            async with self.gate:
                self.finish(ident, 'running')
                async with self.providers.client() as client:
                    stage='upstream_edit' if edit else 'upstream_generate'
                    mime='image/png' if reference and reference.startswith(b'\x89PNG') else 'image/jpeg'
                    filename='reference.png' if mime=='image/png' else 'reference.jpg'
                    kwargs=({'data':{'model':payload['model'],'prompt':payload['input'],'size':'1024x1024'},'files':{'image':(filename,reference,mime)}} if edit else {'json':payload})
                    submitted = True
                    async with client.stream('POST', self.providers.config.model_base+('/images/edits' if edit else '/responses'),
                                             headers={'Authorization': 'Bearer '+self.providers.config.model_key, 'X-Request-ID': 'image-'+ident},
                                             **kwargs, timeout=httpx.Timeout(300, connect=10)) as response:
                        status=response.status_code
                        if response.status_code != 200:
                            if 400 <= response.status_code < 500:
                                self.store.settle(uid, 'image-'+ident, 0)
                                self.finish(ident, 'failed', 'image_provider_rejected',{'stage':stage,'upstream_status':status})
                                return
                            raise Fault('image_result_unknown', 502)
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            raw.extend(chunk)
                            if len(raw) > 32*1024*1024: raise ValueError('oversized image response')
                response_received = True
                stage='decode_result'
                data = json.loads(raw)
                if edit:
                    # Images Edits and Responses converge only after a real image is returned.
                    items=data.get('data') or []
                    if len(items)!=1 or not isinstance(items[0].get('b64_json'),str):raise ValueError('missing edited image')
                    data={**data,'status':'completed','output':[{'type':'image_generation_call','status':'completed','result':items[0]['b64_json']}]}
                if data.get('status') != 'completed': raise ValueError('incomplete response')
                results = [x.get('result') for x in data.get('output', []) if x.get('type') == 'image_generation_call' and x.get('status') == 'completed']
                if len(results) == 1 and isinstance(results[0], str):
                    if len(results[0]) > 24*1024*1024:raise ValueError('invalid image result')
                    binary = base64.b64decode(results[0], validate=True)
                elif not results and self.providers.config.image_asset_origin:
                    # Older sub-buddy Responses compatibility returns a completed
                    # output_text image asset instead of image_generation_call.
                    # Fetch the existing result once; never submit generation again.
                    text='\n'.join(part.get('text','') for item in data.get('output',[]) if item.get('type')=='message'
                                   for part in item.get('content',[]) if part.get('type')=='output_text')
                    urls=re.findall(r'https://[^\s)<>]+/generated-images/[a-f0-9]{64}\.(?:png|jpg|webp)',text)
                    urls=list(dict.fromkeys(urls))
                    if len(urls)!=1:raise ValueError('no single image result')
                    url=urlsplit(urls[0]);origin=urlsplit(self.providers.config.image_asset_origin)
                    if (url.scheme,url.netloc)!=(origin.scheme,origin.netloc) or url.username or url.password or url.query or url.fragment:raise ValueError('untrusted image asset')
                    async with self.providers.client() as download:
                        async with download.stream('GET',urls[0],timeout=45) as response:
                            if response.status_code!=200:raise ValueError('image download failed')
                            binary=bytearray()
                            async for chunk in response.aiter_bytes():
                                binary.extend(chunk)
                                if len(binary)>16*1024*1024:raise ValueError('image too large')
                    binary=bytes(binary)
                else:raise ValueError('invalid image result')
                if len(binary) > 16*1024*1024: raise ValueError('image too large')
                stage='save_result'
                picture = Image.open(io.BytesIO(binary))
                if picture.format not in {'PNG', 'JPEG', 'WEBP'} or picture.width*picture.height > 16_000_000: raise ValueError('invalid image')
                picture.load()
                png = io.BytesIO(); picture.save(png, 'PNG')
                if len(png.getvalue()) > 16*1024*1024: raise ValueError('image too large')
                width, height = picture.size
                picture.thumbnail((1600, 1600))
                preview = io.BytesIO(); picture.convert('RGB').save(preview, 'JPEG', quality=90)
                image = self.life.store.add_image(uid, preview.getvalue(), picture.width, picture.height, 'generation-'+ident)
                # Generated art is assistant output, never evidence of an actual user's life event.
                entry = self.life.store.record(uid, {'request_id': 'generation-'+ident, 'kind': 'photo', 'role': 'assistant',
                    'text': ('AI 参考图编辑。' if edit else 'AI 生成图片。')+'模型：'+payload['model']+'；需求：'+payload['input'], 'images': [image['id']]})
                usage = data.get('usage') if isinstance(data.get('usage'), dict) else {}
                # Retain only numerical usage, never arbitrary upstream URLs/credentials.
                usage = {k: v for k, v in usage.items() if k in {'credit','total_tokens','input_tokens','output_tokens'} and type(v) in {int, float} and math.isfinite(v) and v >= 0}
                source = data.get('image_source') if isinstance(data.get('image_source'), str) else payload['model']
                self.store.settle(uid, 'image-'+ident, self.providers.config.image_credits)
                with self.store.tx() as db:
                    db.execute("UPDATE image_jobs SET state='succeeded',image_id=?,entry_id=?,width=?,height=?,source=?,usage=?,png=?,updated=? WHERE id=?",
                               (image['id'], entry['id'], width, height, source[:256], encode(usage), png.getvalue(), time.time(), ident))
        except (httpx.ConnectError, httpx.ConnectTimeout):
            if response_received:
                self.finish(ident, 'unknown', 'image_result_unknown')
            else:
                self.store.settle(uid, 'image-'+ident, 0)
                self.finish(ident, 'failed', 'image_connection_failed')
        except asyncio.CancelledError:
            if not submitted: self.store.settle(uid, 'image-'+ident, 0)
            self.finish(ident, 'unknown' if submitted else 'failed', 'image_result_unknown' if submitted else 'service_stopped')
            raise
        except Fault as failure:
            if not submitted:self.store.settle(uid,'image-'+ident,0)
            self.finish(ident,'unknown' if submitted else 'failed',failure.code if not submitted else 'image_result_unknown',{'stage':stage,'upstream_status':status,'exception_type':'Fault'})
        except Exception as failure:
            if not submitted:self.store.settle(uid,'image-'+ident,0)
            self.finish(ident, 'unknown' if submitted else 'failed', 'image_result_unknown' if submitted else 'image_reference_unavailable',{'stage':stage,'upstream_status':status,'exception_type':type(failure).__name__})

    async def close(self):
        for task in list(self.tasks): task.cancel()
        await asyncio.gather(*list(self.tasks), return_exceptions=True)


def mount(app, service, user):
    from .app import Input, PREFIX

    class Settings(Input):
        model: str | None = Field(default=None,min_length=1, max_length=256)
        edit_model: str | None = Field(default=None,min_length=1,max_length=256)

    class Generate(Input):
        prompt: str = Field(min_length=1, max_length=4000)
        request_id: str = Field(min_length=16, max_length=128)
        model: str | None = Field(default=None, min_length=1, max_length=256)

        image_id: str | None = Field(default=None,pattern=r'^[a-f0-9]{32}$')
        parent_job_id: str | None = Field(default=None,pattern=r'^[a-f0-9]{32}$')

    class ClientEvent(Input):
        stage: str = Field(pattern=r'^[a-z_]{3,32}$')
        code: str = Field(pattern=r'^[a-z][a-z0-9_]{2,80}$')

    @app.post(PREFIX+'/images/client-events')
    async def client_event(body:ClientEvent,uid=Depends(user)):
        with service.store.tx() as db:
            db.execute('DELETE FROM image_client_events WHERE created<?',(time.time()-7*86400,))
            if db.execute('SELECT COUNT(*) FROM image_client_events WHERE uid=? AND created>?',(uid,time.time()-60)).fetchone()[0]>=12:raise Fault('rate_limited',429)
            db.execute('INSERT INTO image_client_events VALUES(?,?,?,?)',(uid,body.stage,body.code,time.time()))
        return {'ok':True}

    @app.get(PREFIX+'/images/settings')
    async def settings(uid=Depends(user)):
        options = await service.catalog(uid)
        options['credits_per_image'] = service.providers.config.image_credits if service.providers else 0
        options['unlimited'] = service.store.unlimited(uid)
        return options

    @app.patch(PREFIX+'/images/settings')
    async def save(body: Settings, uid=Depends(user)):
        options = await service.catalog(uid)
        if not body.model and not body.edit_model:raise Fault('image_model_not_available',409)
        for field in ['model','edit_model']:
            value=getattr(body,field)
            if value and value not in {m['id'] for m in options['edit_models' if field=='edit_model' else 'models']}:raise Fault('image_model_not_available',409)
        with service.store.tx() as db:
            db.execute("INSERT OR IGNORE INTO image_preferences(uid,model) VALUES(?, '')",(uid,))
            if body.model:db.execute('UPDATE image_preferences SET model=? WHERE uid=?',(body.model,uid))
            if body.edit_model:db.execute('UPDATE image_preferences SET edit_model=? WHERE uid=?',(body.edit_model,uid))
        return await service.catalog(uid)

    @app.get(PREFIX+'/images/jobs')
    async def jobs(uid=Depends(user)):
        with service.store.lock:
            ids = [r['id'] for r in service.store.db.execute('SELECT id FROM image_jobs WHERE uid=? ORDER BY created DESC LIMIT 30', (uid,))]
        return {'ok': True, 'jobs': [service.public(uid, ident) for ident in ids]}

    @app.post(PREFIX+'/images/jobs')
    async def generate(body: Generate, uid=Depends(user)):
        return {'ok': True, 'job': await service.submit(uid, body.prompt.strip(), body.request_id, body.model, body.image_id, body.parent_job_id)}

    @app.get(PREFIX+'/images/jobs/{ident}')
    async def job(ident: str, uid=Depends(user)):
        return {'ok': True, 'job': service.public(uid, ident)}

    @app.get(PREFIX+'/images/jobs/{ident}/file')
    async def file(ident: str, uid=Depends(user)):
        job = service.public(uid, ident)
        if job['state'] != 'succeeded': raise Fault('image_not_ready', 409)
        with service.store.lock:
            raw = service.store.db.execute('SELECT png FROM image_jobs WHERE id=? AND uid=?', (ident, uid)).fetchone()['png']
        return Response(raw, media_type='image/png', headers={'Content-Disposition': 'inline; filename="shengjian-'+ident+'.png"'})
