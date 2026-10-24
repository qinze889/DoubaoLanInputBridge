const {openModels,closeModels,toggleModels,setSpeech,logoutUser}=require('./ui_helpers.cjs');
const {chromium}=require('../desktop/node_modules/playwright');
const {spawn}=require('node:child_process'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const directory=fs.mkdtempSync(path.join(os.tmpdir(),'shengjian-mobile-ui-')),origin='http://127.0.0.1:18789',out=path.resolve('artifacts/core-ui');fs.mkdirSync(out,{recursive:true});
 const server=spawn(process.env.SHENGJIAN_TEST_PYTHON||path.resolve('.venv/bin/python'),['tests/fixtures/core_ui_server.py',directory,'18789'],{stdio:'ignore'});let browser;
 try{
  for(let i=0;i<100;i++){try{if((await fetch(origin+'/shengjian/api/v2/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({headless:true,executablePath:process.env.SHENGJIAN_UI_BROWSER});
  const page=await browser.newPage({viewport:{width:390,height:844}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  async function login(name,password){await page.getByLabel('用户名',{exact:true}).fill(name);await page.getByLabel('密码',{exact:true}).fill(password);await page.getByRole('button',{name:'登录',exact:true}).click();await page.locator('#workspace').waitFor({state:'visible'});}
  await page.goto(origin+'/shengjian/api/v2/console');await login('browser-test','browser-password-123');
  for(const colorScheme of ['light','dark'])for(const width of [320,390,1100]){
    await page.emulateMedia({colorScheme});await page.setViewportSize({width,height:844});
    for(const section of ['conversation','create','life','tasks','devices']){
      await page.locator('[data-page="'+section+'"]').click();
      await page.waitForTimeout(180);
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),section+' overflow at '+width);
      await page.screenshot({path:path.join(out,`mobile-${section}-${colorScheme}-${width}.png`),fullPage:true});
    }
  }
  await page.locator('[data-page="conversation"]').click();await toggleModels(page);
  await page.locator('#chat-model').selectOption('fixture-text-alternative');await page.waitForFunction(()=>document.querySelector('#current-model-name').textContent==='fixture text alternative');
  await page.locator('#chat-vision-model').selectOption('fixture-vision-alternative');await page.waitForFunction(()=>!document.querySelector('#chat-vision-model').disabled);
  await page.reload();await page.locator('#workspace').waitFor({state:'visible'});await toggleModels(page);
  assert.equal(await page.locator('#chat-model').inputValue(),'fixture-text-alternative');await page.waitForFunction(()=>document.querySelector('#chat-vision-model').value==='fixture-vision-alternative');
  await page.setViewportSize({width:390,height:844});await page.emulateMedia({colorScheme:'light'});await page.waitForTimeout(180);await page.screenshot({path:path.join(out,'mobile-model-settings.png'),fullPage:true});
  await logoutUser(page);await login('browser-second','browser-password-456');
  assert.equal(await page.locator('#chat-model').inputValue(),'fixture-text');await page.waitForFunction(()=>!document.querySelector('#chat-vision-model').disabled);assert.equal(await page.locator('#chat-vision-model').inputValue(),'');
  assert.equal(errors.length,0,errors.join('\n'));console.log(JSON.stringify({ok:true,checks:['5-product-sections','320-390-1100-width','light-dark','chat-and-vision-selection','reload-persistence','account-isolation'],screenshots:out}));
 }finally{await browser?.close();server.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1;});
