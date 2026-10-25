const {chromium}=require('../desktop/node_modules/playwright'),{spawn}=require('node:child_process'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'shengjian-model-recovery-')),origin='http://127.0.0.1:18811';
 const server=spawn(process.env.SHENGJIAN_TEST_PYTHON||path.resolve('.venv/bin/python'),['tests/fixtures/core_ui_server.py',root,'18811'],{env:{...process.env,SHENGJIAN_FIXTURE_HARNESS:'1',SHENGJIAN_FIXTURE_STREAM:'1'},stdio:'ignore'});let browser;
 try{
  for(let i=0;i<100;i++){try{if((await fetch(origin+'/shengjian/api/v2/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({headless:true,executablePath:process.env.SHENGJIAN_UI_BROWSER});const page=await browser.newPage({viewport:{width:390,height:844}});let calls=0,sockets=0;
  page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/assistant/chat'))calls++;});
  await page.routeWebSocket(/\/tasks\/[^/]+\/stream$/,ws=>{if(sockets++===0)ws.onMessage(()=>{ws.send(JSON.stringify({seq:1,type:'model.failure',code:'model_upstream_failed',upstream_status:503}));ws.send(JSON.stringify({seq:2,type:'task.state',state:'failed'}));});else ws.connectToServer();});
  await page.goto(origin+'/shengjian/api/v2/console');await page.getByLabel('用户名',{exact:true}).fill('browser-test');await page.getByLabel('密码',{exact:true}).fill('browser-password-123');await page.getByRole('button',{name:'登录',exact:true}).click();await page.locator('#workspace').waitFor({state:'visible'});
  await page.evaluate(async()=>{const d=await json('/devices',{name:'Recovery fixture',capabilities:['tasks']});await json('/devices/'+d.id,{grants:['tasks']},'PATCH');await fetch('/__test/agent-online/'+d.id,{method:'POST'});await refresh();$('speak').checked=false;
   window.micStopped=false;navigator.mediaDevices.getUserMedia=async()=>({getTracks:()=>[{stop(){window.micStopped=true;},addEventListener(){}}]});
   window.AudioContext=class{constructor(){this.sampleRate=16000;this.state='running';this.started=performance.now();}get currentTime(){return(performance.now()-this.started)/1000;}resume(){return Promise.resolve();}close(){return Promise.resolve();}createMediaStreamSource(){return{connect(){},disconnect(){}};}createScriptProcessor(){return{connect(){},disconnect(){}};}};
  });
  await page.locator('#realtime').click();await page.waitForFunction(()=>live?.processor);
  await page.evaluate(()=>submitPrompt('合成测试：这一轮上游返回错误'));await page.waitForFunction(()=>!replyController&&!busy);assert(await page.evaluate(()=>!!live?.processor&&!micStopped),'upstream model failure must not close the microphone');assert((await page.locator('#notice').textContent()).includes('对话上游'));assert.equal(calls,1,'failed work is not automatically replayed');
  await page.evaluate(()=>submitPrompt('新的用户请求：我们继续聊'));await page.waitForFunction(()=>!replyController&&!busy);assert.equal(calls,2);assert(await page.evaluate(()=>!!live?.processor&&!micStopped));assert((await page.locator('#messages .assistant').last().textContent()).includes('第二句'));
  await page.locator('#realtime').click();assert(await page.evaluate(()=>micStopped));console.log(JSON.stringify({ok:true,upstream_error_distinguished:true,microphone_preserved:true,no_automatic_replay:true,next_user_turn_succeeds:true}));
 }finally{await browser?.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
