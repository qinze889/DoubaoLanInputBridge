const assert=require('node:assert/strict'),Flow=require('../server/core_v2/web/voice-flow.js');
let clock=0,timer,finished=0;const sent=[];
const flow=new Flow(x=>sent.push(x),()=>finished++,e=>{throw e;},{now:()=>clock,schedule:f=>(timer=f,1),unschedule:()=>{timer=null;}});
for(let i=0;i<12;i++)flow.push(new Int16Array(8000).fill(i));
assert.equal(sent.length,0);flow.end();assert.equal(finished,0);flow.ready();assert.equal(sent.reduce((n,x)=>n+x.length,0),24000,'1.5 second burst leaves server rate headroom');
for(let i=1;i<=45;i++){clock=i*100;timer?.();assert(sent.reduce((n,x)=>n+x.length,0)<=24000+clock*16);}
assert.equal(finished,1);assert.equal(sent.reduce((n,x)=>n+x.length,0),96000);const all=Int16Array.from(sent.flatMap(x=>Array.from(x)));for(let i=0;i<all.length;i++)assert.equal(all[i],Math.floor(i/8000),'no reordered or dropped capture prefix');
flow.end();flow.ready();assert.equal(finished,1);
let failed=false;const stalled=new Flow(()=>{},()=>assert.fail('cancelled buffer finished'),()=>failed=true);stalled.push(new Int16Array(128001));assert(failed);assert(stalled.closed);
let calls=0;const cancelled=new Flow(()=>calls++,()=>calls++,()=>calls++);cancelled.push(new Int16Array(400));cancelled.close();cancelled.ready();cancelled.end();assert.equal(calls,0);

let earlySent=0,earlyNow=0,earlyFinish=0;const early=new Flow(p=>earlySent+=p.length,()=>earlyFinish++,()=>assert.fail(),{now:()=>earlyNow,schedule:()=>1,unschedule:()=>{}});
early.push(new Int16Array(64000));early.early();assert.equal(earlySent,16000,'only one second is sent before upstream readiness');earlyNow=5000;early.push(new Int16Array(16000));assert.equal(earlySent,16000,'readiness stall cannot expand early burst');early.end();assert.equal(earlyFinish,0);early.ready();assert.equal(earlySent,24000,'early data counts against initial ready budget');earlyNow=8500;early.drain();assert.equal(earlySent,80000);assert.equal(earlyFinish,1);

console.log('Voice flow: six-second handshake queue, ordered lossless paced drain, bounded burst, finish once, overflow and cancellation passed');
