/* WebRTC direct transport. The relay is used only for the SDP handshake. */
class ShengjianDirect {
  constructor(base, report) { this.base=base;this.report=report;this.pc=null;this.channel=null;this.pending=new Map();this.buffers=new Map();this.connecting=null;this.sendChain=Promise.resolve(); }
  close() {
    if(this.pc)this.pc.close();this.pc=null;this.channel=null;this.connecting=null;
    for(const p of this.pending.values())p.reject(Error('P2P 连接已断开，结果可能未知，请确认后再发送。'));
    this.pending.clear();this.buffers.clear();
  }
  async connect() {
    if(this.channel?.readyState==='open')return;
    if(this.connecting)return this.connecting;
    this.connecting=this.open().finally(()=>{this.connecting=null});return this.connecting;
  }
  async open() {
    if(!window.RTCPeerConnection)throw Error('浏览器不支持 P2P，请使用 Safari/Chrome 或切换公网方式。');
    const pc=new RTCPeerConnection({iceServers:[{urls:'stun:stun.cloudflare.com:3478'}]});this.pc=pc;
    const ch=pc.createDataChannel('shengjian',{ordered:true});ch.binaryType='arraybuffer';this.channel=ch;
    ch.onmessage=e=>this.receive(e.data);
    ch.onclose=()=>{for(const p of this.pending.values())p.reject(Error('P2P 已断开，请确认结果后再发送。'));this.pending.clear();this.report(false)};
    pc.onconnectionstatechange=()=>{if(pc.connectionState==='failed'){ch.close();this.report(false)}};
    try {
      await pc.setLocalDescription(await pc.createOffer());
      if(pc.iceGatheringState!=='complete')await new Promise((resolve,reject)=>{const timer=setTimeout(()=>{if(pc.localDescription?.sdp.includes('a=candidate:'))resolve();else reject(Error('P2P 地址发现超时，请切换公网或 CF 隧道。'))},12000);pc.addEventListener('icegatheringstatechange',()=>{if(pc.iceGatheringState==='complete'){clearTimeout(timer);resolve()} });});
      const res=await fetch(this.base+'p2p/offer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(pc.localDescription)});
      const result=await res.json();if(!res.ok||!result.ok)throw Error(result.error||'P2P 握手失败');
      await pc.setRemoteDescription(result.answer);
      if(ch.readyState!=='open')await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('P2P 打洞失败，请切换固定公网或 CF 隧道。')),20000);ch.onopen=()=>{clearTimeout(timer);resolve()};ch.onerror=()=>{clearTimeout(timer);reject(Error('P2P 连接失败'))};});
      this.report(true);
    }catch(e){this.close();throw e}
  }
  receive(value) {
    try {
      if(value instanceof ArrayBuffer) {
        const bytes=new Uint8Array(value);if(bytes.length<33||bytes.length>16417||bytes[0]!==68)throw Error('frame');
        const id=new TextDecoder().decode(bytes.subarray(1,33)),entry=this.buffers.get(id);if(!entry||entry.offset+bytes.length-33>entry.bytes.length)throw Error('size');
        entry.bytes.set(bytes.subarray(33),entry.offset);entry.offset+=bytes.length-33;return;
      }
      if(typeof value!=='string'||value.length>512)throw Error('control');
      const c=JSON.parse(value);if(!/^[a-f0-9]{32}$/.test(c.id))throw Error('id');
      if(c.type==='start') {
        if(!Number.isInteger(c.bytes)||c.bytes<1||c.bytes>33554432||this.buffers.size>1||this.buffers.has(c.id)||Array.from(this.buffers.values()).reduce((sum,e)=>sum+e.bytes.length,0)+c.bytes>33554432)throw Error('budget');
        this.buffers.set(c.id,{bytes:new Uint8Array(c.bytes),offset:0});
      }else if(c.type==='end') {
        const entry=this.buffers.get(c.id);this.buffers.delete(c.id);if(!entry||entry.offset!==entry.bytes.length)throw Error('incomplete');
        const data=JSON.parse(new TextDecoder().decode(entry.bytes));if(data.id!==c.id||!data.response)throw Error('response');
        const p=this.pending.get(c.id);if(p){this.pending.delete(c.id);p.resolve(data.response)}
      }else throw Error('control');
    }catch { this.close(); }
  }
  async transmit(job) {
    const bytes=new TextEncoder().encode(JSON.stringify(job)),ch=this.channel;if(bytes.length>33554432)throw Error('文件超出 P2P 单次上限');
    const ident=new TextEncoder().encode(job.id);ch.send(JSON.stringify({type:'start',id:job.id,bytes:bytes.length}));
    for(let offset=0;offset<bytes.length;offset+=16384) {
      const deadline=Date.now()+30000;while(ch.bufferedAmount>524288){if(ch.readyState!=='open'||Date.now()>deadline)throw Error('P2P 发送超时');await new Promise(r=>setTimeout(r,10))}
      const part=bytes.subarray(offset,offset+16384),frame=new Uint8Array(33+part.length);frame[0]=68;frame.set(ident,1);frame.set(part,33);ch.send(frame);
    }
    ch.send(JSON.stringify({type:'end',id:job.id}));
  }
  async fetch(path,options={}) {
    await this.connect();
    const request=new Request('https://shengjian.invalid/'+path,options),body=new Uint8Array(await request.arrayBuffer());
    let binary='';for(let off=0;off<body.length;off+=8192)binary+=String.fromCharCode(...body.subarray(off,off+8192));
    const id=crypto.randomUUID().replaceAll('-',''),job={id,method:request.method,path:'/'+path.replace(/^r\//,''),body:btoa(binary),content_type:request.headers.get('Content-Type')||'application/json'};
    let timer;const response=new Promise((resolve,reject)=>{timer=setTimeout(()=>{this.pending.delete(id);reject(Error('电脑未返回结果，请确认后再发送。本次不会自动重发。'))},90000);this.pending.set(id,{resolve,reject})});
    response.catch(()=>{});
    try {
      const send=this.sendChain.then(()=>this.transmit(job));this.sendChain=send.catch(()=>{});await send;
      const r=await response,bytes=Uint8Array.from(atob(r.body),c=>c.charCodeAt(0));
      return new Response(bytes,{status:r.status,headers:{'Content-Type':r.content_type}});
    }finally{clearTimeout(timer);this.pending.delete(id)}
  }
}
window.ShengjianDirect=ShengjianDirect;
