const assert=require('node:assert/strict'),fs=require('node:fs'),{createHmac}=require('node:crypto');
const ts=require('../desktop/node_modules/typescript');
const text=ts.transpileModule(fs.readFileSync(require('node:path').resolve(__dirname,'../desktop/src/localService.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const exported={};new Function('exports',text)(exported);
const {requestLocal}=exported,identity={service:'shengjian.bridge',protocol:1,port:54321,pid:12345,instance_id:'0123456789abcdef0123456789abcdef'},runtime={running:true,port:54321,key:'fixture-local-service-key',identity};
const original=global.fetch;let mode='valid',calls=[],replay=null;
global.fetch=async(url,options={})=>{
 calls.push({url,options});
 if(url.endsWith('/health')){
  assert(!url.includes(runtime.key)&&!options.body,'health proof never sends the access key');assert.equal(options.redirect,'error');
  if(mode==='html')return new Response('<title>Other app</title>',{headers:{'Content-Type':'text/html'}});
  if(mode==='redirect')return new Response('',{status:302,headers:{Location:'https://example.invalid'}});
  if(mode==='offline')throw new TypeError('Failed to fetch');
  const nonce=options.headers['X-Shengjian-Challenge'];let value={...identity,ok:true,proof:createHmac('sha256',runtime.key).update(`shengjian-local-v1\n${nonce}\n${identity.instance_id}\n${identity.pid}\n${identity.port}`).digest('hex')};
  if(mode==='copy')value.proof='0'.repeat(64);
  if(mode==='replay'){if(replay)value=replay;else replay=value;}
  if(mode==='wrong-pid')value.pid++;
  return new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json'}});
 }
 if(mode==='post-drop')throw new TypeError('connection ended');
 return new Response(JSON.stringify({ok:true}),{headers:{'Content-Type':'application/json','X-Shengjian-Instance':mode==='wrong-response'?'f'.repeat(32):identity.instance_id}});
};
(async()=>{try{
 for(const invalid of ['html','redirect','offline','copy','wrong-pid']){
  mode=invalid;calls=[];await assert.rejects(()=>requestLocal(runtime,'/desktop/account/login',{password:'test-only'}));assert.equal(calls.length,1,'no credential or action request before valid identity');
 }
 mode='valid';calls=[];await requestLocal(runtime,'/desktop/state');assert.equal(calls.length,2);assert.equal(calls[1].options.headers['X-Shengjian-Instance'],identity.instance_id);
 mode='replay';calls=[];await requestLocal(runtime,'/desktop/state');await assert.rejects(()=>requestLocal(runtime,'/desktop/state'));assert.equal(calls.length,3,'a captured challenge proof is not reusable');
 mode='wrong-response';await assert.rejects(()=>requestLocal(runtime,'/desktop/state'));
 mode='post-drop';calls=[];await assert.rejects(()=>requestLocal(runtime,'/desktop/account/login',{password:'test-only'}));assert.equal(calls.filter(c=>c.options.method==='POST').length,1,'never replay an uncertain action');
 console.log('Desktop service identity: foreign HTML, redirects, offline, copied PID/instance, stale nonce and result rejection; no credentials before verification, no POST replay passed');
}finally{global.fetch=original;}})().catch(e=>{console.error(e);process.exitCode=1;});
