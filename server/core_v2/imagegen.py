"""Owned durable image jobs using the upstream Responses image_generation tool.

Single submission: a timeout/restart is unknown, never an automatic second generation.
Only configured, independently verified image models are exposed.
"""
import asyncio
import base64
import io
import json
import math
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
            queued=store.db.execute("SELECT id,uid FROM image_jobs WHERE state='queued'").fetchall()
            store.db.execute("UPDATE image_jobs SET state='failed',error='service_stopped' WHERE state='queued'")
            store.db.execute("UPDATE image_jobs SET state='unknown',error='service_restarted' WHERE state='running'")
            for row in queued:
                if store.db.execute('SELECT 1 FROM usage WHERE id=?',('image-'+row['id'],)).fetchone():store.settle(row['uid'],'image-'+row['id'],0)

    async def catalog(self, uid):
        p = self.providers
        choices = []
        if p and p.readiness()['models'] and p.config.image_models:
            await p.models()
            names={'workbuddy/cn:hunyuan-image-alpha':'Hunyuan Image Alpha · WorkBuddy','minimax/image-01':'MiniMax Image-01'}
            choices = [{'id': m, 'name': names.get(m,m.removeprefix('workbuddy/cn:').removeprefix('minimax/')),
                        'protocol': 'responses', 'verified': True} for m in p.config.image_models if m in p.discovered_ids]
        with self.store.lock:
            row = self.store.db.execute('SELECT model FROM image_preferences WHERE uid=?', (uid,)).fetchone()
        return {'ok': True, 'models': choices, 'model': row['model'] if row else choices[0]['id'] if choices else ''}

    def public(self, uid, ident):
        with self.store.lock:
            row = self.store.db.execute('SELECT id,model,prompt,state,error,image_id,entry_id,width,height,source,usage,created,updated FROM image_jobs WHERE id=? AND uid=?', (ident, uid)).fetchone()
        if not row: raise Fault('image_job_not_found', 404)
        data = dict(row)
        data['usage'] = json.loads(data['usage'])
        return data

    async def submit(self, uid, prompt, request_id, model=None):
        if not prompt.strip():raise Fault('image_prompt_required')
        # A repeated request recovers its original job, even after changing preferences.
        with self.store.lock:
            old = self.store.db.execute('SELECT id,prompt,model FROM image_jobs WHERE uid=? AND request_id=?', (uid, request_id)).fetchone()
        if old:
            if prompt != old['prompt'] or (model and model != old['model']): raise Fault('idempotency_conflict', 409)
            return self.public(uid, old['id'])
        options = await self.catalog(uid)
        model = model or options['model']
        if model not in {m['id'] for m in options['models']}: raise Fault('image_model_not_available', 409)
        payload = {'model': model, 'input': prompt, 'tools': [{'type': 'image_generation'}],
                   'tool_choice': {'type': 'image_generation'}, 'stream': False}
        ident = secrets.token_hex(16)
        with self.store.tx() as db:
            if db.execute("SELECT 1 FROM image_jobs WHERE uid=? AND state IN ('queued','running')", (uid,)).fetchone(): raise Fault('image_job_busy', 409)
            if db.execute('SELECT COALESCE(SUM(length(png)),0) FROM image_jobs WHERE uid=?', (uid,)).fetchone()[0] > 184*1024*1024: raise Fault('image_storage_full', 413)
            db.execute('INSERT INTO image_jobs(id,uid,request_id,fingerprint,model,prompt,state,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',
                       (ident, uid, request_id, digest(encode(payload)), model, prompt, 'queued', time.time(), time.time()))
        try:
            # Fixed application credits per successful image, separate from upstream money/credit units.
            self.store.reserve(uid, 'image-'+ident, self.providers.config.image_credits, digest(encode(payload)))
        except Fault:
            self.finish(ident, 'failed', 'insufficient_credits')
            raise
        task = asyncio.create_task(self.generate(uid, ident, payload))
        self.tasks.add(task); task.add_done_callback(self.tasks.discard)
        return self.public(uid, ident)

    def finish(self, ident, state, error=''):
        with self.store.tx() as db:
            db.execute('UPDATE image_jobs SET state=?,error=?,updated=? WHERE id=?', (state, error, time.time(), ident))

    async def generate(self, uid, ident, payload):
        submitted = False
        response_received = False
        try:
            async with self.gate:
                self.finish(ident, 'running')
                async with self.providers.client() as client:
                    submitted = True
                    async with client.stream('POST', self.providers.config.model_base+'/responses',
                                             headers={'Authorization': 'Bearer '+self.providers.config.model_key, 'X-Request-ID': 'image-'+ident},
                                             json=payload, timeout=httpx.Timeout(300, connect=10)) as response:
                        if response.status_code != 200:
                            if 400 <= response.status_code < 500:
                                self.store.settle(uid, 'image-'+ident, 0)
                                self.finish(ident, 'failed', 'image_provider_rejected')
                                return
                            raise Fault('image_result_unknown', 502)
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            raw.extend(chunk)
                            if len(raw) > 32*1024*1024: raise ValueError('oversized image response')
                response_received = True
                data = json.loads(raw)
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
                    'text': 'AI 生成图片。模型：'+payload['model']+'；需求：'+payload['input'], 'images': [image['id']]})
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
        except Exception:
            self.finish(ident, 'unknown', 'image_result_unknown')

    async def close(self):
        for task in list(self.tasks): task.cancel()
        await asyncio.gather(*list(self.tasks), return_exceptions=True)


def mount(app, service, user):
    from .app import Input, PREFIX

    class Settings(Input):
        model: str = Field(min_length=1, max_length=256)

    class Generate(Input):
        prompt: str = Field(min_length=1, max_length=4000)
        request_id: str = Field(min_length=16, max_length=128)
        model: str | None = Field(default=None, min_length=1, max_length=256)

    @app.get(PREFIX+'/images/settings')
    async def settings(uid=Depends(user)):
        options = await service.catalog(uid)
        options['credits_per_image'] = service.providers.config.image_credits if service.providers else 0
        return options

    @app.patch(PREFIX+'/images/settings')
    async def save(body: Settings, uid=Depends(user)):
        options = await service.catalog(uid)
        if body.model not in {m['id'] for m in options['models']}: raise Fault('image_model_not_available', 409)
        with service.store.tx() as db:
            db.execute('INSERT INTO image_preferences VALUES(?,?) ON CONFLICT(uid) DO UPDATE SET model=excluded.model', (uid, body.model))
        return await service.catalog(uid)

    @app.get(PREFIX+'/images/jobs')
    async def jobs(uid=Depends(user)):
        with service.store.lock:
            ids = [r['id'] for r in service.store.db.execute('SELECT id FROM image_jobs WHERE uid=? ORDER BY created DESC LIMIT 30', (uid,))]
        return {'ok': True, 'jobs': [service.public(uid, ident) for ident in ids]}

    @app.post(PREFIX+'/images/jobs')
    async def generate(body: Generate, uid=Depends(user)):
        return {'ok': True, 'job': await service.submit(uid, body.prompt.strip(), body.request_id, body.model)}

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
