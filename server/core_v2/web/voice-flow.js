/* Bound pre-ready audio and pace its drain so a slow handshake never floods ASR. */
class VoicePCMFlow {
  constructor(send,finish,fail,{now=()=>performance.now(),schedule=(f,d)=>setTimeout(f,d),unschedule=id=>clearTimeout(id)}={}) {
    this.send=send;this.finish=finish;this.fail=fail;this.now=now;this.schedule=schedule;this.unschedule=unschedule;
    this.queue=[];this.queued=0;this.sent=0;this.started=null;this.earlyAllowed=false;this.ended=false;this.closed=false;this.timer=null;
  }
  push(pcm){if(this.closed||this.ended||!pcm.length)return;this.queue.push(pcm.slice());this.queued+=pcm.length;if(this.queued>128000){this.close();this.fail(new Error('voice_connection_slow'));return;}this.drain();}
  early(){if(this.closed)return;this.earlyAllowed=true;this.drain();}
  ready(){if(this.closed||this.started!==null)return;this.started=this.now();this.drain();}
  end(){if(this.closed||this.ended)return;this.ended=true;this.drain();}
  drain(){
    if(this.closed||(this.started===null&&!this.earlyAllowed))return;
    if(this.timer!==null){this.unschedule(this.timer);this.timer=null;}
    let budget=this.started===null?16000-this.sent:Math.floor(24000+(this.now()-this.started)*16-this.sent);
    try {
      while(this.queue.length&&budget>0){const first=this.queue[0],count=Math.min(first.length,3200,budget);this.send(first.slice(0,count));this.sent+=count;this.queued-=count;budget-=count;if(count===first.length)this.queue.shift();else this.queue[0]=first.slice(count);}
      if(this.ended&&!this.queue.length&&this.started!==null){this.closed=true;this.finish();return;}
      if(this.queue.length&&this.started!==null)this.timer=this.schedule(()=>{this.timer=null;this.drain();},20);
    }catch(error){this.close();this.fail(error);}
  }
  close(){this.closed=true;if(this.timer!==null)this.unschedule(this.timer);this.timer=null;this.queue=[];this.queued=0;}
}
if(typeof module!=='undefined')module.exports=VoicePCMFlow;
