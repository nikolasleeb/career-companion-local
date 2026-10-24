import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/apiClient.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {ApiError,requestJSON,pollTask,comparisonTask,pendingComparison,projectTask,clearProjectTask}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const immediate=async()=>{};
const storage=()=>{const rows=new Map();return {getItem:k=>rows.get(k)||null,setItem:(k,v)=>rows.set(k,v),removeItem:k=>rows.delete(k)};};
test('network error gives a useful message without echoing fetch internals',async()=>{
 const original=globalThis.fetch;globalThis.fetch=async()=>{throw Error('Load failed PRIVATE');};
 try{await assert.rejects(()=>requestJSON('/analyses','POST',{},'csrf'),e=>e instanceof ApiError&&e.transient&&!e.message.includes('PRIVATE')&&e.message.includes('app'));}finally{globalThis.fetch=original;}
});
test('HTTP and malformed JSON errors retain status',async()=>{
 const original=globalThis.fetch;
 try{
  globalThis.fetch=async()=>new Response(JSON.stringify({detail:'Update your key in Settings.'}),{status:400});await assert.rejects(()=>requestJSON('/x'),e=>e.status===400&&e.message.includes('Settings'));
  globalThis.fetch=async()=>new Response('<html>unavailable</html>',{status:503});await assert.rejects(()=>requestJSON('/x'),e=>e.status===503&&e.transient);
  globalThis.fetch=async()=>new Response('{}',{status:401});await assert.rejects(()=>requestJSON('/x'),e=>e.status===401&&e.message.includes('session expired'));
 }finally{globalThis.fetch=original;}
});
test('polling reconnects using GET without starting a provider job',async()=>{
 const paths=[];const result=await pollTask('task',async path=>{paths.push(path);if(paths.length<3)throw new ApiError('offline');return {status:'completed',result:{id:'result'}};},immediate);
 assert.equal(result.id,'result');assert.deepEqual(paths,['/tasks/task','/tasks/task','/tasks/task']);
});
test('persistent polling failure retains comparison for explicit status check',async()=>{
 const store=storage();let posts=0;
 const call=async(path,method)=>{if(method==='POST'){posts++;return {task_id:'same-task'};}throw new ApiError('offline');};
 await assert.rejects(()=>comparisonTask('a',{job_id:'j',mode:'deep'},call,store,immediate),/may still be running/);
 assert.equal(pendingComparison('a','j',store).id,'same-task');assert.equal(pendingComparison('b','j',store),null);
 const result=await comparisonTask('a',{job_id:'j',mode:'economy'},async(path,method)=>{assert.notEqual(method,'POST');return {status:'completed',result:{id:'recovered'}};},store,immediate);
 assert.equal(result.id,'recovered');assert.equal(posts,1);assert.equal(pendingComparison('a','j',store),null);
});
test('lost POST response reuses its token and original mode',async()=>{
 const store=storage();const tokens=[];
 await assert.rejects(()=>comparisonTask('a',{job_id:'j',mode:'deep'},async(path,method,body)=>{tokens.push(body.request_token);throw new ApiError('offline');},store,immediate));
 await comparisonTask('a',{job_id:'j',mode:'economy'},async(path,method,body)=>{if(method==='POST'){tokens.push(body.request_token);assert.equal(body.mode,'deep');return {task_id:'original'};}return {status:'completed',result:{id:'saved'}};},store,immediate);
 assert.equal(tokens[0],tokens[1]);
});
test('failed and interrupted comparisons clear pending state for explicit retry',async()=>{
 for(const status of ['failed','interrupted']){
  const store=storage();await assert.rejects(()=>comparisonTask('a',{job_id:'j',mode:'deep'},async(path,method)=>method==='POST'?{task_id:'t'}:{status,error:'Your inputs are saved.'},store,immediate),/inputs are saved/);
  assert.equal(pendingComparison('a','j',store),null);
 }
});
test('polling has bounded waits and never retries authorization failures',async()=>{
 let calls=0;await assert.rejects(()=>pollTask('t',async()=>{calls++;throw new ApiError('Sign in',401);},immediate),/Sign in/);assert.equal(calls,1);
 await assert.rejects(()=>pollTask('t',async()=>({status:'running'}),immediate,2),/taking longer/);
 await assert.rejects(()=>pollTask('t',async()=>({status:'completed',result:null}),immediate),/without a readable result/);
});
test('project analysis recovers a lost start response with the same token and mode',async()=>{
 const store=storage();let first;
 await assert.rejects(()=>projectTask('a','snapshot',{mode:'deep',request_token:'first'},async(path,method,body)=>{first=body;throw new ApiError('offline');},store,immediate));
 const result=await projectTask('a','snapshot',{mode:'economy',request_token:'second'},async(path,method,body)=>{
  if(method==='POST'){assert.equal(path,'/project-snapshots/snapshot/analyze');assert.deepEqual(body,first);return {task_id:'original'};}
  assert.equal(path,'/tasks/original');return {status:'completed',result:{draft:{id:'saved'}}};
 },store,immediate);
 assert.equal(result.draft.id,'saved');assert.equal(store.getItem('next-step-project-task:a:snapshot'),null);
});
test('project navigation and reload recovery polls the original task without a new POST',async()=>{
 const store=storage();let posts=0;
 await assert.rejects(()=>projectTask('a','snapshot',{mode:'deep'},async(path,method)=>{if(method==='POST'){posts++;return {task_id:'original'};}throw new ApiError('offline');},store,immediate),/may still be running/);
 await projectTask('a','snapshot',{mode:'economy'},async(path,method)=>{assert.notEqual(method,'POST');return {status:'completed',result:{draft:{id:'saved'}}};},store,immediate);
 assert.equal(posts,1);
});
test('project task failures allow an explicit retry, with account and snapshot isolation',async()=>{
 const store=storage();
 store.setItem('next-step-project-task:b:snapshot',JSON.stringify({id:'other-account',token:'secret',mode:'deep'}));
 store.setItem('next-step-project-task:a:other',JSON.stringify({id:'other-project',token:'other',mode:'deep'}));
 await assert.rejects(()=>projectTask('a','snapshot',{mode:'economy'},async(path,method)=>method==='POST'?{task_id:'mine'}:{status:'failed',error:'Quote validation failed.'},store,immediate),/Quote validation/);
 assert.equal(store.getItem('next-step-project-task:a:snapshot'),null);assert.ok(store.getItem('next-step-project-task:b:snapshot'));assert.ok(store.getItem('next-step-project-task:a:other'));
 clearProjectTask('a','other',store);assert.equal(store.getItem('next-step-project-task:a:other'),null);assert.ok(store.getItem('next-step-project-task:b:snapshot'));
});

test('task polling reports stages and terminal state using GET only',async()=>{
 const updates=[],paths=[];let n=0;
 const value=await pollTask('original',async(path,method)=>{paths.push(path);assert.equal(method,undefined);return ++n===1?{id:'original',status:'running',progress:{label:'Writing the tailored draft'}}:{id:'original',status:'completed',result:{id:'draft'}};},immediate,10,v=>updates.push(v));
 assert.equal(value.id,'draft');assert.equal(updates.length,2);assert.equal(updates[0].progress.label,'Writing the tailored draft');assert.equal(updates[1].status,'completed');assert.ok(updates[0].checked_at);assert.deepEqual(paths,['/tasks/original','/tasks/original']);
});
test('transient disconnection reports unknown status and successful polling reconnects',async()=>{
 const updates=[];let n=0;
 await pollTask('t',async()=>{n++;if(n===2)throw new ApiError('offline');return n===1?{status:'running',progress:{label:'Checking claims'}}:{status:'completed',result:{}};},immediate,5,v=>updates.push(v));
 assert.equal(updates[1].connection_lost,true);assert.equal(updates[1].progress.label,'Checking claims');assert.equal(updates[2].connection_lost,false);
});

test('AJAX authentication failures remain actionable even when the gateway returns HTML',async()=>{
 const original=globalThis.fetch;let attempts=0;
 globalThis.fetch=async(url,options)=>{attempts++;assert.equal(options.headers['X-Requested-With'],'XMLHttpRequest');assert.equal(options.credentials,'same-origin');return new Response('<html>Sign in</html>',{status:401});};
 try{await assert.rejects(()=>requestJSON('/tasks/active'),e=>e.status===401&&!e.transient&&e.message.includes('Keep this tab open'));assert.equal(attempts,1);}finally{globalThis.fetch=original;}
});
