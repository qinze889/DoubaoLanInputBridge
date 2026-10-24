/* Physical press is the only authority to capture microphone audio in this mode. */
(()=>{
  const buttons=[document.getElementById('push-to-talk'),document.getElementById('image-push-to-talk')];
  let gesture=null,owner='',mode='live';
  const state=document.getElementById('live-state');
  const labels=()=>{for(const b of buttons){b.textContent=b.id==='image-push-to-talk'?'按住说出需求':'按住说话，松开发送';b.setAttribute('aria-pressed','false');b.classList.remove('recording','cancel');}};
  function switchMode(value,save=true){
    if(!['live','hold'].includes(value))return;
    if(gesture){gesture.cancelled=true;endManualVoice(gesture,true);gesture=null;}
    if(mode!==value&&live)stopLive('语音方式已切换',true);
    mode=value;document.getElementById('realtime').hidden=value==='hold';buttons[0].hidden=value!=='hold';state.hidden=value!=='hold';
    for(const b of document.querySelectorAll('[data-voice-mode]')){const chosen=b.dataset.voiceMode===value;b.setAttribute('aria-pressed',String(chosen));b.classList.toggle('selected',chosen);}
    document.getElementById('voice-note').textContent=value==='hold'?'单次约30秒，上滑取消；打断播报不影响工作。':'开口可打断，后台工作继续。';
    if(save&&owner)localStorage.setItem('shengjian.voice-mode.'+owner,value);
    labels();if(value==='hold'&&!live)state.textContent='按住说话，松开发送；上滑取消。';
  }
  async function begin(button,event,source='pointer'){
    if(gesture&&!gesture.held)gesture=null;
    if(gesture||!token)return;
    switchMode('hold');
    const current={held:true,ready:false,cancelled:false,button,source,startY:event.clientY,pointerId:event.pointerId,touchId:event.identifier};gesture=current;
    if(event.pointerId!==undefined)try{button.setPointerCapture(event.pointerId);}catch{}
    button.textContent='正在开启麦克风…';button.setAttribute('aria-pressed','true');state.textContent='准备好后说话，松开即可发送。';
    try{await startManualVoice(current);}catch(failure){reportVoiceFailure('capture',failure,'hold');error(failure);}
    finally{if(gesture===current&&!current.held){gesture=null;labels();}}
  }
  function release(event,cancel=false,reason=''){
    const current=gesture;if(!current)return;
    if(event?.pointerId!==undefined&&event.pointerId!==current.pointerId)return;
    gesture=null;if(cancel&&reason)reportVoiceFailure('capture',new Error('hold_'+reason),'hold');endManualVoice(current,cancel);labels();
  }
  function move(current,y){current.cancelled=current.startY-y>64;current.button.classList.toggle('cancel',current.cancelled);if(current.ready)current.button.textContent=current.cancelled?'松开取消':'松开发送 · 上滑取消';}
  for(const button of buttons){
    button.draggable=false;
    button.onpointerdown=event=>{if(event.pointerType==='touch'||event.button!==0||!event.isPrimary)return;event.preventDefault();void begin(button,event);};
    button.onpointermove=event=>{if(gesture?.source!=='pointer'||gesture.button!==button||gesture.pointerId!==event.pointerId)return;move(gesture,event.clientY);};
    // Touch owns its physical contact until touchend/touchcancel. Browser focus
    // changes and lost pointer capture do not mean that the finger was lifted.
    button.addEventListener('touchstart',event=>{if(gesture||!event.changedTouches.length)return;event.preventDefault();const touch=event.changedTouches[0];void begin(button,touch,'touch');},{passive:false});
    button.oncontextmenu=event=>event.preventDefault();
    button.onblur=()=>{if(gesture?.button===button&&gesture.source==='keyboard')release(null,true,'keyboard_blur');};
    button.onkeydown=event=>{if(event.key==='Escape'){event.preventDefault();release(null,true);}else if([' ','Enter'].includes(event.key)){event.preventDefault();if(!event.repeat)void begin(button,{},'keyboard');}};
    button.onkeyup=event=>{if([' ','Enter'].includes(event.key)){event.preventDefault();if(gesture?.source==='keyboard')release(null);}};
  }
  document.addEventListener('pointerup',event=>{if(gesture?.source==='pointer'){event.preventDefault();release(event);}},{capture:true});
  document.addEventListener('pointercancel',event=>{if(gesture?.source==='pointer')release(event,true,'pointer_cancel');},{capture:true});
  document.addEventListener('touchmove',event=>{if(gesture?.source!=='touch')return;const touch=[...event.touches].find(t=>t.identifier===gesture.touchId);if(touch){event.preventDefault();move(gesture,touch.clientY);}},{passive:false,capture:true});
  document.addEventListener('touchend',event=>{if(gesture?.source!=='touch'||![...event.changedTouches].some(t=>t.identifier===gesture.touchId))return;event.preventDefault();release(null);},{passive:false,capture:true});
  document.addEventListener('touchcancel',event=>{if(gesture?.source==='touch'&&[...event.changedTouches].some(t=>t.identifier===gesture.touchId))release(null,true,'touch_cancel');},{capture:true});
  window.addEventListener('blur',()=>{if(gesture&&gesture.source!=='touch')release(null,true,'window_blur');});
  for(const b of document.querySelectorAll('[data-voice-mode]'))b.onclick=()=>switchMode(b.dataset.voiceMode);
  document.getElementById('image-start-live').onclick=()=>{switchMode('live');document.getElementById('realtime').click();};
  window.ShengjianPTT={
    activate(uid){if(owner===uid)return;owner=uid;switchMode(localStorage.getItem('shengjian.voice-mode.'+uid)||'live',false);},
    deactivate(){if(gesture)release(null,true);owner='';switchMode('live',false);},
    select:switchMode,mode:()=>mode,
    reset(){if(gesture)gesture.held=false;gesture=null;labels();},
    ready(){labels();},
    recording(){if(gesture){gesture.button.textContent='松开发送 · 上滑取消';gesture.button.classList.add('recording');}},
    recognizing(){state.textContent='正在识别，完成后自动发送。';}
  };
  if(chatOwner)window.ShengjianPTT.activate(chatOwner);
})();
