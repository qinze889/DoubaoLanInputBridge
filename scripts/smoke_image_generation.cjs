const {chromium}=require('../desktop/node_modules/playwright');
const {spawn}=require('node:child_process'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'shengjian-image-ui-')),origin='http://127.0.0.1:18790',out=path.resolve('artifacts/core-ui');fs.mkdirSync(out,{recursive:true});
 const server=spawn(process.env.SHENGJIAN_TEST_PYTHON||path.resolve('.venv/bin/python'),['tests/fixtures/core_ui_server.py',root,'18790'],{stdio:'ignore'});let browser;
 try{
  for(let i=0;i<100;i++){try{if((await fetch(origin+'/shengjian/api/v2/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({headless:true,executablePath:process.env.SHENGJIAN_UI_BROWSER});const page=await browser.newPage({viewport:{width:390,height:844}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  const login=async(name,password)=>{await page.getByLabel('用户名',{exact:true}).fill(name);await page.getByLabel('密码',{exact:true}).fill(password);await page.getByRole('button',{name:'登录',exact:true}).click();await page.locator('#workspace').waitFor({state:'visible'});};
  await page.goto(origin+'/shengjian/api/v2/console');await login('browser-test','browser-password-123');
  await page.locator('#model-settings summary').click();await page.locator('#image-model').selectOption('fixture-image-b');await page.waitForFunction(()=>document.querySelector('#model-note').textContent.startsWith('生图模型已保存'));
  await page.reload();await page.locator('#workspace').waitFor({state:'visible'});await page.waitForFunction(()=>document.querySelector('#image-model').value==='fixture-image-b');
  await page.locator('[data-conversation-mode=image]').click();await page.locator('#image-prompt').fill('一片绿色叶子的水彩画');await page.locator('#create-image').click();await page.locator('.generated-card img').waitFor();
  assert(await page.locator('.generated-card img').evaluate(img=>img.complete&&img.naturalWidth===128));
  await page.reload();await page.locator('#workspace').waitFor({state:'visible'});await page.locator('[data-conversation-mode=image]').click();await page.locator('.generated-card img').waitFor();
  for(const colorScheme of ['light','dark']){await page.emulateMedia({colorScheme});await page.waitForTimeout(180);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:path.join(out,'image-generation-'+colorScheme+'.png'),fullPage:true});}
  const download=page.waitForEvent('download');await page.getByRole('link',{name:'保存 PNG'}).click();assert((await download).suggestedFilename().endsWith('.png'));
  await page.getByRole('button',{name:'聊这张图',exact:true}).click();await page.locator('#visual-photo').waitFor({state:'visible'});assert(await page.locator('#image-space').isHidden());
  await page.locator('#visual-clear').click();await page.locator('#prompt').fill('帮我生成一张绿色森林图片');await page.locator('.send-button').click();await page.getByRole('button',{name:'查看图片与版本',exact:true}).waitFor();
  await page.locator('#logout').click();await login('browser-second','browser-password-456');await page.locator('[data-conversation-mode=image]').click();await page.getByText('第一张作品，从一句描述开始。',{exact:true}).waitFor();assert.equal(await page.locator('.generated-card').count(),0);assert.equal(errors.length,0,errors.join('\n'));
  console.log(JSON.stringify({ok:true,checks:['select-and-persist-image-model','Responses-to-real-PNG','reload-job-recovery','PNG-download','generated-image-to-voice-chat-context','explicit-chat-image-routing','light-dark-mobile','account-isolation'],screenshots:out}));
 }finally{await browser?.close();server.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1;});
