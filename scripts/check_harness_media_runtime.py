"""Verify real pinned SDK tools and expansion of a legacy model profile."""
import os,sys,asyncio,tempfile,subprocess,json,time,shutil
from pathlib import Path
import httpx
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root));from server.desktop_agent.sdk import SDKHarness
scratch=Path(tempfile.mkdtemp(prefix='shengjian-sdk-media-'));port=18810
server=subprocess.Popen([sys.executable,str(root/'tests/fixtures/core_ui_server.py'),str(scratch/'core'),str(port)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
async def main():
 engine=None
 try:
  async with httpx.AsyncClient(timeout=20,trust_env=False) as c:
   base=f'http://127.0.0.1:{port}/shengjian/api/v2'
   for _ in range(60):
    try:
     if (await c.get(base+'/health')).status_code==200:break
    except httpx.HTTPError:pass
    await asyncio.sleep(.1)
   r=await c.post(base+'/auth/login',json={'username':'browser-test','password':'browser-password-123'});r.raise_for_status();token=r.json()['token'];headers={'Authorization':'Bearer '+token}
   r=await c.post(base+'/devices',headers=headers,json={'name':'SDK Media Fixture','capabilities':['tasks']});r.raise_for_status();d=r.json();await c.patch(base+'/devices/'+d['id'],headers=headers,json={'grants':['tasks']})
   async def emit(event):pass
   workspace=scratch/'work';workspace.mkdir()
   class LegacySDK(SDKHarness):
    def model_facts(self):return {'context_window':32768,'max_output_tokens':2048}
   engine=LegacySDK([shutil.which('node'),str(root/'tools/dsh/node_modules/@deepseek-ai/dsh/lib/bin.js')],workspace,emit,{'server':base,'token':d['token'],'text_model':'fixture-text'},scratch/'runtime')
   engine.local_tools=object()
   await engine.start()
   for _ in range(60):
    state=scratch/'runtime/home/shengjian-media-runtime.json'
    if state.exists():
     data=json.loads(state.read_text())
     if data.get('context_window')==1000000:
      assert len(data.get('tools',[]))==5 and data.get('default_max_tokens')==8192
      print(json.dumps({'ok':True,'runtime':data}));return
     if data.get('error_class'):raise RuntimeError('Media plugin initialization failed')
    await asyncio.sleep(.2)
   raise RuntimeError('Media runtime metadata not ready')
 finally:
  if engine:engine.local_tools=None;await engine.close()
  server.terminate();server.wait(timeout=5)
asyncio.run(main())
