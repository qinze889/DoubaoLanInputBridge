"use strict";
(()=>{
  const $=id=>document.getElementById(id),stateNames={queued:'等待生成',running:'正在生成',succeeded:'已完成',failed:'未完成',unknown:'结果待核实，未自动重试'};
  const errors={image_job_busy:'已有一张图片正在生成，请等完成后再提交。',image_model_not_available:'暂无可用的生图模型，请在模型与连接中选择。',insufficient_credits:'积分不足，未提交生图。',image_result_unknown:'上游未确认结果，未重复生成。',image_provider_rejected:'图片来源拒绝了请求，请检查需求或联系管理员。',image_connection_failed:'未能连接生图来源，本次预留积分已释放。'};
  let owner='',epoch=0,api=null,timer=null,loading=false,sending=false,mode='chat',urls=new Map(),downloads=new Set(),lastModel='';
  function note(message){$('image-status').textContent=message;}
  function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
  function clear(){for(const u of urls.values())URL.revokeObjectURL(u);urls.clear();for(const u of downloads)URL.revokeObjectURL(u);downloads.clear();$('image-gallery').replaceChildren();}
  function setMode(value){mode=value;if(value==='image')window.ShengjianVisual?.stopCamera();$('image-space').hidden=value!=='image';$('chat-space').hidden=value==='image';for(const b of document.querySelectorAll('[data-conversation-mode]')){const selected=b.dataset.conversationMode===value;b.classList.toggle('selected',selected);b.setAttribute('aria-pressed',String(selected));}if(owner&&value==='image')void refresh();}
  for(const b of document.querySelectorAll('[data-conversation-mode]'))b.onclick=()=>setMode(b.dataset.conversationMode);
  async function refresh(){
    if(!owner||!api||loading)return;const uid=owner,version=epoch,client=api;loading=true;
    try{
      const [settings,data]=await Promise.all([client.json('/images/settings'),client.json('/images/jobs')]);if(uid!==owner||version!==epoch)return;
      const select=$('image-model');if(document.activeElement!==select){select.replaceChildren(...settings.models.map(m=>new Option(m.name+' · 生图',m.id)));if(!settings.models.length)select.add(new Option('暂无已验证生图模型',''));if(settings.model&&!settings.models.some(m=>m.id===settings.model))select.add(new Option('原模型暂不可用，请重新选择',settings.model));select.value=settings.model;lastModel=settings.model;}
      select.disabled=!settings.models.length;$('image-cost').textContent=settings.models.length?`每张 ${settings.credits_per_image} 应用积分`:'生图来源尚未配置';
      $('create-image').disabled=sending||!settings.models.length||data.jobs.some(j=>['queued','running'].includes(j.state));
      const cards=[];
      for(const job of data.jobs){
        const card=node('article',undefined,'generated-card');card.dataset.job=job.id;
        card.append(node('small',(job.model.replace('workbuddy/cn:','').replace('minimax/',''))+' · '+(stateNames[job.state]||job.state)),node('p',job.prompt));
        if(job.state==='succeeded'){
          let url=urls.get(job.id);
          if(!url){const response=await (client.preview?client.preview(job.image_id):client.file(job.id)),blob=await response.blob();if(uid!==owner||version!==epoch)return;url=URL.createObjectURL(blob);urls.set(job.id,url);}
          const picture=node('img');picture.src=url;picture.alt='AI 生成：'+job.prompt;picture.loading='lazy';card.append(picture);
          const actions=node('div',undefined,'actions'),download=node('a','保存 PNG');download.href='#';download.onclick=async e=>{e.preventDefault();if(uid!==owner||version!==epoch)return;try{const response=await client.file(job.id),blob=await response.blob();if(uid!==owner||version!==epoch)return;const original=URL.createObjectURL(blob);downloads.add(original);const link=node('a');link.href=original;link.download='声笺-'+job.id+'.png';document.body.append(link);link.click();link.remove();setTimeout(()=>{URL.revokeObjectURL(original);downloads.delete(original);},60000);}catch(e){if(uid===owner&&version===epoch)note('原图下载未完成，可以稍后重试下载，不会重新生成图片。');}};actions.append(download);
          const chat=node('button','聊这张图');chat.type='button';chat.onclick=async()=>{try{if(uid!==owner||version!==epoch)return;setMode('chat');await window.ShengjianVisual.useSaved(job.image_id,job.entry_id);}catch(e){note(e.message);}};actions.append(chat);card.append(actions,node('small',`${job.width} × ${job.height} · AI 生成作品`));
        }else if(job.error)card.append(node('p',errors[job.error]||'生成未完成，未自动重复提交。'));
        cards.push(card);
      }
      if(!cards.length)cards.push(node('p','第一张作品，从一句描述开始。','muted'));
      $('image-gallery').replaceChildren(...cards);
      const liveIds=new Set(data.jobs.filter(j=>j.state==='succeeded').map(j=>j.id));for(const [id,url] of urls)if(!liveIds.has(id)){URL.revokeObjectURL(url);urls.delete(id);}
    }catch(e){if(uid===owner&&version===epoch)note(errors[e.message]||'生图记录暂未载入，请稍后重试。');}
    finally{if(uid===owner&&version===epoch)loading=false;}
  }
  $('image-model').onchange=async()=>{const uid=owner,version=epoch,client=api,select=$('image-model');select.disabled=true;try{const data=await client.json('/images/settings',{model:select.value},'PATCH');if(uid!==owner||version!==epoch)return;lastModel=data.model;$('model-note').textContent='生图模型已保存，下一次生成使用；聊天与识图模型保持各自选择。';}catch(e){if(uid===owner&&version===epoch){select.value=lastModel;note(errors[e.message]||e.message);}}finally{if(uid===owner&&version===epoch)select.disabled=false;}};
  async function generate(prompt){
    if(!owner||!api)throw new Error('请先登录');if(sending)throw new Error('正在提交生图，请稍等。');if(prompt.length>1500)throw new Error('生图描述请控制在 1500 字内。');
    const uid=owner,version=epoch,client=api;sending=true;$('create-image').disabled=true;note('正在提交，提交成功后会在云端继续生成…');
    const storageKey='shengjian.image-request.'+uid;let pending;try{pending=JSON.parse(sessionStorage.getItem(storageKey)||'null');}catch{}if(!pending||pending.prompt!==prompt){pending={prompt,request_id:crypto.randomUUID()};sessionStorage.setItem(storageKey,JSON.stringify(pending));}
    try{const result=await client.json('/images/jobs',pending);if(uid!==owner||version!==epoch)return;sessionStorage.removeItem(storageKey);note('已提交后台生成，离开页面也会继续。');void refresh();return result.job;}
    catch(e){if(uid===owner&&version===epoch)note(errors[e.message]||'提交未获确认。请查看生成记录，不要立即重复提交。');throw e;}
    finally{if(uid===owner&&version===epoch){sending=false;$('create-image').disabled=false;}}
  }
  $('image-stop-live').onclick=()=>$('realtime').click();
  new MutationObserver(()=>{$('image-live-banner').hidden=$('realtime').getAttribute('aria-pressed')!=='true';}).observe($('realtime'),{attributes:true,attributeFilter:['aria-pressed']});
  $('image-form').onsubmit=async e=>{e.preventDefault();try{await generate($('image-prompt').value.trim());}catch{}};
  window.ShengjianImages={
    activate(uid,client){api=client;if(owner===uid)return;owner=uid;epoch++;loading=false;sending=false;void refresh();clearInterval(timer);timer=setInterval(()=>{if(mode==='image'&&!document.hidden)void refresh();},2500);},
    deactivate(){if(owner)sessionStorage.removeItem('shengjian.image-request.'+owner);owner='';api=null;epoch++;loading=false;sending=false;clearInterval(timer);clear();$('image-prompt').value='';$('image-model').replaceChildren(new Option('正在加载生图模型…',''));$('image-model').disabled=true;lastModel='';note('');setMode('chat');},
    generate,open(){setMode('image');},
    isGeneration(prompt){return !/代码|脚本|取消|进度|停止|不要|别生成/.test(prompt)&&/^(?:请你|请|帮我|给我|麻烦)?\s*(?:(?:生成|绘制|制作).{0,15}(?:图片|图像|海报|插画|封面)|画(?:一|个|只|张))/.test(prompt);}
  };
})();
