const {logoutUser}=require('./ui_helpers.cjs');
const {chromium}=require('../desktop/node_modules/playwright'),{spawn}=require('node:child_process'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'shengjian-chat-media-')),origin='http://127.0.0.1:18809';
 const server=spawn(process.env.SHENGJIAN_TEST_PYTHON||path.resolve('.venv/bin/python'),['tests/fixtures/core_ui_server.py',folder,'18809'],{env:{...process.env,SHENGJIAN_FIXTURE_HARNESS:'1'},stdio:'ignore'});let browser;
 try{
  for(let i=0;i<100;i++){try{if((await fetch(origin+'/shengjian/api/v2/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({headless:true,executablePath:process.env.SHENGJIAN_UI_BROWSER});const page=await browser.newPage({viewport:{width:390,height:844}});let task='',cid='',complete=false,modelCalls=0,imagePosts=0;
  const errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/assistant/chat'))modelCalls++;if(r.method()==='POST'&&r.url().endsWith('/images/jobs'))imagePosts++;});
  page.on('response',async r=>{if(r.request().method()==='POST'&&r.url().endsWith('/assistant/chat')){const d=await r.json();if(!task){task=d.task.id;cid=d.conversation_id;}}});
  await page.route('**/assistant/conversations/*/images',async route=>{await route.fulfill({json:{ok:true,jobs:task?[{id:'a'.repeat(32),task_id:task,state:complete?'succeeded':'running',operation:'generate',prompt:'红色纸雕小猫，柔和侧光',model:'fixture-image-a',width:32,height:32,created:1,image_id:complete?'b'.repeat(32):null}]:[]}});});
  await page.route('**/images/jobs/'+ 'a'.repeat(32)+'/file',route=>route.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jQh0AAAAASUVORK5CYII=','base64')}));
  await page.goto(origin+'/shengjian/api/v2/console');await page.getByLabel('用户名',{exact:true}).fill('browser-test');await page.getByLabel('密码',{exact:true}).fill('browser-password-123');await page.getByRole('button',{name:'登录',exact:true}).click();await page.locator('#workspace').waitFor({state:'visible'});
  await page.evaluate(async()=>{const d=await json('/devices',{name:'Media Harness',capabilities:['tasks']});await json('/devices/'+d.id,{grants:['tasks']},'PATCH');await fetch('/__test/agent-online/'+d.id,{method:'POST'});await refresh();$('speak').checked=false;});
  await page.locator('#prompt').fill('结合刚才聊的纸雕风格，帮我生成一张图片');await page.getByRole('button',{name:'发送',exact:true}).click();
  await page.locator('.inline-media-card').waitFor();assert.equal(await page.evaluate(()=>document.body.dataset.activePage),'conversation');assert.equal(imagePosts,0,'no regex diversion to direct image API');assert.equal(modelCalls,1);
  await page.waitForFunction(()=>document.querySelectorAll('[data-chat-task]').length===1&&!replyController);await page.locator('#prompt').fill('图片慢慢画，我们继续聊刚才的灯光');await page.getByRole('button',{name:'发送',exact:true}).click();await page.waitForFunction(()=>document.querySelectorAll('[data-chat-task]').length===2&&!replyController);
  assert.equal(modelCalls,2,'chat continues while the image is still running');assert((await page.locator('.inline-media-status').textContent()).includes('生成'));
  await page.locator('#prompt').fill('还没发出的草稿');await page.locator('#prompt').focus();complete=true;await page.locator('.inline-media-card img').waitFor();assert(await page.locator('#prompt').evaluate(e=>document.activeElement===e),'completion does not steal focus');assert.equal(await page.locator('#prompt').inputValue(),'还没发出的草稿');assert.equal(await page.evaluate(()=>document.body.dataset.activePage),'conversation');
  await page.evaluate(()=>{window.ShengjianVisual.useSaved=async id=>{window.selectedInlineImage=id;return true;};});await page.locator('.inline-media-card button').click();assert.equal(await page.locator('#prompt').inputValue(),'继续调整这张图片：');assert.equal(await page.evaluate(()=>selectedInlineImage),'b'.repeat(32));assert.equal(await page.evaluate(()=>document.body.dataset.activePage),'conversation');
  await page.setViewportSize({width:320,height:640});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.reload();await page.locator('#workspace').waitFor({state:'visible'});await page.locator('.inline-media-card img').waitFor();assert.equal(modelCalls,2,'history restore never repeats generation or model calls');assert.equal(imagePosts,0);assert.equal(await page.evaluate(()=>window.ShengjianProduct.conversationFor()),cid);
  await logoutUser(page);await page.waitForFunction(()=>!document.querySelector('.inline-media-card'));assert.equal(errors.length,0,errors.join('\n'));
  console.log(JSON.stringify({ok:true,main_chat_driven:true,no_image_keyword_diversion:true,nonblocking_generation:true,inline_image:true,focus_preserved:true,history_without_replay:true,logout_cleanup:true,mobile_320:true}));
 }finally{await browser?.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
