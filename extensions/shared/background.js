const api=globalThis.browser||globalThis.chrome;
const storage=api.storage.session||api.storage.local;
let busy=false,stopRequested=false;
const extensionRoot=api.runtime.getURL('');
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function config(){return (await storage.get('connection')).connection||{};}
async function save(connection){await storage.set({connection});}
function appOrigin(raw){const url=new URL(raw);if(!((url.protocol==='http:'&&['localhost','127.0.0.1'].includes(url.hostname)))||url.username||url.password)throw Error('Use localhost or 127.0.0.1.');return url.origin;}
async function relay(operation,body={},runId){const c=await config();if(!c.relayTab||!c.appOrigin)throw Error('Connect to a signed-in Career Companion tab first.');
 const reply=await api.tabs.sendMessage(c.relayTab,{channel:'career-companion-relay-v1',appOrigin:c.appOrigin,accountId:c.accountId,operation,body:operation==='status'?{pairing_id:c.pairingId,secret:c.secret}:body,runId});
 if(!reply?.ok)throw Error(reply?.error||'App connection lost. Reconnect in Career Companion.');
 if(c.accountId&&c.accountId!==reply.accountId)throw Error('Account switched. Pair again.');return reply;}
async function execute(tabId,func,args=[]){const result=await api.scripting.executeScript({target:{tabId},world:'ISOLATED',func,args});return result[0]?.result;}
async function tabOrigin(id){const tab=await api.tabs.get(id);if(!tab.url)throw Error('Tab access expired. Activate again.');return new URL(tab.url).origin;}
async function signature(scan,tabId){const page=await execute(tabId,()=>location.origin+location.pathname);const raw=new TextEncoder().encode(JSON.stringify([page,scan.fields.map(f=>[f.label,f.description,f.context,f.control,f.options,f.section,f.repeat_index])]));return [...new Uint8Array(await crypto.subtle.digest('SHA-256',raw))].map(x=>x.toString(16).padStart(2,'0')).join('');}
function relayCredentials(c){return {pairing_id:c.pairingId,secret:c.secret};}
async function report(c,run,state,reason='',write_ids=[],failed_ids=[]){return (await relay('progress',{...relayCredentials(c),expected_version:run.version,tab_id:c.employerTab,origin:c.employerOrigin,state,reason,write_ids,failed_ids},run.id)).result;}
async function drive(){
 if(busy)throw Error('This run is already active.');busy=true;stopRequested=false;let c=await config();let run;let pendingWrites=[];
 try{
  for(let page=0;page<20&&!stopRequested;page++){
   c=await config();if(!c.runId)break;
   run=(await relay('status',{},c.runId)).result;
   if(['paused','stopped','failed','ready_for_final_review'].includes(run.state))break;
   if(await tabOrigin(c.employerTab)!==c.employerOrigin)throw Error('Website origin changed. Renew activation.');
   await api.scripting.executeScript({target:{tabId:c.employerTab},world:'ISOLATED',files:['engine.js']});
   const scan=await execute(c.employerTab,()=>globalThis.CareerCompanionDOM.inspect());
   const sig=await signature(scan,c.employerTab);
   const planned=(await relay('scan',{...relayCredentials(c),...scan,signature:sig,origin:c.employerOrigin,tab_id:c.employerTab,expected_version:run.version},run.id)).result;
   run=planned.run;pendingWrites=planned.writes;
   if(['paused','stopped','failed','ready_for_final_review','needs_input'].includes(run.state)&&!planned.writes.length)break;
   const write_ids=[],failed_ids=[];
   for(const item of planned.writes){
    if(stopRequested)break;
    const latest=(await relay('status',{},run.id)).result;
    if(latest.version!==run.version||['paused','stopped','failed'].includes(latest.state))throw Error('Run paused or changed. Review Career Companion.');
    if(await tabOrigin(c.employerTab)!==c.employerOrigin)throw Error('Website origin changed. Renew activation.');
    const result=await execute(c.employerTab,(id,value)=>globalThis.CareerCompanionDOM.write(id,value),[item.id,item.value]);
    (result?.ok?write_ids:failed_ids).push(item.id);
    item.value=''; // Private values remain transient and are never persisted in extension storage.
   }
   planned.writes.length=0;
   const state=stopRequested?'paused':failed_ids.length||run.unresolved.length?'needs_input':scan.final_review?'ready_for_final_review':'advancing';
   run=await report(c,run,state,stopRequested?'user_action':scan.final_review?'final_review':'',write_ids,failed_ids);
   if(state!=='advancing')break;
   const latest=(await relay('status',{},run.id)).result;
   if(latest.version!==run.version||latest.state!=='advancing')break;
   const next=await execute(c.employerTab,()=>globalThis.CareerCompanionDOM.next());
   if(!next?.ok){run=await report(c,run,'needs_input',next?.reason==='validation'?'validation':'manual_handoff');break;}
   let changed=false;
   for(let attempt=0;attempt<20;attempt++){
    await sleep(300);if(stopRequested)break;
    if(await tabOrigin(c.employerTab)!==c.employerOrigin)throw Error('Website origin changed. Renew activation.');
    try{
     await api.scripting.executeScript({target:{tabId:c.employerTab},world:'ISOLATED',files:['engine.js']});
     const current=await execute(c.employerTab,()=>globalThis.CareerCompanionDOM.inspect());
     if(await signature(current,c.employerTab)!==sig){changed=true;break;}
    }catch(error){if(attempt===19)throw error;}
   }
   if(!changed){run=await report(c,run,'paused','stalled_navigation');break;}
  }
 }catch(error){
  // A lost relay/login/revocation never triggers more writes, retries or privileged fallback.
  await storage.set({lastError:error.message||'Run stopped safely.'});
  try{if(run&&!stopRequested)await report(c,run,'paused','connection_lost');}catch{}
 }finally{
  for(const item of pendingWrites)item.value='';pendingWrites.length=0;busy=false;
  try{await execute(c.employerTab,()=>globalThis.CareerCompanionDOM?.stop());}catch{}
 }
}
async function handle(message){
 if(message.action==='state'){const c=await config();let run=null;try{if(c.runId)run=(await relay('status',{},c.runId)).result;}catch{}return {connection:{appOrigin:c.appOrigin,pairingId:c.pairingId,code:c.code,accountId:c.accountId,employerOrigin:c.employerOrigin},run,busy,lastError:(await storage.get('lastError')).lastError||''};}
 if(message.action==='connect'){
  if(busy)throw Error('Pause the current run before reconnecting.');
  const origin=appOrigin(message.origin),url=new URL(origin);
  // Browser match patterns select a host, not a port. Never pick another
  // localhost service just because it matches the same host permission.
  const tabs=await api.tabs.query({url:`${url.protocol}//${url.hostname}/*`});
  const target=tabs.find(tab=>{
   if(tab.incognito||!tab.url)return false;
   try{return new URL(tab.url).origin===origin;}catch{return false;}
  });
  if(!target?.id)throw Error('Open and sign in to Career Companion in this browser first.');
  await api.scripting.executeScript({target:{tabId:target.id},world:'ISOLATED',files:['relay.js']});
  const secret=[...crypto.getRandomValues(new Uint8Array(32))].map(x=>x.toString(16).padStart(2,'0')).join('');
  const label=api.runtime.getURL('').startsWith('safari-web-extension:')?'Safari on this computer':'Chrome on this computer';
  await save({appOrigin:origin,relayTab:target.id,secret});
  const pair=await relay('pair',{secret,label});
  await save({appOrigin:origin,relayTab:target.id,secret,pairingId:pair.result.id,code:pair.result.code,accountId:pair.accountId});
  await storage.remove('lastError');return {code:pair.result.code};
 }
 if(message.action==='context'){const c=await config();return (await relay('context',relayCredentials(c))).result;}
 if(message.action==='start'){
  if(busy)throw Error('A run is already filling.');
  const c=await config();const [tab]=await api.tabs.query({active:true,currentWindow:true});
  if(!tab?.id||!tab.url)throw Error('Activate this extension on the employer form tab.');
  const origin=new URL(tab.url).origin;
  if(origin===c.appOrigin||!/^https:\/\//.test(origin)&&!/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin))throw Error('Open the employer form before starting.');
  const run=(await relay('create',{...relayCredentials(c),application_id:message.applicationId,resume_id:message.resumeId,cover_letter_id:message.coverLetterId||'',documents_approved:message.documentsApproved===true,tab_id:tab.id,allowed_origin:origin})).result;
  await save({...c,employerTab:tab.id,employerOrigin:origin,runId:run.id});await storage.remove('lastError');
  drive().catch(()=>{});return {run};
 }
 if(message.action==='continue'){
  const c=await config();if(await tabOrigin(c.employerTab)!==c.employerOrigin)throw Error('Website changed. Stop and start a new activation.');
  drive().catch(()=>{});return {started:true};
 }
 if(message.action==='pause'){
  stopRequested=true;const c=await config();try{await execute(c.employerTab,()=>globalThis.CareerCompanionDOM?.stop());}catch{}
  if(c.runId){const run=(await relay('status',{},c.runId)).result;if(!['paused','stopped','failed','ready_for_final_review'].includes(run.state))await relay('control',{action:'pause',expected_version:run.version},run.id);}
  return {paused:true};
 }
 if(message.action==='disconnect'){stopRequested=true;const c=await config();try{if(c.pairingId)await relay('revoke',{},c.pairingId);}catch{}await storage.remove(['connection','lastError']);return {disconnected:true};}
 throw Error('Unsupported extension action.');
}
api.runtime.onMessage.addListener((message,sender,reply)=>{
 // Employer and app content scripts cannot invoke background operations.
 if(sender.id!==api.runtime.id||!sender.url?.startsWith(extensionRoot)||message?.channel!=='career-companion-ui-v1')return;
 handle(message).then(result=>reply({ok:true,result})).catch(error=>reply({ok:false,error:error.message||'Action failed safely.'}));return true;
});
