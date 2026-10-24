/* Physical press is the only authority to capture microphone audio in this mode. */
(()=>{
  const buttons=[document.getElementById('push-to-talk'),document.getElementById('image-push-to-talk')];
  let gesture=null,owner='',mode='live';
  const state=document.getElementById('live-state');
  const labels=()=>{for(const b of buttons){b.textContent=b.id==='image-push-to-talk'?'按住说话改图':'按住说话，松开发送';b.setAttribute('aria-pressed','false');b.classList.remove('recording','cancel');}};
  function switchMode(value,save=true){
    if(!['live','hold'].includes(value))return;
    if(gesture){gesture.cancelled=true;endManualVoice(gesture,true);gesture=null;}
    if(mode!==value&&live)stopLive('语音方式已切换',true);
    mode=value;document.getElementById('realtime').hidden=value==='hold';buttons[0].hidden=value!=='hold';state.hidden=value!=='hold';
    for(const b of document.querySelectorAll('[data-voice-mode]')){const chosen=b.dataset.voiceMode===value;b.setAttribute('aria-pressed',String(chosen));b.classList.toggle('selected',chosen);}
    document.getElementById('voice-note').textContent=value==='hold'?'按住说话，松开发送；上滑取消。单次约30秒，到时自动发送；打断播报不会取消后台工作。':'随时开口打断。停止播报不会取消后台工作。';
    if(save&&owner)localStorage.setItem('shengjian.voice-mode.'+owner,value);
    labels();if(value==='hold'&&!live)state.textContent='按住说话，松开发送；上滑取消。';
  }
  async function begin(button,event){
    if(gesture||!token)return;
    switchMode('hold');
    const current={held:true,ready:false,cancelled:false,button,startY:event.clientY,pointerId:event.pointerId};gesture=current;
    if(event.pointerId!==undefined)try{button.setPointerCapture(event.pointerId);}catch{}
    button.textContent='正在开启麦克风…';button.setAttribute('aria-pressed','true');state.textContent='准备好后说话，松开即可发送。';
    try{await startManualVoice(current);}catch(failure){reportVoiceFailure('capture',failure,'hold');error(failure);}
    finally{if(gesture===current&&!current.held){gesture=null;labels();}}
  }
  function release(event,cancel=false){
    const current=gesture;if(!current)return;
    if(event?.pointerId!==undefined&&event.pointerId!==current.pointerId)return;
    gesture=null;endManualVoice(current,cancel);labels();
  }
  for(const button of buttons){
    button.onpointerdown=event=>{if(event.button!==0||!event.isPrimary)return;event.preventDefault();void begin(button,event);};
    button.onpointermove=event=>{if(!gesture||gesture.button!==button||gesture.pointerId!==event.pointerId)return;gesture.cancelled=gesture.startY-event.clientY>64;button.classList.toggle('cancel',gesture.cancelled);if(gesture.ready)button.textContent=gesture.cancelled?'松开取消':'松开发送 · 上滑取消';};
    button.onpointerup=event=>{event.preventDefault();release(event);};
    button.onpointercancel=event=>release(event,true);
    button.onlostpointercapture=event=>{if(gesture?.pointerId===event.pointerId)release(event,true);};
    button.oncontextmenu=event=>event.preventDefault();
    button.onblur=()=>{if(gesture?.button===button)release(null,true);};
    button.onkeydown=event=>{if(event.key==='Escape'){event.preventDefault();release(null,true);}else if([' ','Enter'].includes(event.key)){event.preventDefault();if(!event.repeat)void begin(button,{});}};
    button.onkeyup=event=>{if([' ','Enter'].includes(event.key)){event.preventDefault();release(null);}};
  }
  window.addEventListener('blur',()=>release(null,true));
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
