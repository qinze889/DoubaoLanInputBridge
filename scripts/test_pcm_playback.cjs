const assert = require('node:assert/strict');
const fs = require('node:fs');
const { chromium } = require('../desktop/node_modules/playwright');
const { PCMPlayback, PCMRateConverter } = require('../server/core_v2/web/stream.js');
const source = Float32Array.from({length:24000}, (_,i)=>.5*Math.sin(2*Math.PI*1703*i/24000));
function convert(rate,size) {
  const converter=new PCMRateConverter(rate),parts=[];
  for(let i=0;i<source.length;i+=size)parts.push(converter.push(source.slice(i,i+size)));
  parts.push(converter.push(new Float32Array(0),true));
  return Float32Array.from(parts.flatMap(part=>Array.from(part)));
}
(async()=>{
  for(const rate of [16000,24000,44100,48000]) {
    const whole=convert(rate,source.length);
    assert.equal(whole.length,rate,'no dropped or duplicated tail samples');
    for(const size of [1,127,480,1024,2048])assert.deepEqual(convert(rate,size),whole,`continuous filter history at ${rate} Hz / ${size} samples`);
    let error=0;
    for(let i=100;i<whole.length-100;i++)error+=(whole[i]-.5*Math.sin(2*Math.PI*1703*i/rate))**2;
    assert(Math.sqrt(error/(whole.length-200))<.001,'speech-band fidelity and unchanged pitch');
  }
  let clock=0,stops=0;const scheduled=[],references=[];
  const context={sampleRate:48000,state:'running',get currentTime(){return clock;},createBuffer(c,n,rate){return{duration:n/rate,getChannelData(){return new Float32Array(n);}};},createBufferSource(){const node={connect(){},disconnect(){},start(at){scheduled.push({at,duration:this.buffer.duration});},stop(){stops++;}};return node;}};
  const player=new PCMPlayback(context,()=>{}, {add(values,at,rate){references.push({n:values.length,at,rate});},cut(){}});
  const bytes=Buffer.from(Int16Array.from(source.slice(0,2048),v=>v*32767).buffer);
  await player.push(bytes.subarray(0,3).toString('base64'));
  await player.push(bytes.subarray(3).toString('base64'));
  assert.equal(scheduled.length,1,'odd packet boundaries preserve PCM sample alignment');
  clock=.13; // 15 ms before the next packet; old per-packet lead inserted a gap.
  await player.push(bytes.toString('base64'));
  assert.equal(scheduled[1].at,scheduled[0].at+scheduled[0].duration,'moderate packet jitter remains gapless');
  assert(references.every(r=>r.rate===48000),'echo timestamps use the actual output sample rate');
  player.mark('已播放片段',0);
  assert.equal(references.reduce((n,r)=>n+r.n,0),8192,'segment tail is rendered once');
  const count=scheduled.length;player.finishSegment();assert.equal(scheduled.length,count);
  clock=player.next+.2;assert.equal(player.heard(),'已播放片段');
  await player.push(bytes.toString('base64'));
  assert(scheduled.at(-1).at>=clock,'true underrun re-buffers instead of scheduling in the past');
  player.pause();assert.equal(stops,scheduled.length);await player.push(bytes.toString('base64'));assert.equal(scheduled.length,count+1,'interruption never resurrects old sound');
  const browser=await chromium.launch({headless:true,...(process.env.SHENGJIAN_UI_BROWSER?{executablePath:process.env.SHENGJIAN_UI_BROWSER}:{})});
  try {
    const page=await browser.newPage();await page.addScriptTag({content:fs.readFileSync('server/core_v2/web/stream.js','utf8')});
    const results=await page.evaluate(async()=>{
      const results=[];
      for(const rate of [44100,48000]) {
        const pcm=Int16Array.from({length:24000},(_,i)=>18000*Math.sin(2*Math.PI*1703*i/24000)),rendered=[];
        for(const size of [24000,2048,480]) {
          const offline=new OfflineAudioContext(1,Math.ceil(rate*1.2),rate);
          const context={sampleRate:rate,state:'running',currentTime:0,destination:offline.destination,createBuffer:offline.createBuffer.bind(offline),createBufferSource:offline.createBufferSource.bind(offline)};
          const player=new PCMPlayback(context);
          for(let i=0;i<pcm.length;i+=size)await player.push(btoa(String.fromCharCode(...new Uint8Array(pcm.slice(i,i+size).buffer))));
          player.mark('合成音测试',0);
          rendered.push((await offline.startRendering()).getChannelData(0));
        }
        for(let k=1;k<rendered.length;k++) {
          let peak=0;for(let i=0;i<rendered[0].length;i++)peak=Math.max(peak,Math.abs(rendered[k][i]-rendered[0][i]));
          results.push({sample_rate:rate,chunk_samples:[2048,480][k-1],max_boundary_difference:peak});
        }
      }
      return results;
    });
    assert(results.every(r=>r.max_boundary_difference<1e-6),'actual Web Audio output is independent of packet boundaries');
    console.log(JSON.stringify({continuous_pcm:true,odd_bytes:true,jitter_cushion_ms:60,echo_rate:true,cancel_no_replay:true,offline_audio:results}));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
