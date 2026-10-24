const api=globalThis.browser||globalThis.chrome;
// Never fall back to durable local storage, including on older Safari builds.
const volatile={};
const storage=api.storage.session||{get:async key=>({[key]:volatile[key]}),set:async values=>Object.assign(volatile,values),remove:async keys=>{for(const key of [].concat(keys))delete volatile[key];}};
let busy=false,starting=false,connecting=false,stopRequested=false;
const extensionRoot=api.runtime.getURL('');
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function config(){return (await storage.get('connection')).connection||{};}
async function save(connection){await storage.set({connection});}
function appOrigin(raw){const url=new URL(raw);if(!((url.protocol==='http:'&&['localhost','127.0.0.1'].includes(url.hostname)))||url.username||url.password)throw Error('Use a localhost Career Companion address.');return url.origin;}
async function bounded(promise){let timer;try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('Request timed out after 15 seconds. Check your connection before resuming.')),15000);})]);}finally{clearTimeout(timer);}}
async function relay(operation,body={},runId){const c=await config();if(!c.relayTab||!c.appOrigin)throw Error('Connect to a signed-in Career Companion tab first.');
 const reply=await bounded(api.tabs.sendMessage(c.relayTab,{channel:'career-companion-relay-v1',appOrigin:c.appOrigin,accountId:c.accountId,operation,body:operation==='status'?{pairing_id:c.pairingId,secret:c.secret}:body,runId}));
 if(!reply?.ok)throw Object.assign(Error(reply?.error||'App connection lost. Keep a signed-in Career Companion tab open, then resume.'),{code:reply?.errorCode});
 if(c.accountId&&c.accountId!==reply.accountId)throw Object.assign(Error('Account switched. Pair again.'),{code:'account_changed'});
 await storage.set({lastContact:Date.now()});return reply;}
async function execute(tabId,func,args=[]){const result=await bounded(api.scripting.executeScript({target:{tabId},world:'ISOLATED',func,args}));return result[0]?.result;}
const terminal=run=>!run||['stopped','failed','ready_for_final_review'].includes(run.state);
function summary(run){if(!run)return null;return {id:run.id,account_id:run.account_id,application_id:run.application_id,state:run.state,reason:run.reason,version:run.version,pages:run.pages,writes:run.writes,questions:run.unresolved.length,documents:run.documents,expires:run.expires};}
async function rememberRun(run){await storage.set({lastRun:summary(run)});return run;}
async function receipt(run,ids=[]){await storage.set({receipt:{runId:run.id,version:run.version,baseline:run.writes,ids}});}
async function tabOrigin(id){const tab=await api.tabs.get(id);if(!tab.url)throw Error('Tab access expired. Activate again.');return new URL(tab.url).origin;}
async function signature(scan,tabId){const page=await execute(tabId,()=>location.origin+location.pathname);const raw=new TextEncoder().encode(JSON.stringify([page,scan.fields.map(f=>[f.label,f.description,f.context,f.control,f.options,f.section,f.repeat_index])]));return [...new Uint8Array(await crypto.subtle.digest('SHA-256',raw))].map(x=>x.toString(16).padStart(2,'0')).join('');}
function relayCredentials(c){return {pairing_id:c.pairingId,secret:c.secret};}
async function report(c,run,state,reason='',write_ids=[],failed_ids=[]){return rememberRun((await relay('progress',{...relayCredentials(c),expected_version:run.version,tab_id:c.employerTab,origin:c.employerOrigin,state,reason,write_ids,failed_ids},run.id)).result);}
async function drive(){
 if(busy)throw Error('This run is already active.');busy=true;await storage.remove('reviewVisited');stopRequested=false;let c=await config();let run;let pendingWrites=[];
 try{
  for(let page=0;page<20&&!stopRequested;page++){
   c=await config();if(!c.runId)break;
   run=await rememberRun((await relay('status',{},c.runId)).result);
   if(['paused','stopped','failed','ready_for_final_review'].includes(run.state))break;
   if(await tabOrigin(c.employerTab)!==c.employerOrigin)throw Error('Website origin changed. Renew activation.');
   await api.scripting.executeScript({target:{tabId:c.employerTab},world:'ISOLATED',files:['engine.js']});
   const scan=await execute(c.employerTab,()=>globalThis.CareerCompanionDOM.inspect());
   const sig=await signature(scan,c.employerTab);
   const planned=(await relay('scan',{...relayCredentials(c),...scan,signature:sig,origin:c.employerOrigin,tab_id:c.employerTab,expected_version:run.version},run.id)).result;
   run=await rememberRun(planned.run);pendingWrites=planned.writes;
   if(['paused','stopped','failed','ready_for_final_review','needs_input'].includes(run.state)&&!planned.writes.length)break;
   const failed_ids=[];
   for(const item of planned.writes){
    if(stopRequested)break;
    const latest=(await relay('status',{},run.id)).result;
    if(latest.version!==run.version||['paused','stopped','failed'].includes(latest.state))throw Error('Run paused or changed. Review Career Companion.');
    if(await tabOrigin(c.employerTab)!==c.employerOrigin)throw Error('Website origin changed. Renew activation.');
    if(stopRequested)break;
    const result=await execute(c.employerTab,(id,value)=>globalThis.CareerCompanionDOM.write(id,value),[item.id,item.value]);
    item.value='';
    // A receipt is metadata only. Count once after DOM readback, then reconcile
    // against the server version if a reply is lost or the worker restarts.
    if(result?.ok){await receipt(run,[item.id]);run=await report(c,run,'filling','',[item.id]);await receipt(run);}
    else failed_ids.push(item.id);
    item.value=''; // Private values remain transient and are never persisted in extension storage.
   }
   planned.writes.length=0;
   const state=stopRequested?'paused':failed_ids.length||run.unresolved.length?'needs_input':scan.final_review?'ready_for_final_review':'advancing';
   run=await report(c,run,state,stopRequested?'user_action':scan.final_review?'final_review':'',[],failed_ids);
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
  stopRequested=true;await storage.set({lastError:error.message||'Run stopped safely.'});
  try{if(run){const pending=(await storage.get('receipt')).receipt;await report(c,run,'paused','connection_lost',pending?.runId===run.id&&pending.version===run.version?pending.ids:[]);}}catch{}
 }finally{
  for(const item of pendingWrites)item.value='';pendingWrites.length=0;busy=false;
  try{await execute(c.employerTab,()=>globalThis.CareerCompanionDOM?.stop());}catch{}
 }
}
async function handle(message){
 if(message.action==='state'){
  const c=await config();let run=(await storage.get('lastRun')).lastRun||null;if(run?.account_id!==c.accountId)run=null;let pairing=null,protocol=0,error='';
  try{if(c.pairingId){const data=(await relay('overview')).result;protocol=data.protocol_version||1;pairing=data.pairings.find(p=>p.id===c.pairingId)||null;
   const [active]=!c.runId?await api.tabs.query({active:true,currentWindow:true}):[];
   const actual=data.runs.find(r=>r.id===c.runId)||(!c.runId?data.runs.find(r=>r.expires>Date.now()/1000&&((c.employerTab!=null&&r.pairing_id===c.pairingId&&r.tab_id===c.employerTab&&r.allowed_origin===c.employerOrigin&&!terminal(r))||(r.state==='paused'&&r.tab_id===active?.id&&r.allowed_origin===new URL(active.url).origin))):null);
   if(actual&&!c.runId)await save({...c,runId:actual.id,employerTab:actual.tab_id,employerOrigin:actual.allowed_origin});if(actual){run=summary(actual);await storage.set({lastRun:run});}
   if(!pairing||pairing.status==='revoked')throw Error('Connection expired or revoked. Reconnect this browser.');
  }}catch(e){error=e.message;if(e.code==='account_changed'){stopRequested=true;await storage.remove(['connection','lastRun','receipt','selections','reviewVisited']);await storage.set({lastError:error});return {connection:{status:'disconnected'},run:null,busy,verified:0,lastError:error,selections:null};}if(busy){stopRequested=true;await storage.set({lastError:error});}}
  const r=(await storage.get('receipt')).receipt;
  const verified=run?Math.max(run.writes,r?.runId===run.id?r.baseline+r.ids.length:0):0;
  return {connection:{appOrigin:c.appOrigin||(await storage.get('draftOrigin')).draftOrigin,pairingId:c.pairingId,code:c.code,accountId:c.accountId,employerOrigin:c.employerOrigin,status:pairing?.status||'disconnected'},protocol,run,reviewVisited:(await storage.get('reviewVisited')).reviewVisited===run?.id,busy:busy||starting,verified,lastContact:(await storage.get('lastContact')).lastContact||null,lastError:error||(await storage.get('lastError')).lastError||'',selections:(await storage.get('selections')).selections?.[c.accountId]||null};
 }
 if(message.action==='selection'){
  const c=await config();if(!c.accountId)throw Error('Connect first.');const previous=(await storage.get('selections')).selections||{};
  const selection={};for(const key of ['applicationId','resumeId','coverLetterId','fingerprint']){if(typeof message[key]!=='string'||message[key].length>1000)throw Error('Invalid selection.');selection[key]=message[key];}
  await storage.set({selections:{...previous,[c.accountId]:selection}});return {saved:true};
 }
 if(message.action==='review'){
  const c=await config();if(!c.runId)throw Error('No run to review.');
  // This fragment selects only the owned run in the existing review UI.
  const tab=await api.tabs.get(c.relayTab);if(new URL(tab.url).origin!==c.appOrigin)throw Error('Reopen Career Companion and reconnect.');
  await api.tabs.update(c.relayTab,{active:true,url:c.appOrigin+'/#assistant-run='+c.runId});if(tab.windowId!=null)await api.windows.update(tab.windowId,{focused:true});await storage.set({reviewVisited:c.runId});return {opened:true};
 }
 if(message.action==='connect'){
  if(connecting)throw Error('Connection is already being requested.');
  if(busy||starting)throw Error('Pause the current run before reconnecting.');
  const origin=appOrigin(message.origin),url=new URL(origin);connecting=true;
  try{
  await storage.set({draftOrigin:origin});
  if(message.waitForPermission){const pattern=`${url.protocol}//${url.hostname}/*`;let granted=false;for(let i=0;i<50;i++){if(await api.permissions.contains({origins:[pattern]})){granted=true;break;}await sleep(300);}if(!granted)throw Error('Permission was not granted. Reopen the popup and connect again.');}
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
  await storage.remove(['lastError','lastRun','receipt','reviewVisited']);return {code:pair.result.code};
  }catch(error){await storage.set({lastError:error.message});throw error;}finally{connecting=false;}
 }
 if(message.action==='context'){const c=await config();return (await relay('context',relayCredentials(c))).result;}
 if(message.action==='start'){
  if(busy||starting)throw Error('A run is already filling.');
  const c=await config();const [tab]=await api.tabs.query({active:true,currentWindow:true});
  if(!tab?.id||!tab.url)throw Error('Activate this extension on the employer form tab.');
  const origin=new URL(tab.url).origin;
  if(origin===c.appOrigin||!/^https:\/\//.test(origin)&&!/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin))throw Error('Open the employer form before starting.');
  starting=true;try{
  const context=(await relay('context',relayCredentials(c))).result;if(context.protocol_version!==2)throw Error('Update Career Companion and refresh its tab before starting.');
  const docs=[message.resumeId,message.coverLetterId].filter(Boolean).map(id=>[id,[...context.resumes,...context.cover_letters].find(d=>d.id===id)?.updated_at||'']);
  if(JSON.stringify([message.applicationId,...docs])!==message.fingerprint)throw Error('Document versions changed. Refresh applications and approve the versions again.');
  await save({...c,employerTab:tab.id,employerOrigin:origin});
  const run=(await relay('create',{...relayCredentials(c),protocol_version:2,document_versions:Object.fromEntries(docs),application_id:message.applicationId,resume_id:message.resumeId,cover_letter_id:message.coverLetterId||'',documents_approved:message.documentsApproved===true,tab_id:tab.id,allowed_origin:origin})).result;
  await save({...c,employerTab:tab.id,employerOrigin:origin,runId:run.id});await storage.remove('lastError');
  await rememberRun(run);await receipt(run);drive().catch(()=>{});return {run};
  }finally{starting=false;}
 }
 if(message.action==='continue'){
  if(busy||starting)throw Error('This run is already active.');starting=true;
  try{const c=await config();const [tab]=await api.tabs.query({active:true,currentWindow:true});
   if(tab?.id!==c.employerTab||await tabOrigin(c.employerTab)!==c.employerOrigin)throw Error('Return to the original employer tab and open the extension there to resume.');
   const context=(await relay('context',relayCredentials(c))).result;if(context.protocol_version!==2)throw Error('Update Career Companion and refresh its tab before resuming.');
   let run=(await relay('overview')).result.runs.find(r=>r.id===c.runId);if(terminal(run))throw Error('This run has ended. Review it on the employer site.');
   const pending=(await storage.get('receipt')).receipt;
   if(pending?.runId===run.id&&pending.ids.length&&pending.version===run.version&&run.state==='filling')run=await report(c,run,'filling','',pending.ids);
   // Recovery from an inactive worker is explicit. Never restart from popup open.
   if(!['paused','needs_input'].includes(run.state))run=(await relay('control',{action:'pause',expected_version:run.version},run.id)).result;
   run=(await relay('control',{action:'resume',protocol_version:2,expected_version:run.version,...(run.pairing_id!==c.pairingId?{activation:{...relayCredentials(c),tab_id:c.employerTab,origin:c.employerOrigin}}:{})},run.id)).result;
   await rememberRun(run);await receipt(run);await storage.remove('lastError');drive().catch(()=>{});return {started:true};
  }finally{starting=false;}
 }
 if(message.action==='reset'){
  if(busy||starting)throw Error('Pause the current run first.');const c=await config();const run=(await relay('overview')).result.runs.find(r=>r.id===c.runId);if(run&&!terminal(run))throw Error('Stop the current run in Career Companion before starting another.');
  const {runId,employerTab,employerOrigin,...connection}=c;await save(connection);await storage.remove(['lastRun','lastError','receipt','reviewVisited']);return {reset:true};
 }
 if(message.action==='pause'){
  stopRequested=true;const c=await config();try{await execute(c.employerTab,()=>globalThis.CareerCompanionDOM?.stop());}catch{}
  if(c.runId){const run=await rememberRun((await relay('status',{},c.runId)).result);if(!['paused','stopped','failed','ready_for_final_review'].includes(run.state))await relay('control',{action:'pause',expected_version:run.version},run.id);}
  return {paused:true};
 }
 if(message.action==='disconnect'){stopRequested=true;const c=await config();try{if(c.pairingId)await relay('revoke',{},c.pairingId);}catch{}await storage.remove(['connection','lastError','lastContact','lastRun','receipt','selections']);return {disconnected:true};}
 throw Error('Unsupported extension action.');
}
api.runtime.onMessage.addListener((message,sender,reply)=>{
 // Employer and app content scripts cannot invoke background operations.
 if(sender.id!==api.runtime.id||!sender.url?.startsWith(extensionRoot)||message?.channel!=='career-companion-ui-v1')return;
 handle(message).then(result=>reply({ok:true,result})).catch(error=>reply({ok:false,error:error.message||'Action failed safely.'}));return true;
});
