// Browser-only verification: native IPC and desktop APIs use isolated fixtures.
const { createRequire } = require('node:module');
const desktopRequire = createRequire(require('node:path').resolve(__dirname, '../desktop/package.json'));
const { chromium } = desktopRequire(process.env.SHENGJIAN_PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
(async () => {
 const output = process.env.SHENGJIAN_UI_OUTPUT || path.resolve(__dirname, '../build/windows-ui-check');
 await fs.mkdir(output, {recursive:true});
 const browser = await chromium.launch({headless:true,...(process.env.SHENGJIAN_UI_BROWSER ? {executablePath:process.env.SHENGJIAN_UI_BROWSER} : {})});
 const context = await browser.newContext({viewport:{width:1180,height:760},colorScheme:'light'});
 const page = await context.newPage();
 const errors=[]; const calls=[];
 let mockAgentEnabled=false;
 page.on('pageerror', error => errors.push(error.message));
 await page.addInitScript(() => {
  let next=0; const callbacks=new Map();
  window.__uiClipboard='';
  Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.__uiClipboard=text;}}});
  window.__TAURI_INTERNALS__={
   metadata:{currentWindow:{label:'main'},currentWebview:{label:'main'}},
   transformCallback:fn=>{callbacks.set(++next,fn);return next;},
   unregisterCallback:id=>callbacks.delete(id),
   invoke:async (cmd,args)=>{
    if(cmd==='bridge_runtime')return {running:true,port:18700,key:'ui-fixture-only'};
    if(cmd==='plugin:dialog|open')return ['C:\\UI-Fixtures\\项目资料.pdf'];
    if(cmd==='plugin:event|listen')return ++next;
    if(cmd==='plugin:event|unlisten')return;
    throw Error('Unexpected native call: '+cmd);
   }
  };
  window.__TAURI_EVENT_PLUGIN_INTERNALS__={unregisterListener:()=>{}};
 });
 const modes=[
  {id:'public',title:'固定公网',description:'通过固定域名连接，电脑与手机无需处于同一网络。',available:true,configured:true},
  {id:'cloudflare',title:'CF 隧道',description:'临时公网连接，关闭后地址失效。',available:true,configured:true},
  {id:'p2p',title:'P2P 直连',description:'设备直接连接，内容不经过服务器。',available:true,configured:true},
  {id:'lan',title:'局域网',description:'同一 Wi-Fi 或内网直接连接。',available:true,configured:true}
 ];
 let mode='public',enabled=true,keyVersion=1, failPublish=false;
 const state=()=>({ok:true,mode,enabled,ready:enabled,phase:enabled?'ready':'stopped',url:enabled?`https://example.invalid/shengjian/ui-fixture/#${keyVersion}`:'',error:'',p2p:{connections:0},modes});
 const records=[{id:'text1',type:'text',text:'把突然想到的灵感，轻轻送到电脑。',ts:1792718130,category:'text',has_thumbnail:false,summary:{kind:'文字',preview:'把突然想到的灵感，轻轻送到电脑。',info:'手机 → 电脑'}},{id:'file1',type:'file',ts:1792717330,category:'file',has_thumbnail:false,summary:{kind:'文件',preview:'项目资料.pdf',info:'手机 → 电脑 · 128 KB'}}];
 await page.route('http://127.0.0.1:18700/**',async route=>{
  const req=route.request(),u=new URL(req.url()); const data=req.postDataJSON()||{};
  calls.push({path:u.pathname,method:req.method(),query:Object.fromEntries(u.searchParams),data});
  let result={ok:true}; let status=200;
  if(u.pathname==='/desktop/state')result={ok:true,version:'1.4.0',port:18700,key:'ui-fixture-only',mobile_url:'https://example.invalid',local_url:'http://192.168.1.8:18700/',host:'Windows',data_dir:'C:\\UI-Fixtures'};
  else if(u.pathname==='/desktop/account')result={ok:true,authenticated:false};
  else if(u.pathname==='/desktop/account/login')result={ok:true,authenticated:true};
  else if(u.pathname==='/desktop/account/qr')result={ok:true,authenticated:true,url:'https://example.invalid/console#login=fixture-only',expires_at:Date.now()/1000+120};
  else if(u.pathname==='/desktop/account/logout')result={ok:true,authenticated:false};
  else if(u.pathname==='/desktop/agent')result={ok:true,phase:mockAgentEnabled?'running':'off',connected:mockAgentEnabled,workspace:'C:/Users/Test/Documents/声笺任务',version:'0.2.1-rc.2',active_tasks:0};
  else if(u.pathname==='/desktop/agent/start'){mockAgentEnabled=true;result={ok:true,phase:'running',connected:true,workspace:'C:/Users/Test/Documents/声笺任务',version:'0.2.1-rc.2',active_tasks:0};}
  else if(u.pathname==='/desktop/agent/stop'){mockAgentEnabled=false;result={ok:true,phase:'off',connected:false,workspace:'C:/Users/Test/Documents/声笺任务',version:'0.2.1-rc.2',active_tasks:0};}
  else if(u.pathname==='/desktop/agent/task')result={ok:true,reply:'已提交测试任务'};
  else if(u.pathname==='/desktop/connections'){
   if(req.method()==='POST'){mode=data.mode;enabled=data.enabled;}
   result=state();
  }
  else if(u.pathname==='/desktop/key/regenerate'){keyVersion++;result={ok:true,key:'ui-fixture-only',mobile_url:state().url};}
  else if(u.pathname==='/desktop/history'){
   const items=records.filter(r=>(u.searchParams.get('category')==='all'||u.searchParams.get('category')===r.category)&&(!u.searchParams.get('q')||r.summary.preview.includes(u.searchParams.get('q'))));
   result={ok:true,items,total:items.length,has_more:false};
  }
  else if(u.pathname==='/desktop/update')result={ok:true,result:{configured:true,available:false,version:'1.4.0'}};
  else if(u.pathname==='/desktop/peers')result={ok:true,device:{name:'Windows 电脑'},peers:[{id:'mac1',name:'我的 Mac',endpoint:'https://example.invalid'}],jobs:[],network:{endpoint:'https://example.invalid',tunnel:{phase:'ready',ready:true,error:'',cloudflared_available:true}}};
  else if(u.pathname==='/desktop/peers/invite')result={ok:true,invitation:'shengjian://pair?fixture=only',expires_in:300};
  else if(u.pathname==='/desktop/config')result={ok:true,minimax_configured:false,minimax_model:'',update_url:'',update_source:'github'};
  else if(u.pathname==='/desktop/publish'&&failPublish){result={ok:false,error:'测试：连接已中断，请重试'};status=503;}
  await route.fulfill({status,contentType:'application/json',headers:{'access-control-allow-origin':'*'},body:JSON.stringify(result)});
 });
 const nav=label=>page.getByRole('navigation').getByRole('button',{name:label,exact:true});
 const checkHeading=async text=>assert.equal(await page.locator('h1').innerText(),text);
 const assertNoOverflow=async()=>{
  const over=await page.locator('.workspace, .connection-card, .feature-grid, .page-content, .machine-pair-grid').evaluateAll(nodes=>nodes.filter(n=>n.scrollWidth>n.clientWidth+2).map(n=>n.className));
  assert.deepEqual(over,[]);
 };
 try {
  await page.goto(process.env.SHENGJIAN_UI_URL || 'http://127.0.0.1:1420');
  await page.getByText('固定公网已就绪',{exact:true}).first().waitFor();
  await checkHeading('连接你的手机'); await assertNoOverflow();
  await page.getByRole('textbox',{name:'用户名',exact:true}).fill('ui-test');
  await page.getByLabel('密码',{exact:true}).fill('fixture-password-123');
  await page.getByRole('button',{name:'登录',exact:true}).click();
  await page.getByText('已登录，手机扫码即可对话',{exact:true}).waitFor();
  await page.getByRole('button',{name:'刷新语音二维码',exact:true}).click();
  assert(calls.some(c=>c.path==='/desktop/account/qr'));
  await page.screenshot({path:path.join(output, 'connect-light.png')});
  await page.getByRole('button',{name:'局域网',exact:true}).click();
  await page.getByText('局域网已就绪',{exact:true}).first().waitFor();
  assert(calls.some(c=>c.path==='/desktop/connections'&&c.data.mode==='lan'));
  await page.getByRole('button',{name:'复制连接',exact:true}).click();
  assert.equal(await page.evaluate(()=>window.__uiClipboard),state().url);
  await page.getByRole('button',{name:'刷新',exact:true}).click();
  await page.waitForTimeout(2200);
  await page.getByRole('button',{name:'复制连接',exact:true}).click();
  assert.equal(await page.evaluate(()=>window.__uiClipboard),state().url); assert.equal(keyVersion,2);
  await page.getByRole('switch',{name:'启用连接'}).click();
  await page.getByText('开启连接后显示二维码',{exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:'复制连接',exact:true}).isEnabled(),false);
  await page.getByRole('switch',{name:'启用连接'}).click();
  await page.getByText('局域网已就绪',{exact:true}).first().waitFor();
  await page.getByRole('button',{name:/发送文字 写下内容/}).click();
  await page.getByRole('dialog').waitFor();
  const text=page.getByRole('textbox',{name:'文字内容'});
  assert.equal(await text.evaluate(element=>element===document.activeElement),true);
  await text.fill('界面测试，仅使用隔离接口。');
  await page.getByRole('button',{name:'发送到手机',exact:true}).click();
  await page.getByRole('dialog').waitFor({state:'hidden'});
  assert(calls.some(c=>c.path==='/desktop/publish'&&c.data.text==='界面测试，仅使用隔离接口。'));
  await page.getByRole('button',{name:/照片、文件，随手传/}).click();
  assert.equal(await page.getByRole('button',{name:/拖入文件，或点击选择/}).evaluate(element=>element===document.activeElement),true);
  await page.getByRole('button',{name:/拖入文件，或点击选择/}).click();
  await page.getByText('已选择 1 个文件').waitFor();
  await page.getByRole('button',{name:'发送到手机',exact:true}).click();
  await page.getByRole('dialog').waitFor({state:'hidden'});
  assert(calls.some(c=>c.path==='/desktop/publish'&&c.data.paths?.[0]==='C:\\UI-Fixtures\\项目资料.pdf'));
  failPublish=true;
  await page.getByRole('button',{name:/发送文字 写下内容/}).click();
  await text.fill('失败时应保留的草稿');
  await page.getByRole('button',{name:'发送到手机',exact:true}).click();
  await page.getByRole('alert').waitFor();
  assert.equal(await text.inputValue(),'失败时应保留的草稿');
  await page.keyboard.press('Escape'); failPublish=false;
  await nav('传输记录').click(); await checkHeading('传输记录');
  await page.getByText('项目资料.pdf',{exact:true}).waitFor(); await assertNoOverflow(); await page.locator('.toast').waitFor({state:'hidden'}); await page.screenshot({path:path.join(output, 'history.png')});
  await page.getByRole('button',{name:'打开所在目录',exact:true}).click();
  assert(calls.some(c=>c.path==='/desktop/open'&&c.data.id==='file1'&&c.data.mode==='folder'));
  await page.getByPlaceholder('搜索文字、文件名、路径或类型').fill('不存在的记录');
  await page.getByText('没有找到相关记录',{exact:true}).waitFor();
  await nav('机器共享').click(); await checkHeading('机器共享');
  await page.getByText('我的 Mac',{exact:true}).waitFor();
  await page.getByRole('button',{name:'生成邀请',exact:true}).click();
  await page.getByRole('button',{name:/复制邀请/}).waitFor(); await assertNoOverflow();
  await page.locator('.toast').waitFor({state:'hidden'}); await page.screenshot({path:path.join(output, 'machines.png')}); await page.keyboard.press('Escape'); await checkHeading('机器共享');
  await nav('设置').click(); await checkHeading('设置');
  await nav('电脑 Agent').click(); await checkHeading('电脑 Agent');
  await page.getByRole('button',{name:'启用 DeepSeek Harness',exact:true}).click();
  await page.getByText('已连接',{exact:true}).waitFor();
  await page.getByRole('textbox',{name:'电脑任务',exact:true}).fill('创建测试说明');
  await page.getByRole('button',{name:'交给 Harness 执行',exact:true}).click();
  await page.getByText('已提交测试任务',{exact:true}).waitFor();
  await page.getByRole('button',{name:'停止 Agent',exact:true}).click();
  assert(calls.some(c=>c.path==='/desktop/agent/start'));
  await nav('设置').click();
  await page.getByRole('button',{name:'检查更新',exact:true}).click();
  await page.getByText('当前已是最新版 1.4.0').first().waitFor();
  await page.locator('.toast').waitFor({state:'hidden'}); await page.screenshot({path:path.join(output, 'settings.png')}); await nav('连接设备').click(); await checkHeading('连接你的手机');
  await page.getByText('局域网已就绪',{exact:true}).first().waitFor();
  await page.setViewportSize({width:900,height:620}); await assertNoOverflow();
  await page.screenshot({path:path.join(output, 'connect-small.png')});
  await page.emulateMedia({colorScheme:'dark'}); await page.waitForTimeout(250); await assertNoOverflow();
  await page.setViewportSize({width:1180,height:760});
  await page.screenshot({path:path.join(output, 'connect-dark.png')});
  await page.keyboard.press('Control+2'); await checkHeading('传输记录');
  await page.keyboard.press('Control+,'); await checkHeading('设置');
  await page.keyboard.press('Control+n'); await page.getByRole('dialog').waitFor();
  await page.keyboard.press('Escape');
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({passed:true,checks:['navigation','connection-switch','qr-refresh','connection-toggle','text-sharing','file-picker-sharing','failed-send-keeps-draft','history-filter','open-containing-folder','machine-polling-and-invitation','settings-update','keyboard-shortcuts','light-dark-small-layout'],syntheticOnly:true,apiCalls:calls.length,pageErrors:errors}));
 } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
