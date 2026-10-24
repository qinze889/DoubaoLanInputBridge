const {chromium}=require('../desktop/node_modules/playwright');
const {spawn}=require('node:child_process'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'shengjian-edit-ui-')),origin='http://127.0.0.1:18791',out=path.resolve('artifacts/core-ui');fs.mkdirSync(out,{recursive:true});
 const server=spawn(process.env.SHENGJIAN_TEST_PYTHON||path.resolve('.venv/bin/python'),['tests/fixtures/core_ui_server.py',root,'18791'],{env:{...process.env,SHENGJIAN_FIXTURE_VISUAL:'1',SHENGJIAN_FIXTURE_STREAM:'1'},stdio:'ignore'});let browser;
 try{
  for(let i=0;i<100;i++){try{if((await fetch(origin+'/shengjian/api/v2/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({headless:true,executablePath:process.env.SHENGJIAN_UI_BROWSER});const page=await browser.newPage({viewport:{width:390,height:844}}),errors=[],submissions=[],work=[];page.setDefaultTimeout(20000);
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST'&&new URL(r.url()).pathname.replace(/\/$/,'').endsWith('/images/jobs'))submissions.push(JSON.parse(r.postData()));if(r.url().endsWith('/assistant/chat'))work.push(r.url());});
  let voice='把背景改成黄色';
  await page.routeWebSocket(/\/voice\/asr\/stream$/,socket=>{socket.onMessage(data=>{if(typeof data==='string'){const c=JSON.parse(data);if(c.token)socket.send(JSON.stringify({type:'asr.ready',partial_results:true}));if(c.type==='finish'){socket.send(JSON.stringify({type:'asr.final',text:voice}));socket.send(JSON.stringify({type:'asr.finished'}));}}else socket.send(JSON.stringify({type:'asr.partial',text:voice}));});});
  const login=async(name,password)=>{await page.getByLabel('用户名',{exact:true}).fill(name);await page.getByLabel('密码',{exact:true}).fill(password);await page.getByRole('button',{name:'登录',exact:true}).click();await page.locator('#workspace').waitFor({state:'visible'});};
  const fakeAudio=async()=>page.evaluate(()=>{
   navigator.mediaDevices.getUserMedia=async()=>({getTracks:()=>[{stop(){},addEventListener(){}}]});
   window.AudioContext=class{constructor(){this.sampleRate=16000;this.state='running';this.started=performance.now();}get currentTime(){return(performance.now()-this.started)/1000;}resume(){return Promise.resolve();}close(){return Promise.resolve();}createMediaStreamSource(){return{connect(){},disconnect(){}};}createScriptProcessor(){return{connect(){},disconnect(){}};}createBuffer(c,length,rate){return{duration:length/rate,getChannelData:()=>new Float32Array(length)};}createBufferSource(){return{connect(){},disconnect(){},start(){setTimeout(()=>this.onended?.(),10);},stop(){this.onended?.();}};}};
   window.feed=(voice,n)=>{for(let i=0;i<n;i++)live.processor.onaudioprocess({inputBuffer:{getChannelData:()=>new Float32Array(320).fill(voice?.1:0)}});};
  });
  const waitJobs=async(count,finished=true)=>{let jobs=[];for(let i=0;i<150;i++){jobs=await page.evaluate(async()=> (await json('/images/jobs')).jobs);if(jobs.length===count&&(!finished||jobs.every(j=>j.state==='succeeded')))return jobs;await page.waitForTimeout(100);}throw new Error('Expected '+count+' image jobs: '+JSON.stringify(jobs.map(j=>({state:j.state,error:j.error}))));};
  const speak=async()=>{await page.waitForFunction(()=>live?.processor&&!live.processing&&!busy);await page.evaluate(()=>{feed(false,12);feed(true,20);feed(false,40);});};
  await page.goto(origin+'/shengjian/api/v2/console');await login('browser-test','browser-password-123');
  await page.waitForFunction(()=>document.querySelector('#image-edit-model').value==='fixture-edit');
  assert(await page.evaluate(async()=>{const x=await json('/models/capabilities');return ['chat','vision','image_generate','image_edit'].every(t=>x.data.some(m=>m.task===t));}));
  const png=Buffer.from(await page.evaluate(()=>{const c=document.createElement('canvas');c.width=180;c.height=180;c.getContext('2d').fillRect(0,0,180,180);return c.toDataURL('image/png').split(',')[1];}),'base64');
  await page.locator('[data-conversation-mode=image]').click();await page.locator('#image-reference-upload').setInputFiles({name:'reference.png',mimeType:'image/png',buffer:png});
  await page.waitForFunction(()=>ShengjianVisual.images().length===1);await page.locator('#image-reference-photo').waitFor({state:'visible'});
  const original=await page.evaluate(()=>ShengjianVisual.images()[0]);await fakeAudio();await page.locator('#image-start-live').click();await speak();
  await waitJobs(1);assert.equal(submissions[0].image_id,original);assert.equal(submissions[0].parent_job_id,null);
  const first=await page.evaluate(async()=> (await json('/images/jobs')).jobs[0]);
  voice='再亮一点';await speak();await waitJobs(2);assert.equal(submissions[1].parent_job_id,first.id);assert.equal(submissions[1].image_id,null);assert.equal(work.length,0,'image voice instructions do not become Work');
  await page.locator('#image-stop-live').click();await page.reload();await page.locator('#workspace').waitFor({state:'visible'});await page.locator('[data-conversation-mode=image]').click();await page.waitForFunction(()=>document.querySelector('#image-reference-label').textContent.includes('第2版'));
  assert(await page.evaluate(()=>ShengjianImages.intent('把背景换成电脑屏幕')==='edit'));assert(await page.evaluate(()=>ShengjianImages.intent('停一下，改成一句话')===null));assert(await page.evaluate(()=>ShengjianImages.intent('取消当前任务')===null));
  await page.locator('#image-prompt').fill('加上红色边框');await page.locator('#create-image').click();await waitJobs(3);assert(submissions[2].parent_job_id&&submissions[2].parent_job_id!==first.id,'reload keeps latest chain');
  await page.waitForFunction(()=>document.querySelectorAll('.generated-card').length===3);await page.locator('.generated-card').last().getByRole('button',{name:'继续修这版',exact:true}).click();await page.locator('#image-prompt').fill('换成白色背景');await page.locator('#create-image').click();await waitJobs(4);assert.equal(submissions[3].parent_job_id,first.id,'explicit branch preserves selected old version');
  
  await page.locator('#image-reference-camera').setInputFiles({name:'new-photo.png',mimeType:'image/png',buffer:png});await page.waitForFunction(()=>ShengjianVisual.images().length===1&&!document.querySelector('#image-reference-label').textContent.includes('第'));
  const newPhoto=await page.evaluate(()=>ShengjianVisual.images()[0]);assert.notEqual(newPhoto,original);await page.locator('#image-prompt').fill('去掉背景');await page.locator('#create-image').click();await waitJobs(5);assert.equal(submissions[4].image_id,newPhoto);assert.equal(submissions[4].parent_job_id,null,'new photo starts separate chain');
  await page.locator('#image-reference-clear').click();await page.locator('[data-conversation-mode=chat]').click();await page.locator('#prompt').fill('生成一张森林图片，不要文字');await page.locator('.send-button').click();await page.getByRole('button',{name:'查看图片与版本',exact:true}).waitFor();await waitJobs(6);assert.equal(submissions[5].image_id,null);assert.equal(submissions[5].parent_job_id,null,'negative content constraint still generates');
  await page.getByRole('button',{name:'查看图片与版本',exact:true}).last().click();
  for(const colorScheme of ['light','dark']){await page.emulateMedia({colorScheme});for(const width of [320,390]){await page.setViewportSize({width,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:path.join(out,`reference-edit-${colorScheme}-${width}.png`),fullPage:true});}}
  await page.locator('#logout').click();await login('browser-second','browser-password-456');await page.locator('[data-conversation-mode=image]').click();await page.getByText('第一张作品，从一句描述开始。',{exact:true}).waitFor();assert.equal(await page.locator('.generated-card').count(),0);assert(await page.locator('#image-reference-photo').isHidden());assert.equal(errors.length,0,errors.join('\n'));
  console.log(JSON.stringify({ok:true,checks:['capability-classification','upload-reference','ASR-to-edit','voice-followup-parent','no-Work-routing','reload-chain','branch-selected-version','capture-new-chain','generation-with-negative-constraint','safe-barge-in-phrases','320px-light-dark','account-isolation'],screenshots:out}));
 }finally{await browser?.close();server.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1;});
