"use strict";
(()=>{
 const $=id=>document.getElementById(id),terminal=new Set(['succeeded','failed','cancelled','unknown']);
 let owner='',epoch=0,page='conversation',cid='',binding='',nextCursor=null,snapshot=null,historyMode='recent',workFilter='active',stick=true,loading=false,entered=false,silentClose=false,deviceSignature='',toastTimer=null,artMode='generate',releaseInfo={name:'声笺 Web',version:'2.0.0-preview.6',updated:'2026-10-24'};
 const acceptedTasks=new Map(),following=new Map(),objectUrls=new Set(),deviceExpanded=new Set();let pendingConfirmation=null;let historyRows=[],historyCursor=null,historyLoading=false,taskResult='',taskResultNode=null,taskLogs=null,taskReadButton=null;
 const titles={conversation:'对话',create:'创作',life:'记录',tasks:'工作',devices:'我的'};
 const friendlyStates={queued:'等待电脑',running:'进行中',awaiting_user:'等你确认',succeeded:'已完成',failed:'未完成',cancelled:'已取消',unknown:'需要核实'};
 function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
 function action(text,fn,cls=''){const b=node('button',text,cls);b.type='button';b.onclick=()=>Promise.resolve(fn()).catch(error);return b;}
 function key(name){return 'shengjian.product.'+name+'.'+owner;}
 function same(uid,version){return owner===uid&&epoch===version&&!!token;}
 function ago(stamp){const date=new Date(stamp*1000),today=new Date();if(date.toDateString()===today.toDateString())return date.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'});return date.toLocaleDateString('zh-CN',{month:'numeric',day:'numeric'});}
 function stateBadge(state){const n=node('span',friendlyStates[state]||state,'state-badge');n.dataset.state=state;return n;}
 function empty(title,description,buttonText,run){const n=node('div',undefined,'empty-state');n.append(node('h2',title),node('p',description));if(buttonText)n.append(action(buttonText,run,'subtle-button'));return n;}
 function routeUrl(state){const hash=new URLSearchParams({page:state.page});if(state.page==='conversation'&&state.cid)hash.set('conversation',state.cid);if(state.task)hash.set('task',state.task);if(state.modal)hash.set('sheet',state.modal);return location.pathname+location.search+'#'+hash;}
 function route(replace=false,extra={}){if(!entered)return;const value={page,cid,...extra};const method=replace?'replaceState':'pushState';const url=routeUrl(value);if(location.pathname+location.search+location.hash===url)return;history[method](value,'',url);}
 function closeDialogs(){for(const d of document.querySelectorAll('dialog[open]')){d.dataset.silentClose='1';d.close();}}
 function openDialog(id,record=true){const d=$(id);if(!d||d.open)return;closeDialogs();d.showModal();if(record)route(false,{modal:id});}
 function closeDialog(id){$(id)?.close();}
 for(const d of document.querySelectorAll('dialog')){
  d.querySelectorAll('[data-close-dialog]').forEach(b=>b.onclick=()=>d.close());
  d.addEventListener('close',()=>{const silent=d.dataset.silentClose==='1';delete d.dataset.silentClose;if(!silent&&history.state?.modal===d.id)history.back();if(d.id==='confirm-dialog'&&pendingConfirmation){const pending=pendingConfirmation;pendingConfirmation=null;pending.resolve(pending.accepted&&same(pending.uid,pending.version));}});
  d.addEventListener('click',e=>{if(e.target!==d)return;const r=d.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)d.close();});
 }
 function modelScope(section){for(const b of document.querySelectorAll('[data-model-scope]'))b.classList.toggle('selected',b.dataset.modelScope===section);for(const panel of document.querySelectorAll('[data-model-panel]'))panel.hidden=panel.dataset.modelPanel!==section;$('models-dialog').querySelector('details.advanced').hidden=section==='image';}function openModels(section='chat'){modelScope(section);openDialog('models-dialog');$('model-settings').open=true;if(section==='image')$('image-model').focus();else $('chat-model').focus();}for(const b of document.querySelectorAll('[data-model-scope]'))b.onclick=()=>modelScope(b.dataset.modelScope);
 $('model-open').onclick=()=>openModels();
 for(const b of document.querySelectorAll('[data-open-models]'))b.onclick=()=>openModels(b.dataset.openModels);
 for(const b of document.querySelectorAll('[data-dialog]'))b.onclick=()=>openDialog(b.dataset.dialog);
 function selectArtMode(value){artMode=value==='edit'?'edit':'generate';if(owner)localStorage.setItem(key('art-mode'),artMode);for(const b of document.querySelectorAll('[data-art-mode]'))b.classList.toggle('selected',b.dataset.artMode===artMode);$('image-reference').hidden=artMode!=='edit';$('image-prompt').placeholder=artMode==='edit'?'想调整哪里？例如：把背景改成海边。':'描述你想要的画面，越具体越接近你的想法…';$('create-image').textContent=artMode==='edit'?'提交修改':'生成图片';}
 for(const b of document.querySelectorAll('[data-art-mode]'))b.onclick=()=>selectArtMode(b.dataset.artMode);
 selectArtMode('generate');
 $('copy-version').onclick=()=>copyText(releaseInfo.name+' '+releaseInfo.version+' ('+releaseInfo.updated+')');void fetch(base+'/console/product-version.json',{cache:'no-cache'}).then(r=>r.ok?r.json():null).then(info=>{if(info?.version){releaseInfo=info;$('about-version').textContent='版本 '+info.version;}}).catch(()=>{});
 document.querySelector('.brand').addEventListener('click',e=>{if(token&&!e.metaKey&&!e.ctrlKey&&!e.shiftKey&&!e.altKey){e.preventDefault();showPage('conversation');}});
 $('profile-open').onclick=()=>showPage('devices');$('computer-status').onclick=()=>{showPage('devices');$('device-list').scrollIntoView({block:'start'});};
 $('attachments-open').onclick=()=>openDialog('attachments-dialog');
 for(const id of ['visual-upload','visual-take-photo'])$(id).addEventListener('change',()=>closeDialog('attachments-dialog'));
 $('visual-camera-toggle').addEventListener('click',()=>closeDialog('attachments-dialog'));
 $('record').addEventListener('click',()=>closeDialog('attachments-dialog'));
 $('suggest-photo').onclick=()=>openDialog('attachments-dialog');$('suggest-create').onclick=()=>showPage('create');
 $('show-devices').onclick=()=>{closeDialogs();showPage('devices');};
 $('new-work').onclick=()=>{showPage('conversation');$('prompt').value='请帮我在电脑上';$('prompt').focus();resizeInput();};
 $('task-back').onclick=()=>{ $('tasks').classList.remove('task-open');route(false); };
 $('voice-return').onclick=()=>showPage('conversation');$('voice-end').onclick=()=>stopLive();
 function authMode(register){const form=$('login-form'),submit=form.querySelector('[type=submit],.auth-submit');submit.value=register?'register':'login';submit.textContent=register?'注册并登录':'登录';$('auth-title').textContent=register?'创建你的声笺账号':'欢迎回来';$('invite-field').hidden=!register;form.elements.invite.required=register;form.elements.password.autocomplete=register?'new-password':'current-password';$('auth-switch').textContent=register?'已有账号，去登录':'使用邀请码注册';}
 $('auth-switch').onclick=()=>authMode($('login-form').querySelector('.auth-submit').value!=='register');
 $('show-password').onclick=()=>{const field=$('login-form').elements.password,show=field.type==='password';field.type=show?'text':'password';$('show-password').textContent=show?'隐藏':'显示';$('show-password').setAttribute('aria-label',show?'隐藏密码':'显示密码');};
 function confirmAction(title,description,accept='确认'){
  if(pendingConfirmation){pendingConfirmation.resolve(false);pendingConfirmation=null;}
  $('confirm-title').textContent=title;$('confirm-description').textContent=description;$('confirm-yes').textContent=accept;
  return new Promise(resolve=>{pendingConfirmation={resolve,accepted:false,uid:owner,version:epoch};openDialog('confirm-dialog');});
 }
 $('confirm-no').onclick=()=>closeDialog('confirm-dialog');$('confirm-yes').onclick=()=>{if(pendingConfirmation)pendingConfirmation.accepted=true;closeDialog('confirm-dialog');};
 function viewport(){const vv=window.visualViewport;if(vv&&Math.abs(vv.scale-1)<.05)document.documentElement.style.setProperty('--app-height',vv.height+'px');else document.documentElement.style.removeProperty('--app-height');document.body.classList.toggle('keyboard-open',!!vv&&document.activeElement===$('prompt')&&window.innerHeight-vv.height>120);}
 window.visualViewport?.addEventListener('resize',viewport);window.addEventListener('resize',viewport);document.addEventListener('focusin',viewport);document.addEventListener('focusout',viewport);viewport();
 function resizeInput(){const input=$('prompt');input.style.height='auto';input.style.height=Math.min(130,input.scrollHeight)+'px';$('compose').querySelector('[type=submit]').disabled=loading||busy||!input.value.trim();}
 $('prompt').addEventListener('input',()=>{resizeInput();if(owner&&cid)sessionStorage.setItem(key('draft.'+cid),$('prompt').value);});
 $('compose').addEventListener('submit',()=>{stick=true;});
 $('prompt').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing&&e.keyCode!==229&&matchMedia('(pointer:fine)').matches){e.preventDefault();if(!busy&&!loading&&$('prompt').value.trim())$('compose').requestSubmit();}});
 for(const b of document.querySelectorAll('[data-prompt]'))b.addEventListener('click',resizeInput);
 let focusedReply=null,scrollFrame=0,touchY=null;
 function clearReplyFocus(forget=false){
  if(focusedReply){focusedReply.dataset.focusDismissed='1';focusedReply.classList.remove('answer-focus','answer-reveal');focusedReply.nextElementSibling?.classList.remove('answer-focus-actions');}
  $('messages').classList.remove('has-answer-focus');if(forget)focusedReply=null;
  $('latest-answer').hidden=!focusedReply?.isConnected;
 }
 function revealReply(bubble,force=false){
  if(!bubble?.isConnected||page!=='conversation'||(!force&&(!stick||bubble.dataset.focusDismissed)))return;
  if(focusedReply!==bubble)clearReplyFocus(true);focusedReply=bubble;delete bubble.dataset.focusDismissed;
  bubble.classList.add('answer-focus');$('messages').classList.add('has-answer-focus');
  if(!bubble.dataset.focusSeen){bubble.dataset.focusSeen='1';bubble.classList.add('answer-reveal');}
  if(bubble.nextElementSibling?.classList.contains('message-actions'))bubble.nextElementSibling.classList.add('answer-focus-actions');
  $('latest-answer').hidden=true;scrollConversation(force);
 }
 function browseHistory(){clearReplyFocus();stick=false;}
 $('latest-answer').onclick=()=>revealReply(focusedReply,true);
 const reading=$('conversation-scroll');
 reading.addEventListener('wheel',e=>{if(e.deltaY)browseHistory();},{passive:true});
 reading.addEventListener('touchstart',e=>{touchY=e.touches[0]?.clientY;},{passive:true});
 reading.addEventListener('touchmove',e=>{if(touchY!=null&&Math.abs((e.touches[0]?.clientY??touchY)-touchY)>10)browseHistory();},{passive:true});
 reading.addEventListener('keydown',e=>{if(['PageUp','PageDown','Home','End','ArrowUp','ArrowDown'].includes(e.key))browseHistory();});
 reading.addEventListener('pointerdown',e=>{if(e.pointerType==='mouse'&&e.clientX>=reading.getBoundingClientRect().right-16)browseHistory();});
 reading.addEventListener('scroll',()=>{if(!focusedReply?.classList.contains('answer-focus'))stick=reading.scrollHeight-reading.scrollTop-reading.clientHeight<100;});
 function scrollConversation(force=false){
  if(force)stick=true;if(!stick||scrollFrame)return;
  scrollFrame=requestAnimationFrame(()=>{scrollFrame=0;if(!stick)return;let top=reading.scrollHeight;
   if(focusedReply?.isConnected&&focusedReply.classList.contains('answer-focus')){
    const box=focusedReply.getBoundingClientRect(),offset=box.top-reading.getBoundingClientRect().top+reading.scrollTop;
    const space=Math.max(18,Math.min(reading.clientHeight*.38,(reading.clientHeight-box.height-48)/2));
    // Keep the first line readable even when status rows, a webview toolbar or
    // the keyboard leave little height. Long answers are read by scrolling.
    top=offset-space;
   }
   reading.scrollTop=Math.max(0,top);
  });
 }
 new ResizeObserver(()=>{reading.dataset.compact=String(reading.clientHeight<280);reading.style.setProperty('--answer-space',Math.round(reading.clientHeight*.5)+'px');scrollConversation();}).observe(reading);
 function messageCount(){const has=$('messages').childElementCount>0;$('welcome').hidden=has||loading;scrollConversation();}
 new MutationObserver(messageCount).observe($('messages'),{childList:true,subtree:true});
 new ResizeObserver(()=>document.documentElement.style.setProperty('--composer-height',document.querySelector('.composer-dock').getBoundingClientRect().height+'px')).observe(document.querySelector('.composer-dock'));
 function voiceFeedback(){document.querySelector('.composer-dock').dataset.voiceFeedback=String(!$('live-state').hidden&&!!$('live-state').textContent.trim());}
 new MutationObserver(voiceFeedback).observe($('live-state'),{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['hidden']});voiceFeedback();
 function mediaPreview(){const has=window.ShengjianVisual?.hasContext();document.querySelector('.visual-panel').hidden=!has;}
 new MutationObserver(mediaPreview).observe($('visual-clear'),{attributes:true,attributeFilter:['disabled']});
 window.addEventListener('shengjian:visual-change',mediaPreview);window.addEventListener('shengjian:visual-ready',mediaPreview);
 function inlineText(parent,text){
  const expression=/(\*\*([^*]+)\*\*|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\))/g;let end=0,match;
  while((match=expression.exec(text))){parent.append(document.createTextNode(text.slice(end,match.index)));if(match[2])parent.append(node('strong',match[2]));else{try{const url=new URL(match[4]);if(!['http:','https:'].includes(url.protocol))throw Error();const a=node('a',match[3]);a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';parent.append(a);}catch{parent.append(document.createTextNode(match[0]));}}end=expression.lastIndex;}
  parent.append(document.createTextNode(text.slice(end)));
 }
 function formatMessage(bubble,text){
  if(!/```|\*\*|\n[-*] |^#{1,3} |\[[^\]]+\]\(https?:/.test(text)){bubble.textContent=text;return;}
  bubble.replaceChildren();for(const [index,part] of text.split('```').entries()){
   if(index%2){const code=node('code',part.replace(/^[a-zA-Z0-9_-]+\n/,'')),pre=node('pre');pre.append(code);bubble.append(pre);continue;}
   let list=null;for(const line of part.split('\n')){if(/^[-*] /.test(line)){if(!list){list=node('ul');bubble.append(list);}const li=node('li');inlineText(li,line.slice(2));list.append(li);}else{list=null;if(!line.trim())continue;const paragraph=node(/^#{1,3} /.test(line)?'h3':'p');inlineText(paragraph,line.replace(/^#{1,3} /,''));bubble.append(paragraph);}}
  }
 }
 async function copyText(text){try{await navigator.clipboard.writeText(text);notice('已复制');}catch{notice('浏览器未允许复制，请长按文字复制。');}}
 async function readText(text){const context=new AudioContext();try{await context.resume();await speak(text,context);}finally{context.close().catch(()=>{});}}
 function messageAdded(bubble,role,text,images=[],{restored=false}={}){
  if(!bubble||!bubble.isConnected)return;
  if(role==='assistant'){bubble.dataset.copyText=text;formatMessage(bubble,text);if(!bubble.nextElementSibling?.classList.contains('message-actions')){const actions=node('div',undefined,'message-actions');actions.append(action('复制',()=>copyText(bubble.dataset.copyText||'')));bubble.after(actions);}}
  if(role==='user'&&images.length&&!bubble.dataset.photos){bubble.dataset.photos='1';const uid=owner,version=epoch;for(const id of images){const img=node('img');img.alt='对话中的照片';img.className='message-photo';bubble.append(img);api('/life/images/'+id).then(r=>r.blob()).then(blob=>{if(!same(uid,version)||!img.isConnected)return;const url=URL.createObjectURL(blob);objectUrls.add(url);img.src=url;}).catch(()=>{img.alt='原图已不可用';});}}
  if(!restored){if(role==='user'){clearReplyFocus(true);stick=true;}else if(role==='assistant')revealReply(bubble);}
  messageCount();
 }
 function closeFollowers(){for(const stop of following.values())stop();following.clear();}
 function saveDraft(){if(entered&&owner&&cid)sessionStorage.setItem(key('draft.'+cid),$('prompt').value);}
 function clearConversation(preserveVisual=false){
  clearReplyFocus(true);
  stopLive('已切换对话，电脑工作继续运行');stopCapture(false).catch(()=>{});interruptReply();closeFollowers();composeEpoch++;busy=false;currentTask='';$('compose').querySelector('[type=submit]').disabled=false;
  if(!preserveVisual)window.ShengjianVisual?.clear();messages=[];$('messages').replaceChildren();for(const url of objectUrls)URL.revokeObjectURL(url);objectUrls.clear();$('live-transcript').hidden=true;$('live-state').hidden=true;$('voice-latency').hidden=true;loading=false;historyLoading=false;for(const id of ['realtime','push-to-talk','attachments-open','image-start-live','image-push-to-talk'])$(id).disabled=false;nextCursor=null;$('history-more').hidden=true;$('conversation-status').textContent='';
 }
 function newConversation(selected=null){saveDraft();epoch++;clearConversation();cid=crypto.randomUUID().replaceAll('-','');binding='';localStorage.setItem(key('active'),cid);if(selected&&[...$('destination').options].some(o=>o.value===selected))$('destination').value=selected;$('prompt').value='';resizeInput();closeDialogs();showPage('conversation');messageCount();scrollConversation(true);updateConnection();}
 $('new-chat').onclick=()=>newConversation();
 $('destination').addEventListener('change',()=>{if(binding&&$('destination').value!=='chat'&&$('destination').value!==binding){newConversation($('destination').value);notice('已为这台电脑开启新对话，原对话仍在历史中。');}});
 function restoreTurn(turn,prepend=false){
  if(turn.task_id)acceptedTasks.set(turn.task_id,cid);
  const holder=document.createDocumentFragment(),userBubble=node('div',turn.user_text,'message user');holder.append(userBubble);
  const assistant=node('div',turn.assistant_text||(terminal.has(turn.state)?'本轮'+(friendlyStates[turn.state]||'已结束'):'正在回复…'),'message assistant');if(turn.task_id)assistant.dataset.chatTask=turn.task_id;holder.append(assistant);
  if(turn.is_work||['failed','unknown','awaiting_user'].includes(turn.state)){const link=action('查看工作进展',()=>openTask(turn.task_id),'work-turn-link');if(turn.task_id)holder.append(link);}
  if(prepend)$('messages').prepend(holder);else $('messages').append(holder);
  messageAdded(userBubble,'user',turn.user_text,turn.images,{restored:true});messageAdded(assistant,'assistant',turn.assistant_text||assistant.textContent,[],{restored:true});
  if(turn.task_id&&!terminal.has(turn.state))followHistory(turn,assistant);
 }
 function followHistory(turn,bubble){
  if(following.size>=5||following.has(turn.task_id))return;const uid=owner,version=epoch;let socket,cursor=turn.last_seq,closed=false,text=turn.assistant_text||'';
  const stop=()=>{closed=true;socket?.close();following.delete(turn.task_id);};following.set(turn.task_id,stop);
  function connect(){if(closed||!same(uid,version))return stop();socket=new WebSocket(location.origin.replace(/^http/,'ws')+base+'/tasks/'+turn.task_id+'/stream');socket.onopen=()=>socket.send(JSON.stringify({token,after:cursor}));socket.onmessage=e=>{if(!same(uid,version)||closed)return;const item=JSON.parse(e.data);if(item.seq<=cursor)return;cursor=item.seq;if(item.type==='task.delta'){text+=item.text||'';bubble.textContent=text;scrollConversation();}if(item.type==='task.result'){text=item.text||text;bubble.textContent=text;}if(item.type==='task.state'&&terminal.has(item.state)){messageAdded(bubble,'assistant',text||'本轮'+friendlyStates[item.state],[],{restored:true});stop();void refresh().catch(error);}};socket.onclose=()=>{if(!closed)setTimeout(connect,1800);};}connect();
 }
 async function resumeConversation(id,{navigate=true}={}){
  if(!/^[a-f0-9]{32}$/.test(id))return;saveDraft();epoch++;const version=epoch,uid=owner;clearConversation(!entered||(!navigate&&page!=='conversation'));cid=id;$('prompt').value='';resizeInput();loading=true;$('conversation-status').textContent='正在恢复对话…';messageCount();
  if(navigate){closeDialogs();showPage('conversation');}localStorage.setItem(key('active'),cid);$('compose').querySelector('[type=submit]').disabled=true;for(const id of ['realtime','push-to-talk','attachments-open','image-start-live','image-push-to-talk'])$(id).disabled=true;
  try{const data=await json('/assistant/conversations/'+id);if(!same(uid,version)||cid!==id)return;binding=data.conversation.device_id;const destination=$('destination');if([...destination.options].some(o=>o.value===binding))destination.value=binding;
   for(const turn of data.turns)restoreTurn(turn);messages=data.turns.flatMap(t=>[{role:'user',content:t.user_text},...(t.assistant_text?[{role:'assistant',content:t.assistant_text}]:[])]).slice(-200);currentTask=[...data.turns].reverse().find(t=>t.task_id)?.task_id||'';nextCursor=data.next_cursor;$('history-more').hidden=!nextCursor;
   $('conversation-status').textContent=data.turns.length?'':'从一句话开始这段对话。';$('prompt').value=sessionStorage.getItem(key('draft.'+cid))||'';resizeInput();
   const photo=[...data.turns].reverse().find(t=>t.images?.length);if(photo&&page==='conversation'&&!window.ShengjianVisual?.hasContext())void window.ShengjianVisual?.useSaved(photo.images[0],null,{open:false,origin:'conversation-history'}).catch(()=>{});
   if(data.conversation.archived)notice('这是已归档的对话，继续发送后会移回最近列表。');
  }catch(failure){if(!same(uid,version))return;if(failure.message==='conversation_not_found'){const draft=sessionStorage.getItem(key('draft.'+cid))||'';cid=crypto.randomUUID().replaceAll('-','');binding='';localStorage.setItem(key('active'),cid);sessionStorage.setItem(key('draft.'+cid),draft);$('prompt').value=draft;resizeInput();$('conversation-status').textContent='';}else{$('conversation-status').textContent='对话暂时无法加载，请稍后从历史中重试。';}}
  finally{if(same(uid,version)){loading=false;for(const id of ['realtime','push-to-talk','attachments-open','image-start-live','image-push-to-talk'])$(id).disabled=false;resizeInput();messageCount();scrollConversation(true);updateConnection();}}
 }
 $('history-more').onclick=async()=>{if(!nextCursor||loading)return;const uid=owner,version=epoch,scroll=$('conversation-scroll'),height=scroll.scrollHeight;loading=true;stick=false;try{const data=await json('/assistant/conversations/'+cid+'?before='+nextCursor);if(!same(uid,version))return;for(const turn of [...data.turns].reverse())restoreTurn(turn,true);nextCursor=data.next_cursor;$('history-more').hidden=!nextCursor;scroll.scrollTop+=scroll.scrollHeight-height;}finally{if(same(uid,version))loading=false;}};
 async function loadHistory(append=false){if(!owner||historyLoading)return;const uid=owner,version=epoch,mode=historyMode;historyLoading=true;$('history-load-more').disabled=true;$('history-status').textContent='正在加载…';try{const data=await json('/assistant/conversations?archived='+(mode==='archived')+(append&&historyCursor?'&before='+historyCursor:''));if(!same(uid,version)||mode!==historyMode)return;historyRows=append?[...historyRows,...data.conversations]:data.conversations;historyCursor=data.next_cursor;$('history-load-more').hidden=!historyCursor;renderHistory();}catch{if(same(uid,version))$('history-status').textContent='暂时无法加载，关闭后可以重新打开。';}finally{if(same(uid,version)){historyLoading=false;$('history-load-more').disabled=false;if(mode!==historyMode)void loadHistory();}}}
 $('history-load-more').onclick=()=>loadHistory(true);
 function renderHistory(){const query=$('conversation-search').value.trim().toLowerCase(),rows=historyRows.filter(r=>r.title.toLowerCase().includes(query));$('conversation-list').replaceChildren();$('history-status').textContent=rows.length?'':query?'没有找到这段对话。':historyMode==='archived'?'没有归档的对话。':'还没有历史对话，先聊一句吧。';for(const item of rows){const card=node('article',undefined,'conversation-item');card.append(action(item.title,()=>resumeConversation(item.id),'conversation-title'));const meta=node('div',undefined,'conversation-meta');meta.append(node('small',item.device_name+' · '+ago(item.updated)),action(historyMode==='archived'?'移回最近':'归档',async()=>{await json('/assistant/conversations/'+item.id,{archived:historyMode!=='archived'},'PATCH');await loadHistory();notice(historyMode==='archived'?'已移回最近对话。':'已归档，可在“已归档”中恢复。');}));card.append(meta);$('conversation-list').append(card);}}
 $('history-open').onclick=()=>{openDialog('history-dialog');void loadHistory();};$('conversation-search').oninput=renderHistory;
 for(const b of document.querySelectorAll('[data-history-view]'))b.onclick=()=>{historyMode=b.dataset.historyView;for(const x of document.querySelectorAll('[data-history-view]'))x.classList.toggle('selected',x===b);void loadHistory();};
 function renderDevices(){const devices=snapshot.devices.filter(d=>!d.revoked),signature=JSON.stringify(devices.map(d=>[d.id,d.name,d.online,d.capabilities,d.grants]));if(signature!==deviceSignature){deviceSignature=signature;$('device-list').replaceChildren();for(const device of devices){const card=node('article',undefined,'device-card');card.dataset.device=device.id;card.append(node('h2',device.name),node('p',device.capabilities.length?(device.capabilities.includes('tasks')?'电脑':'设备')+' · '+(device.online?'在线':'离线'):'浏览器登录记录','device-status'),node('p','','device-readings'));if(device.capabilities.length){const detail=node('details');detail.open=deviceExpanded.has(device.id);detail.append(node('summary','权限与访问'));detail.ontoggle=()=>detail.open?deviceExpanded.add(device.id):deviceExpanded.delete(device.id);for(const capability of device.capabilities){const label=node('label',undefined,'inline'),input=node('input');input.type='checkbox';input.checked=device.grants.includes(capability);input.onchange=async()=>{input.disabled=true;try{const grants=new Set(device.grants);input.checked?grants.add(capability):grants.delete(capability);await json('/devices/'+device.id,{grants:[...grants]},'PATCH');await refresh();}catch(e){input.checked=!input.checked;error(e);}finally{input.disabled=false;}};label.append(input,document.createTextNode({tasks:'执行任务',metrics:'状态监控',screen:'共享屏幕',input:'键鼠控制',files:'文件共享'}[capability]||capability));detail.append(label);}detail.append(action('撤销设备访问',async()=>{if(await confirmAction('撤销这台设备的访问？','设备将退出账号；正在执行的工作需要先核对结果。','撤销访问')){await json('/devices/'+device.id,undefined,'DELETE');await refresh();}},'device-remove'));card.append(detail);if(device.capabilities.includes('tasks')&&device.grants.includes('tasks')){const use=action('使用这台电脑',()=>newConversation(device.id),'subtle-button');use.disabled=!device.online;card.append(use);}}else card.append(action('退出此设备',async()=>{if(await confirmAction('撤销这台设备的访问？','设备将退出账号；正在执行的工作需要先核对结果。','撤销访问')){await json('/devices/'+device.id,undefined,'DELETE');await refresh();}},'device-remove'));$('device-list').append(card);}
   if(!devices.length)$('device-list').append(empty('还没有连接设备','在电脑端登录同一账号并启用电脑助手。','查看连接方法',()=>openDialog('connect-dialog')));
  }
  for(const device of devices){const target=$('device-list').querySelector(`[data-device="${device.id}"] .device-readings`);if(!target)continue;target.textContent=device.online?[['cpu_percent','CPU'],['memory_percent','内存'],['disk_percent','磁盘']].filter(([key])=>Number.isFinite(device.metrics?.[key])).map(([key,label])=>label+' '+device.metrics[key].toFixed(0)+'%').join(' · '):'';}
 }
 function updateConnection(){if(!snapshot)return;const all=snapshot.devices.filter(d=>!d.revoked&&d.grants.includes('tasks')),selected=binding||($('destination').value!=='chat'?$('destination').value:null),device=selected?all.find(d=>d.id===selected):all.filter(d=>d.online).length===1?all.find(d=>d.online):null;const online=!!device?.online;$('computer-status').dataset.online=String(online);$('computer-status').textContent=device?device.name+' · '+(online?'在线':'离线'):selected?'原电脑已移除':all.some(d=>d.online)?'选择一台电脑':'连接电脑，开始对话';}
 function renderWork(){if(!snapshot)return;const all=snapshot.tasks.filter(t=>t.is_work!==0),active=all.filter(t=>['queued','running'].includes(t.state)),attention=all.filter(t=>['awaiting_user','unknown'].includes(t.state)),done=all.filter(t=>['succeeded','failed','cancelled'].includes(t.state));$('work-overview').replaceChildren();for(const [name,list] of [['进行中',active],['待处理',attention],['已结束',done]]){const card=node('div',undefined,'work-stat');card.append(node('strong',String(list.length)),node('span',name));$('work-overview').append(card);}const list=workFilter==='active'?active:workFilter==='attention'?attention:workFilter==='done'?done:all;$('task-list').replaceChildren();if(!list.length)$('task-list').append(empty(workFilter==='active'?'现在没有进行中的工作':'这里还没有工作记录','说出要完成的事情，进展和结果会留在这里。','交给电脑做件事',()=>$('new-work').click()));for(const task of list){const spec=typeof task.specification==='string'?JSON.parse(task.specification):task.specification,b=action('',()=>openTask(task.id),'task-card');b.dataset.task=task.id;b.classList.toggle('selected',task.id===taskViewId);b.append(node('h3',(spec.voice_text||spec.prompt||'电脑任务').slice(0,100)));const meta=node('span',undefined,'task-meta');meta.append(stateBadge(task.cancel_requested&&!terminal.has(task.state)?'queued':task.state),node('span',task.cancel_requested&&!terminal.has(task.state)?'正在请求取消':ago(task.created)));b.append(meta);$('task-list').append(b);}const count=active.length+attention.filter(t=>t.state==='awaiting_user').length,badge=document.querySelector('[data-page=tasks] .nav-count');badge.hidden=!count;badge.textContent=String(count);const current=attention.find(t=>t.state==='awaiting_user')||active[0];$('active-work-strip').hidden=!current;if(current){const spec=JSON.parse(current.specification);$('active-work-strip').replaceChildren(action((current.state==='awaiting_user'?'需要确认 · ':'电脑正在处理 · ')+(spec.voice_text||spec.prompt).slice(0,32)+'　查看',()=>openTask(current.id)));}}
 for(const b of document.querySelectorAll('[data-work-filter]'))b.onclick=()=>{workFilter=b.dataset.workFilter;for(const x of document.querySelectorAll('[data-work-filter]'))x.classList.toggle('selected',x===b);renderWork();};
 for(const b of document.querySelectorAll('[data-life-view]'))b.onclick=()=>{for(const x of document.querySelectorAll('[data-life-view]'))x.classList.toggle('selected',x===b);for(const panel of document.querySelectorAll('[data-life-panel]'))panel.hidden=panel.dataset.lifePanel!==b.dataset.lifeView;};
 function voiceMinibar(){$('voice-minibar').hidden=!(live?.mode==='live'&&page!=='conversation'&&page!=='create');$('stop-speech').hidden=!playback;}
 new MutationObserver(voiceMinibar).observe($('realtime'),{attributes:true,attributeFilter:['aria-pressed']});
 function navigated(id,options={}){if(id!=='conversation')clearReplyFocus();page=id;document.body.dataset.activePage=id;document.title=titles[id]+' · 声笺';if(id==='tasks'&&!options.task)$('tasks').classList.remove('task-open');voiceMinibar();if(!options.fromHistory)route(!!options.replace,{...(options.task?{task:options.task}:{})});}
 window.addEventListener('popstate',()=>{if(!owner)return;const value=history.state||{page:'conversation'};closeDialogs();if(value.cid&&value.cid!==cid)void resumeConversation(value.cid,{navigate:false});showPage(titles[value.page]?value.page:'conversation',{fromHistory:true,task:value.task});if(value.modal)openDialog(value.modal,false);if(value.task)void openTask(value.task,{reveal:false}).then(()=>$('tasks').classList.add('task-open')).catch(error);});
 function taskOpened(id,reveal){if(reveal)$('tasks').classList.add('task-open');taskResult='';taskResultNode=node('div',undefined,'task-result');taskReadButton=action('朗读结果',()=>readText(taskResult),'subtle-button');taskReadButton.hidden=true;taskLogs=node('details');taskLogs.append(node('summary','运行详情'));$('task-detail').append(taskResultNode,taskReadButton,taskLogs);renderWork();}
 function taskEvent(item){if(!taskResultNode)return;if(item.type==='task.delta'){taskResult+=item.text||'';taskResultNode.textContent=taskResult;}else if(item.type==='task.result'){taskResult=item.text||taskResult;taskResultNode.textContent=taskResult;taskReadButton.hidden=!taskResult;}else if(item.type==='task.log'){let log;try{log=JSON.parse(item.text);}catch{}if(log?.type==='tool_call'){const names={background_browser:'正在操作后台浏览器',see_user_image:'正在查看图片',memory:'正在整理记忆',shell:'正在运行电脑操作'};$('task-detail').insertBefore(node('div',names[log.tool]||'正在处理电脑任务','task-step'),taskResultNode);}taskLogs.append(node('pre',item.text||''));}else if(item.type==='task.approval'){$('task-detail').append(node('p',item.text||'电脑需要你确认这一次操作。'));}}
 window.ShengjianProduct={
  update(value){snapshot=value;const uid=value.me.user_id;if(owner!==uid){owner=uid;epoch++;binding='';cid=localStorage.getItem(key('active'))||sessionStorage.getItem('shengjian.chat.'+uid+'.chat')||'';deviceSignature='';selectArtMode(localStorage.getItem(key('art-mode'))||'generate');if(cid)void resumeConversation(cid,{navigate:false});else{cid=crypto.randomUUID().replaceAll('-','');localStorage.setItem(key('active'),cid);}}$('profile-name').textContent=value.me.username||'我的账号';const letter=(value.me.username||'笺').slice(0,1).toUpperCase();$('profile-avatar').textContent=letter;$('profile-open').textContent=letter;renderDevices();renderWork();updateConnection();},
  entered(){entered=true;const query=new URLSearchParams(location.hash.slice(1)),initial=query.get('page');showPage(titles[initial]?initial:'conversation',{fromHistory:true});const requested=query.get('conversation');if(requested&&requested!==cid)void resumeConversation(requested,{navigate:false});route(true);},
  deactivate(){clearReplyFocus(true);saveDraft();closeFollowers();closeDialogs();for(const url of objectUrls)URL.revokeObjectURL(url);objectUrls.clear();if(owner){for(const item of Object.keys(sessionStorage))if(item.startsWith('shengjian.product.draft.')&&item.includes(owner))sessionStorage.removeItem(item);for(const item of Object.keys(sessionStorage))if(item==='shengjian.pending-turn.'+owner||item.startsWith('shengjian.pending-turn.'+owner+'.'))sessionStorage.removeItem(item);}owner='';epoch++;snapshot=null;acceptedTasks.clear();cid='';binding='';entered=false;page='conversation';history.replaceState({},'',location.pathname+location.search);delete document.body.dataset.activePage;historyRows=[];historyCursor=null;historyLoading=false;historyMode='recent';workFilter='active';deviceExpanded.clear();taskResult='';taskResultNode=null;taskLogs=null;taskReadButton=null;$('conversation-search').value='';for(const b of document.querySelectorAll('[data-history-view]'))b.classList.toggle('selected',b.dataset.historyView==='recent');for(const b of document.querySelectorAll('[data-work-filter]'))b.classList.toggle('selected',b.dataset.workFilter==='active');for(const b of document.querySelectorAll('[data-life-view]'))b.classList.toggle('selected',b.dataset.lifeView==='timeline');for(const panel of document.querySelectorAll('[data-life-panel]'))panel.hidden=panel.dataset.lifePanel!=='timeline';deviceSignature='';authMode(false);$('login-form').elements.password.type='password';$('show-password').textContent='显示';$('conversation-list').replaceChildren();$('profile-name').textContent='我的账号';$('active-work-strip').hidden=true;$('voice-minibar').hidden=true;},
  artMode:()=>artMode,selectArtMode,
  creationIntent(text){if(page!=='create')return null;const explicit=window.ShengjianImages.intent(text);if(explicit)return explicit;if(ShengjianAgent.control(text)||/^(?:请|帮我|麻烦)?(?:打开|执行|运行|整理文件|查看电脑|汇报电脑)/.test(text)||/^(?:请|帮我)?(?:不要|别|不用)(?:生成|画|修改|改图)/.test(text)||/^(?:这张图|图片|为什么|能不能|可以|怎么).*(?:什么|吗|原因|如何|意思)/.test(text))return null;return artMode==='edit'?'edit':'generate';},
  async creationControl(text){if(page!=='create'||/电脑|后台任务/.test(text)||!/(?:进度|好了没|完成了吗|画好|生成好了|取消.*(?:图|生成))/.test(text))return false;const job=await window.ShengjianImages.progress();const reply=!job?'还没有正在创作的图片，先说出你想要的画面。':/取消/.test(text)&&!terminal.has(job.state)?'这张图片已经提交，暂时不能撤回。完成后会留在创作记录中。':({queued:'正在等待创作，完成后会出现在下方。',running:'图片还在创作，完成后会出现在下方。',succeeded:'这张图片已完成，可以查看或继续修改。',failed:'这次没有完成，请查看图片下方的说明。',unknown:'还没有确认这次结果，先不要重复提交。'})[job.state]||'正在核对图片状态。';$('image-status').textContent=reply;$('prompt').value='';if(live&&$('speak').checked)await speak(reply);return true;},
  artReady(){if(page!=='create'){notice('图片已完成。');$('notice').append(action('查看图片',()=>showPage('create'),'subtle-button'));}},
  jobSubmitted(job,edit){selectArtMode(edit?'edit':'generate');$('image-prompt').value='';closeDialogs();showPage('create');},
  confirm:confirmAction,navigated,closeDialogs,showCreation(){if(page!=='create')showPage('create');},messageAdded,revealReply,scrollConversation,
  conversationFor(){return owner?cid:null;},
  turnAccepted(id,data){if(!owner||id!==cid)return;if(data.task?.id){acceptedTasks.set(data.task.id,cid);if(acceptedTasks.size>1000)acceptedTasks.delete(acceptedTasks.keys().next().value);}let accepted=data.task?.specification;try{if(typeof accepted==='string')accepted=JSON.parse(accepted);}catch{}if(sessionStorage.getItem(key('draft.'+cid))===(accepted?.voice_text||accepted?.prompt))sessionStorage.removeItem(key('draft.'+cid));if(data.task?.device_id)binding=data.task.device_id;localStorage.setItem(key('active'),cid);if(data.action==='chat'||data.device_id||data.task)void json('/assistant/conversations/'+cid,{archived:false},'PATCH').catch(()=>{});},
  workStarted(){void refresh().catch(error);},taskOpened,taskEvent,
  taskReportElsewhere(id,state){const origin=acceptedTasks.get(id);if(!origin||origin===cid)return false;notice(state==='succeeded'?'一项后台工作已完成。':'有一项后台处理需要查看。');$('notice').append(action('查看',()=>openTask(id),'subtle-button'));void refresh().catch(error);return true;},
  presentNotice(text){clearTimeout(toastTimer);if(!text)return;const close=action('×',()=>notice(''));close.setAttribute('aria-label','关闭提示');close.style.cssText='background:transparent;border:0;color:inherit;min-height:24px;padding:0 0 0 12px;float:right';$('notice').append(close);if(/^(?:已复制|设置已保存|模型已保存)/.test(text))toastTimer=setTimeout(()=>notice(''),3500);},
  authBusy(value){const submit=$('login-form').querySelector('.auth-submit');submit.disabled=value;$('auth-switch').disabled=value;submit.textContent=value?'请稍候…':submit.value==='register'?'注册并登录':'登录';}
 };
 resizeInput();if(appSnapshot)window.ShengjianProduct.update(appSnapshot);if(token&&!$('workspace').hidden)window.ShengjianProduct.entered();window.dispatchEvent(new Event('shengjian:product-ready'));
})();
