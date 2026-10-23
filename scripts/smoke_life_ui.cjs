const { chromium } = require('../desktop/node_modules/playwright');
const { spawn } = require('node:child_process');
const fs = require('node:fs');const os=require('node:os');const path=require('node:path');const assert=require('node:assert/strict');
(async()=>{
 const directory=fs.mkdtempSync(path.join(os.tmpdir(),'shengjian-life-ui-')),origin='http://127.0.0.1:18781';
 const server=spawn(path.resolve('.venv/bin/python'),['tests/fixtures/core_ui_server.py',directory,'18781'],{stdio:'ignore'});let browser;
 try {
  for(let i=0;i<100;i++){try{if((await fetch(origin+'/shengjian/api/v2/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({headless:true,executablePath:process.env.SHENGJIAN_UI_BROWSER});
  const context=await browser.newContext({viewport:{width:390,height:844},colorScheme:'dark'}),page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(origin+'/shengjian/api/v2/console');await page.getByLabel('用户名',{exact:true}).fill('browser-test');await page.getByLabel('密码',{exact:true}).fill('browser-password-123');await page.getByRole('button',{name:'登录',exact:true}).click();await page.locator('#workspace').waitFor({state:'visible'});
  await page.locator('[data-page="life"]').click();await page.locator('#life-note').fill('今天在公园散步，感觉不错。');await page.getByRole('button',{name:'保存文字',exact:true}).click();await page.locator('#life-timeline').getByText('今天在公园散步，感觉不错。',{exact:true}).waitFor();
  assert.equal(await page.locator('#life-camera').getAttribute('capture'),'environment');
  const png=await page.evaluate(()=>{const c=document.createElement('canvas');c.width=128;c.height=128;c.getContext('2d').fillRect(0,0,128,128);return c.toDataURL('image/png').split(',')[1];});
  await page.locator('#life-files').setInputFiles({name:'photo.png',mimeType:'image/png',buffer:Buffer.from(png,'base64')});await page.waitForFunction(()=>document.querySelector('#life-timeline img')?.naturalWidth>0);
  await page.locator('#life-consolidate').click();await page.getByRole('heading',{name:/已沉淀/}).waitFor({timeout:20000});await page.locator('#life-memories textarea').waitFor();
  await page.getByRole('button',{name:'查看来源',exact:true}).click();await page.locator('#life-source .life-entry').waitFor();
  await context.setOffline(true);await page.locator('#life-note').fill('断网时留下的一句话。');await page.getByRole('button',{name:'保存文字',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#life-status').textContent.includes('浏览器'));
  await context.setOffline(false);await page.locator('#life-timeline').getByText('断网时留下的一句话。',{exact:true}).waitFor({timeout:20000});
  await page.locator('#life-note').fill('请用一句话回应我');await page.getByRole('button',{name:'聊一聊并记录',exact:true}).click();await page.locator('#life-timeline').getByText('已收到你的消息。',{exact:true}).waitFor();
  // A poll must not discard a memory edit in progress.
  await page.locator('#life-memories textarea').fill('我正在修改');await page.waitForTimeout(10500);assert.equal(await page.locator('#life-memories textarea').inputValue(),'我正在修改');
  await page.screenshot({path:path.join(directory,'life-mobile.png'),fullPage:true});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'mobile width overflow');
  await page.setViewportSize({width:1200,height:900});await page.emulateMedia({colorScheme:'light'});await page.screenshot({path:path.join(directory,'life-desktop.png'),fullPage:true});
  const logout=page.locator('#logout');await logout.click();await page.getByLabel('用户名',{exact:true}).fill('browser-second');await page.getByLabel('密码',{exact:true}).fill('browser-password-456');await page.getByRole('button',{name:'登录',exact:true}).click();await page.locator('#workspace').waitFor({state:'visible'});await page.locator('[data-page="life"]').click();await page.getByText('还没有记录。写下一句话，或拍下今天的第一张照片。',{exact:true}).waitFor();assert.equal(await page.locator('#life-memories textarea').count(),0);assert.equal(errors.length,0,errors.join('\n'));
  console.log(JSON.stringify({ok:true,checks:['mobile-dark','desktop-light','record','photo','consolidate','sources','offline-retry','conversation','edit-preserved','account-isolation'],screenshots:directory}));
 }finally{await browser?.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1});
