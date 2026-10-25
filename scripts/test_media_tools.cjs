const assert=require('node:assert/strict'),path=require('node:path');
(async()=>{
 process.env.SHENGJIAN_TOOLS_MODULE=path.resolve('tools/dsh/node_modules/@deepseek-ai/dsh-tools/lib/index.js');
 process.env.SHENGJIAN_MEDIA_URL='http://fixture.invalid/assistant/media-tool';process.env.SHENGJIAN_DEVICE_TOKEN='fixture-only';
 const definitions=new Map(),sent=[];const previous=global.fetch;
 global.fetch=async(url,options)=>{sent.push(JSON.parse(options.body));return new Response(JSON.stringify({ok:true,job:{id:'a'.repeat(32),state:'queued'}}),{headers:{'Content-Type':'application/json'}});};
 try{
  const plugin=await import(require('node:url').pathToFileURL(path.resolve('server/desktop_agent/dsh_media.mjs')).href);
  plugin.apply({inject(){},tools:{register(def){definitions.set(def.name,def);}}});
  for(const tool of ['media_models','create_image','edit_image','view_conversation_image','image_job_status'])assert(definitions.has(tool));
  const prompt='保持前面讨论的纸雕风格、红色和侧光，现在把小猫改成一只狗。';
  await definitions.get('create_image').execute({prompt,model:'verified-generator'},{callId:'create-call'});
  assert.deepEqual(sent[0],{action:'generate',call_id:'create-call',prompt,model:'verified-generator'});
  await definitions.get('edit_image').execute({prompt,job_id:'a'.repeat(32)},{callId:'edit-call'});
  assert.equal(sent[1].action,'edit');assert.equal(sent[1].call_id,'edit-call');
  assert(definitions.get('create_image').description.includes('Continue talking'));
  console.log('Real Harness tool definitions: generation, editing, vision, model catalog, stable call IDs and full contextual prompts passed');
 }finally{global.fetch=previous;}
})().catch(e=>{console.error(e);process.exitCode=1;});
