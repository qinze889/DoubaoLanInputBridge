"use strict";
(() => {
  const $=id=>document.getElementById(id);
  let uid='',api=null,epoch=0,current=null,media=null,cameraEpoch=0,framePromise=null,opening=false,cameraWaiters=[];
  function note(text){$('visual-status').textContent=text;}
  function changed(origin='user'){window.dispatchEvent(new CustomEvent('shengjian:visual-change',{detail:{origin}}));}
  function dispose(){if(current){if(current.url)URL.revokeObjectURL(current.url);for(const w of current.waiters)w.reject(new Error('图片已更换'));current=null;}}
  function preview(){const img=$('visual-photo');img.hidden=!current?.url;img.src=current?.url || '';$('visual-clear').disabled=!current&&!media;}
  function stopCamera(){opening=false;for(const w of cameraWaiters)w.reject(new Error('摄像头已关闭'));cameraWaiters=[];const active=!!media;cameraEpoch++;media?.getTracks().forEach(t=>t.stop());media=null;$('visual-video').srcObject=null;$('visual-video').hidden=true;$('visual-camera-toggle').disabled=false;$('visual-camera-toggle').textContent='开启摄像头';$('visual-camera-toggle').setAttribute('aria-pressed','false');if(current&&active)note('摄像头已关闭，仍可聊最后一张图片。');}
  function beginSelection(options={}){stopCamera();dispose();const selectionId=crypto.randomUUID();current={selectionId,preparing:true,url:'',id:null,waiters:[],epoch,origin:options.origin||'user'};preview();note('正在准备图片，请稍等保存完成后提问。');changed(options.origin||'user');return selectionId;}
  function selectionFailed(selectionId,error){if(current?.selectionId!==selectionId)return;current.error=error;for(const w of current.waiters)w.reject(error);current.waiters=[];note('图片未就绪：'+error.message);}
  function pendingPhoto(blob,requestId,options={}){
    if(!uid)return;
    if(options.selectionId){if(current?.selectionId!==options.selectionId)return;Object.assign(current,{requestId,blob,url:URL.createObjectURL(blob),preparing:false,error:null});}
    else{if(!options.silent)stopCamera();dispose();current={requestId,blob,url:URL.createObjectURL(blob),id:null,waiters:[],epoch};}
    preview();note('图片正在保存，保存后即可直接语音提问。');if(!options.silent&&!options.selectionId)changed();
  }
  function photoReady(owner,requestId,id,entryId){if(owner!==uid||current?.requestId!==requestId)return;current.id=id;current.entryId=entryId;for(const w of current.waiters)w.resolve(id);current.waiters=[];window.dispatchEvent(new CustomEvent('shengjian:visual-ready',{detail:{id,origin:current.origin||'user'}}));note(media?'摄像头已开启。本轮画面已保存，可以继续提问。':'当前图片已就绪，直接开口提问即可。');}
  function photoFailed(owner,requestId,error){if(owner!==uid||current?.requestId!==requestId)return;for(const w of current.waiters)w.reject(error);current.waiters=[];note('图片仍在本机，尚未同步：'+error.message);}
  async function useSaved(id,entryId,options={}){if(!uid||!api)throw new Error('请先登录');const owner=uid,version=epoch,client=api,selectionId=beginSelection(options);try{const response=await client.fetchImage(id),blob=await response.blob();if(owner!==uid||version!==epoch||current?.selectionId!==selectionId)return false;pendingPhoto(blob,'saved-'+id,{selectionId});photoReady(owner,'saved-'+id,id,entryId);if(options.open!==false)await window.ShengjianConversation?.openVisual(false);return true;}catch(error){selectionFailed(selectionId,error);throw error;}}
  async function ready(){if(!current)return[];if(current.error)throw current.error;if(current.id)return[current.id];const state=current;void window.ShengjianLife?.flush();return new Promise((resolve,reject)=>{let timer;const waiter={resolve:id=>{clearTimeout(timer);resolve([id]);},reject:e=>{clearTimeout(timer);reject(e);}};state.waiters.push(waiter);timer=setTimeout(()=>{state.waiters=state.waiters.filter(w=>w!==waiter);reject(new Error('图片尚未保存，请联网同步后再提问。'));},15000);});}
  function cameraReady(){if(!opening)return Promise.resolve();return new Promise((resolve,reject)=>{let timer;const waiter={resolve:()=>{clearTimeout(timer);resolve();},reject:e=>{clearTimeout(timer);reject(e);}};cameraWaiters.push(waiter);timer=setTimeout(()=>{cameraWaiters=cameraWaiters.filter(w=>w!==waiter);reject(new Error('摄像头仍未就绪，请确认相机权限后重试。'));},15000);});}
  async function captureFrame(prompt){
    if(framePromise)return framePromise;
    const owner=uid,version=epoch,cam=cameraEpoch,video=$('visual-video');
    if(!media||!video.videoWidth||media.getVideoTracks().some(t=>t.readyState!=='live'||t.muted))throw new Error('摄像头画面尚未就绪，请稍后提问。');
    framePromise=(async()=>{const scale=Math.min(1,1600/Math.max(video.videoWidth,video.videoHeight)),canvas=document.createElement('canvas');canvas.width=Math.round(video.videoWidth*scale);canvas.height=Math.round(video.videoHeight*scale);canvas.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',.85));if(!blob)throw new Error('无法读取摄像头画面。');if(owner!==uid||version!==epoch||cam!==cameraEpoch)throw new Error('摄像头已关闭');await window.ShengjianLife.attachPhoto(blob,'视频对话提问时的画面',{silent:true});})();
    try{await framePromise;}finally{framePromise=null;}
  }
  async function snapshot(prompt){if(opening)await cameraReady();if(media)await captureFrame(prompt);const state=current,version=epoch;const images=await ready();if(version!==epoch||state!==current)throw new Error('图片已更换，请重新提问。');return{images};}
  async function attach(files){if(files.length!==1)throw new Error('每次选择一张图片。');await window.ShengjianConversation?.openVisual(false);const owner=uid,version=epoch,selectionId=beginSelection();try{const blob=await window.ShengjianLife.compress(files[0]);if(owner!==uid||version!==epoch)return;await window.ShengjianLife.attachPhoto(blob,'',{selectionId});}catch(error){selectionFailed(selectionId,error);throw error;}}
  for(const id of ['visual-upload','visual-take-photo'])$(id).onchange=e=>{attach([...e.target.files]).catch(e=>note(e.message)).finally(()=>{e.target.value='';});};
  $('visual-camera-toggle').onclick=async()=>{
    if(media){stopCamera();changed();return;}const version=epoch;let cam;
    try{
      await window.ShengjianConversation?.openVisual(false);cam=++cameraEpoch;dispose();preview();opening=true;note('正在开启摄像头，画面就绪后即可提问。');changed();$('visual-camera-toggle').disabled=true;$('visual-clear').disabled=false;
      const stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'},width:{ideal:1280},height:{ideal:720}},audio:false});
      if(version!==epoch||cam!==cameraEpoch||!uid){stream.getTracks().forEach(t=>t.stop());return;}
      media=stream;stream.getVideoTracks().forEach(t=>t.addEventListener('ended',()=>{if(media===stream){stopCamera();note('摄像头已断开，仍可聊最后一张已保存图片。');changed();}}));const video=$('visual-video');video.srcObject=stream;video.hidden=false;await video.play();if(version!==epoch||media!==stream)return;
      $('visual-camera-toggle').textContent='关闭摄像头';$('visual-camera-toggle').setAttribute('aria-pressed','true');$('visual-clear').disabled=false;$('visual-camera-toggle').disabled=false;note('摄像头已开启。提问时只保存一张当前画面，随后和对话一起晚间整理。');opening=false;for(const w of cameraWaiters)w.resolve();cameraWaiters=[];
    }catch(error){if(version!==epoch||cam!==cameraEpoch)return;stopCamera();note('摄像头未开启：'+error.message);changed();}
  };
  $('visual-clear').onclick=()=>{stopCamera();dispose();preview();note('已结束看图，照片和对话仍保留在生活记录。');changed();};
  document.addEventListener('visibilitychange',()=>{if(document.hidden)stopCamera();});
  window.addEventListener('pagehide',stopCamera);
  window.ShengjianVisual={
    activate(owner,client){if(uid!==owner){stopCamera();dispose();epoch++;uid=owner;preview();note('拍照或上传后即可直接语音聊图，也可以开启摄像头边看边聊。');}api=client;},
    deactivate(){uid='';epoch++;stopCamera();dispose();preview();api=null;},
    attach,pendingPhoto,photoReady,photoFailed,useSaved,snapshot,stopCamera,beginSelection,selectionFailed,
    hasContext(){return !!(current||media||opening);},
    images(){return current?.id?[current.id]:[];},
    removed(ids){if(current?.id&&ids.includes(current.id)){$('visual-clear').click();}}
  };
})();
