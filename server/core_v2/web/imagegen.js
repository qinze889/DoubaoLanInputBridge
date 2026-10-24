"use strict";
(()=>{
  const $=id=>document.getElementById(id),stateNames={queued:'等待生成',running:'正在生成',succeeded:'已完成',failed:'未完成',unknown:'结果待核实，未自动重试'};
  const errors={image_job_busy:'已有一张图片正在生成，请等完成后再提交。',image_model_not_available:'暂无可用的生图模型，请在模型与连接中选择。',insufficient_credits:'积分不足，未提交生图。',image_result_unknown:'上游未确认结果，未重复生成。',image_provider_rejected:'图片来源拒绝了请求，请检查需求或联系管理员。',image_connection_failed:'未能连接图片来源，本次预留积分已释放。',image_parent_not_completed:'上一版未完成，未重新生成。请在版本记录中选择一个已完成的版本继续。',image_reference_unavailable:'参考图暂不可用，请重新上传或选择已有版本。',image_reference_too_large:'参考图片过大，请换一张较小的图片。'};
  let owner='',epoch=0,api=null,timer=null,loading=false,sending=false,mode='chat',urls=new Map(),downloads=new Set(),lastModel='',editState={head:null,anchor:null},jobsById=new Map(),hasPending=false,referenceUrl='',referenceKey='',syncing='';
  function saveEdit(){if(owner)localStorage.setItem('shengjian.image-edit.'+owner,JSON.stringify(editState));}
  function note(message){$('image-status').textContent=message;}
  function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
  function clear(){if(referenceUrl)URL.revokeObjectURL(referenceUrl);referenceUrl='';referenceKey='';$('image-reference-photo').hidden=true;for(const u of urls.values())URL.revokeObjectURL(u);urls.clear();for(const u of downloads)URL.revokeObjectURL(u);downloads.clear();$('image-gallery').replaceChildren();}
  function setMode(value){mode=value;if(value==='image')window.ShengjianVisual?.stopCamera();$('image-space').hidden=value!=='image';$('chat-space').hidden=value==='image';for(const b of document.querySelectorAll('[data-conversation-mode]')){if(b.closest('.app-nav'))continue;const selected=b.dataset.conversationMode===value;b.classList.toggle('selected',selected);b.setAttribute('aria-pressed',String(selected));}if(owner&&value==='image')void refresh();}
  for(const b of document.querySelectorAll('[data-conversation-mode]'))b.onclick=()=>setMode(b.dataset.conversationMode);
  async function refresh(){
    if(!owner||!api||loading)return;const uid=owner,version=epoch,client=api;loading=true;
    try{
      const [settings,data]=await Promise.all([client.json('/images/settings'),client.json('/images/jobs')]);if(uid!==owner||version!==epoch)return;
      for(const job of data.jobs){const previous=jobsById.get(job.id);if(previous&&['queued','running'].includes(previous.state)&&job.state==='succeeded'){note('图片已完成，可以保存或继续修改。');window.ShengjianProduct?.artReady(job);}}
      jobsById=new Map(data.jobs.map(j=>[j.id,j]));hasPending=data.jobs.some(j=>['queued','running'].includes(j.state));
      const editSelect=$('image-edit-model');if(document.activeElement!==editSelect){editSelect.replaceChildren(...(settings.edit_models||[]).map(m=>new Option(m.name+' · 改图',m.id)));if(!settings.edit_models?.length)editSelect.add(new Option('暂无已验证改图模型',''));editSelect.value=settings.edit_model||'';}editSelect.disabled=!settings.edit_models?.length;
      const select=$('image-model');if(document.activeElement!==select){select.replaceChildren(...settings.models.map(m=>new Option(m.name+' · 生图',m.id)));if(!settings.models.length)select.add(new Option('暂无已验证生图模型',''));if(settings.model&&!settings.models.some(m=>m.id===settings.model))select.add(new Option('原模型暂不可用，请重新选择',settings.model));select.value=settings.model;lastModel=settings.model;}
      select.disabled=!settings.models.length;$('image-cost').textContent=settings.unlimited?'本账号不限应用积分':settings.models.length?`每张 ${settings.credits_per_image} 应用积分`:'生图来源尚未配置';
      $('create-image').disabled=sending||(!(editState.head||window.ShengjianVisual?.hasContext())&&!settings.models.length);
      await reference();
      const cards=[];
      for(const job of data.jobs){
        const card=node('article',undefined,'generated-card');card.dataset.job=job.id;
        card.append(node('small',(job.operation==='edit'?'改图 · ':'生图 · ')+('第'+(job.version||1)+'版 · ')+(job.model.replace('workbuddy/cn:','').replace('minimax/',''))+' · '+(stateNames[job.state]||job.state)),node('p',job.prompt));
        if(job.state==='succeeded'){
          let url=urls.get(job.id);
          if(!url){let response;try{response=await(client.preview?client.preview(job.image_id):client.file(job.id));}catch{response=await client.file(job.id);}const blob=await response.blob();if(uid!==owner||version!==epoch)return;url=URL.createObjectURL(blob);urls.set(job.id,url);}
          const picture=node('img');picture.src=url;picture.alt='AI 生成：'+job.prompt;picture.loading='lazy';card.append(picture);
          const actions=node('div',undefined,'actions'),download=node('a','保存 PNG');download.href='#';download.onclick=async e=>{e.preventDefault();if(uid!==owner||version!==epoch)return;try{const response=await client.file(job.id),blob=await response.blob();if(uid!==owner||version!==epoch)return;const original=URL.createObjectURL(blob);downloads.add(original);const link=node('a');link.href=original;link.download='声笺-'+job.id+'.png';document.body.append(link);link.click();link.remove();setTimeout(()=>{URL.revokeObjectURL(original);downloads.delete(original);},60000);}catch(e){if(uid===owner&&version===epoch)note('原图下载未完成，可以稍后重试下载，不会重新生成图片。');}};actions.append(download);
          const chat=node('button','聊这张图');chat.type='button';chat.onclick=async()=>{try{if(uid!==owner||version!==epoch)return;setMode('chat');await window.ShengjianVisual.useSaved(job.image_id,job.entry_id);}catch(e){note(e.message);}};actions.append(chat);const edit=node('button','继续修这版');edit.type='button';edit.onclick=async()=>{try{if(uid!==owner||version!==epoch)return;editState={head:job.id,anchor:job.image_id};saveEdit();await window.ShengjianVisual.useSaved(job.image_id,job.entry_id,{open:false,origin:'image-edit'});setMode('image');window.ShengjianProduct?.selectArtMode('edit');await reference();note('已选定这一版。直接说出要调整的地方。');}catch(e){note(e.message);}};actions.append(edit);card.append(actions,node('small',`${job.width} × ${job.height} · AI 生成作品`));
        }else if(job.error){card.append(node('p',errors[job.error]||'生成未完成，未自动重复提交。'));if(job.diagnostic?.stage){const detail=node('details');detail.append(node('summary','问题详情'),node('small',job.diagnostic.stage+' · '+job.error));card.append(detail);}}
        cards.push(card);
      }
      if(!cards.length)cards.push(node('p','第一张作品，从一句描述开始。','muted'));
      $('image-gallery').replaceChildren(...cards);
      await syncReadyReference();
      const liveIds=new Set(data.jobs.filter(j=>j.state==='succeeded').map(j=>j.id));for(const [id,url] of urls)if(!liveIds.has(id)){URL.revokeObjectURL(url);urls.delete(id);}
    }catch(e){if(uid===owner&&version===epoch)note(errors[e.message]||'生图记录暂未载入，请稍后重试。');}
    finally{if(uid===owner&&version===epoch)loading=false;}
  }
  function report(stage,error){if(!owner||!api)return;const code=/^[a-z][a-z0-9_]{2,80}$/.test(error.message||'')?error.message:error.name==='TypeError'?'client_network':'client_failure';void api.json('/images/client-events',{stage,code}).catch(()=>{});}
  async function reference(){
    if(!owner||!api)return;const uid=owner,version=epoch;
    const head=editState.head?jobsById.get(editState.head):null;
    let imageId=window.ShengjianVisual?.images()[0];
    $('image-reference-label').textContent=head?'调整目标：第'+(head.version||1)+'版 · '+(stateNames[head.state]||head.state):window.ShengjianVisual?.hasContext()?'参考图已选择':'先上传参考图，或直接描述新图片';
    $('image-reference-status').textContent=head&&['queued','running'].includes(head.state)?'这一版仍在处理。继续说出调整，会等待这一版完成后再修改。':'上传／拍照后说“背景改成白色”，再说“亮一点”即可继续调整。';
    $('create-image').textContent=window.ShengjianProduct?(window.ShengjianProduct.artMode()==='edit'?'提交修改':'生成图片'):(editState.head||window.ShengjianVisual?.hasContext())?'提交调整':'生成图片';
    if(imageId && imageId!==referenceKey){const response=await api.preview(imageId),blob=await response.blob();if(uid!==owner||version!==epoch||imageId!==window.ShengjianVisual?.images()[0])return;if(referenceUrl)URL.revokeObjectURL(referenceUrl);referenceUrl=URL.createObjectURL(blob);referenceKey=imageId;$('image-reference-photo').src=referenceUrl;$('image-reference-photo').hidden=false;}
    if(!imageId){if(referenceUrl)URL.revokeObjectURL(referenceUrl);referenceUrl='';referenceKey='';$('image-reference-photo').hidden=true;}
  }
  async function syncReadyReference(){
    if(mode!=='image'||!editState.head||!owner||!api)return;const uid=owner,version=epoch,headId=editState.head;let job=jobsById.get(headId),seen=new Set();
    while(job&&job.state!=='succeeded'&&job.parent_job_id&&!seen.has(job.id)){seen.add(job.id);job=jobsById.get(job.parent_job_id);}
    if(!job||job.state!=='succeeded'||syncing===job.id||(editState.anchor===job.image_id&&window.ShengjianVisual?.images()[0]===job.image_id))return;
    syncing=job.id;
    try{const ready=await window.ShengjianVisual.useSaved(job.image_id,job.entry_id,{open:false,origin:'image-edit'});if(ready&&uid===owner&&version===epoch&&headId===editState.head){editState.anchor=job.image_id;saveEdit();await reference();}}
    finally{if(uid===owner&&version===epoch)syncing='';}
  }
  window.addEventListener('shengjian:visual-change',event=>{if(event.detail?.origin==='image-edit')return;editState={head:null,anchor:null};saveEdit();void reference().catch(()=>{});});
  window.addEventListener('shengjian:visual-ready',()=>{void reference().catch(()=>{});});
  for(const id of ['image-reference-upload','image-reference-camera'])$(id).onchange=async e=>{try{await window.ShengjianVisual.attach([...e.target.files],{open:false});setMode('image');window.ShengjianProduct?.showCreation();window.ShengjianProduct?.selectArtMode('edit');await reference();}catch(error){report('reference_prepare',error);note('参考图未保存：'+error.message);}finally{e.target.value='';}};
  $('image-reference-clear').onclick=()=>{editState={head:null,anchor:null};saveEdit();$('visual-clear').click();void reference();window.ShengjianProduct?.selectArtMode('generate');note('已开始新的创作，旧版本保留在下方。');};
  $('image-edit-model').onchange=async()=>{const uid=owner,version=epoch,select=$('image-edit-model');select.disabled=true;try{await api.json('/images/settings',{edit_model:select.value},'PATCH');if(uid===owner&&version===epoch)$('model-note').textContent='改图模型已保存，下一次调整使用此模型。';}catch(error){report('model_select',error);note(errors[error.message]||error.message);}finally{if(uid===owner&&version===epoch){select.disabled=false;void refresh();}}};
  $('image-model').onchange=async()=>{const uid=owner,version=epoch,client=api,select=$('image-model');select.disabled=true;try{const data=await client.json('/images/settings',{model:select.value},'PATCH');if(uid!==owner||version!==epoch)return;lastModel=data.model;$('model-note').textContent='生图模型已保存，下一次生成使用；聊天与识图模型保持各自选择。';}catch(e){if(uid===owner&&version===epoch){select.value=lastModel;note(errors[e.message]||e.message);}}finally{if(uid===owner&&version===epoch)select.disabled=false;}};
  async function generate(prompt,options={}){
    if(!owner||!api)throw new Error('请先登录');if(sending)throw new Error('正在提交图片，请稍等。');if(prompt.length>1500)throw new Error('生图描述请控制在 1500 字内。');
    const uid=owner,version=epoch,client=api;let imageId=null,parentId=null;const edit=options.edit===true;
    sending=true;$('create-image').disabled=true;
    try{if(edit){if(editState.head)parentId=editState.head;else{const visual=await window.ShengjianVisual.snapshot(prompt);if(!visual.images.length)throw new Error('请先上传或拍摄参考图，再说出修改需求。');imageId=visual.images[0];window.ShengjianVisual.stopCamera();}}}catch(error){sending=false;$('create-image').disabled=false;report('reference_prepare',error);throw error;}
    if(uid!==owner||version!==epoch)return;
    sending=true;$('create-image').disabled=true;note('正在提交，提交成功后会在云端继续生成…');
    const storageKey='shengjian.image-request.'+uid;let pending;try{pending=JSON.parse(sessionStorage.getItem(storageKey)||'null');}catch{}if(!pending||pending.prompt!==prompt||pending.image_id!==imageId||pending.parent_job_id!==parentId){pending={prompt,request_id:crypto.randomUUID(),image_id:imageId,parent_job_id:parentId};sessionStorage.setItem(storageKey,JSON.stringify(pending));}
    try{const result=await client.json('/images/jobs',pending);if(uid!==owner||version!==epoch)return;sessionStorage.removeItem(storageKey);editState={head:result.job.id,anchor:imageId||editState.anchor};saveEdit();note(edit?'调整已排队，会接着选定版本继续修改。':'已提交后台生成，离开页面也会继续。');void refresh();return result.job;}
    catch(e){if(uid===owner&&version===epoch){report(edit?'edit_submit':'generate_submit',e);note(errors[e.message]||e.message||'提交未获确认，请查看记录。');}throw e;}
    finally{if(uid===owner&&version===epoch){sending=false;$('create-image').disabled=false;}}
  }
  $('image-start-live').onclick=()=>$('realtime').click();
  $('image-stop-live').onclick=()=>$('realtime').click();
  new MutationObserver(()=>{$('image-live-banner').hidden=$('realtime').getAttribute('aria-pressed')!=='true';$('image-start-live').hidden=!$('image-live-banner').hidden;}).observe($('realtime'),{attributes:true,attributeFilter:['aria-pressed']});
  $('image-form').onsubmit=async e=>{e.preventDefault();try{await generate($('image-prompt').value.trim(),{edit:window.ShengjianProduct?window.ShengjianProduct.artMode()==='edit':!!(editState.head||window.ShengjianVisual?.hasContext())});$('image-prompt').value='';}catch{}};
  window.ShengjianImages={
    activate(uid,client){api=client;if(owner===uid)return;owner=uid;epoch++;loading=false;sending=false;try{editState=JSON.parse(localStorage.getItem('shengjian.image-edit.'+uid)||'null')||{head:null,anchor:null};}catch{editState={head:null,anchor:null};}void refresh();clearInterval(timer);timer=setInterval(()=>{if((mode==='image'||editState.head||hasPending)&&!document.hidden)void refresh();},2500);},
    deactivate(){if(owner){sessionStorage.removeItem('shengjian.image-request.'+owner);localStorage.removeItem('shengjian.image-edit.'+owner);}owner='';api=null;epoch++;loading=false;sending=false;clearInterval(timer);clear();$('image-prompt').value='';$('image-model').replaceChildren(new Option('正在加载生图模型…',''));$('image-model').disabled=true;lastModel='';editState={head:null,anchor:null};jobsById.clear();hasPending=false;syncing='';$('image-edit-model').replaceChildren(new Option('正在加载改图模型…',''));$('image-edit-model').disabled=true;note('');setMode('chat');},
    generate,async progress(){if(!editState.head)return null;const result=await api.json('/images/jobs/'+editState.head);return result.job;},chat(){setMode('chat');},open(){setMode('image');window.ShengjianProduct?.showCreation();},
    isGeneration(prompt){return !/代码|脚本|取消|进度|停止/.test(prompt)&&!/^(?:请|帮我|给我)?(?:不要|别)(?:生成|画)/.test(prompt)&&/^(?:请你|请|帮我|给我|麻烦)?\s*(?:(?:生成|绘制|制作).{0,15}(?:图片|图像|海报|插画|封面)|画(?:一|个|只|张))/.test(prompt);},
    intent(prompt){
      if(/代码|脚本|任务|打开|文件|文档|停止|取消|进度/.test(prompt)||/^(?:请|帮我)?(?:先别改|不要修改|别改了)/.test(prompt))return null;
      if(/一句话|简短|语速|播报|回答|文字回复|语音回复/.test(prompt)&&!/图片|照片|海报|图里|字样/.test(prompt))return null;
      const reference=!!(editState.head||window.ShengjianVisual?.hasContext());
      const modification=/改图|修图|编辑.{0,8}(?:图片|照片)|(?:改成|改为|换成|换为|调亮|调暗|去掉|移除|擦掉|加上|添加|替换|调整|变成)/.test(prompt)||/(?:更|再|稍微|一点|一些|点).*(?:亮|暗|暖|冷|饱和|对比|色温|清晰|模糊)|(?:亮|暗|暖|冷|饱和|对比|色温|清晰|模糊).*(?:一点|一些|点)/.test(prompt)||/(?:参考|根据|用这|以这).*(?:图|照片).*(?:生成|画|制作|做)/.test(prompt);
      if(modification&&(reference||/图|照片|背景|人物/.test(prompt)))return 'edit';
      return window.ShengjianImages.isGeneration(prompt)?'generate':null;
    }
  };
})();
