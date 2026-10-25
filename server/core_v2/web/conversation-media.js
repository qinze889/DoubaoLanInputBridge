/* Media belongs to its conversation; image jobs never navigate or own Chat. */
(()=>{
 const $=id=>document.getElementById(id),cards=new Map();
 let scope='',epoch=0,inFlight=false,timer;
 const terminal=new Set(['succeeded','failed','unknown','cancelled']);
 function current(){const cid=window.ShengjianProduct?.conversationFor();return token&&cid?{cid,owner:token,key:chatOwner+':'+cid}:null;}
 function clear(){epoch++;for(const card of cards.values()){if(card.url)URL.revokeObjectURL(card.url);card.node.remove();}cards.clear();scope='';}
 function position(card,job){
  const anchor=[...$('messages').querySelectorAll('[data-chat-task]')].find(node=>node.dataset.chatTask===job.task_id);
  if(anchor){let after=anchor;while(after.nextElementSibling){const next=after.nextElementSibling;if(next===card.node)return;if(next.dataset.mediaTask===job.task_id||next.classList.contains('message-actions'))after=next;else break;}after.after(card.node);}
  else if(!card.node.isConnected)$('messages').append(card.node);
 }
 function create(job){
  const node=document.createElement('article');node.className='message assistant inline-media-card';node.dataset.imageJob=job.id;node.dataset.mediaTask=job.task_id;
  const status=document.createElement('p');status.className='inline-media-status';status.setAttribute('role','status');status.setAttribute('aria-atomic','true');
  const frame=document.createElement('div');frame.className='inline-media-frame';
  const detail=document.createElement('details'),label=document.createElement('summary'),prompt=document.createElement('p');label.textContent='创作说明';prompt.textContent=job.prompt;detail.append(label,prompt);
  const actions=document.createElement('div');actions.className='inline-media-actions';
  node.append(status,frame,actions,detail);const card={node,status,frame,actions,loading:false};cards.set(job.id,card);position(card,job);return card;
 }
 async function update(job,context,generation){
  let card=cards.get(job.id);if(!card)card=create(job);else position(card,job);
  const text=({queued:'图片已排队，可以继续聊',running:'图片正在生成，可以继续聊',succeeded:job.operation==='edit'?'这版调整好了':'图片已生成',failed:'这次图片未完成',unknown:'图片结果尚未确认，请先查看进度'})[job.state]||'正在核对图片';
  if(card.status.textContent!==text)card.status.textContent=text;
  card.node.dataset.state=job.state;
  if(job.state!=='succeeded'||card.url||card.loading)return;
  card.loading=true;
  try{
   const response=await api('/images/jobs/'+job.id+'/file');const blob=await response.blob();
   if(generation!==epoch||context.owner!==token||context.key!==scope)return;
   card.url=URL.createObjectURL(blob);
   const image=document.createElement('img');image.alt='AI 生成的图片';image.loading='lazy';image.decoding='async';image.src=card.url;image.width=job.width||1024;image.height=job.height||1024;
   const download=document.createElement('a');download.href=card.url;download.download='声笺图片-'+job.id.slice(0,6)+'.png';download.textContent='保存图片';
   const edit=document.createElement('button');edit.type='button';edit.textContent='继续调整';edit.onclick=async()=>{
    try{
     if(generation!==epoch||context.owner!==token||context.key!==scope)return;
     if(!await window.ShengjianVisual.useSaved(job.image_id,job.entry_id,{open:false,origin:'conversation-edit'}))return;
     if(generation!==epoch||context.owner!==token||context.key!==scope)return;
     $('prompt').value='继续调整这张图片：';$('prompt').dispatchEvent(new Event('input'));$('prompt').focus();
    }catch{notice('这张图片暂未选中，请稍后再试。');}
   };
   card.frame.replaceChildren(image);card.actions.replaceChildren(download,edit);
  }catch{if(generation===epoch)card.status.textContent='图片已生成，预览暂未加载，稍后自动恢复';}
  finally{card.loading=false;}
 }
 async function poll(){
  if(inFlight)return;
  const context=current();if(!context){if(scope)clear();return;}
  if(context.key!==scope){clear();scope=context.key;}
  const generation=epoch;inFlight=true;
  try{
   const data=await json('/assistant/conversations/'+context.cid+'/images');
   if(generation!==epoch||context.owner!==token||context.key!==scope)return;
   for(const job of data.jobs)await update(job,context,generation);
  }catch{}finally{inFlight=false;}
 }
 window.ShengjianConversationMedia={poll,clear};
 window.addEventListener('pagehide',()=>{clearInterval(timer);clear();});
 window.addEventListener('pageshow',()=>{clearInterval(timer);timer=setInterval(poll,1800);void poll();});
 new MutationObserver(()=>void poll()).observe($('messages'),{childList:true});
 timer=setInterval(poll,1800);void poll();
})();
