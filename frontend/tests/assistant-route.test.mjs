import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/assistantRoute.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {assistantRunId,clearAssistantRoute,openAssistantRoute}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const id='a'.repeat(32),other='b'.repeat(32);
function browser(){const location={pathname:'/workspace',search:'?view=jobs',hash:'#assistant-run='+id};const history={state:{preserve:true},calls:[],replaceState(state,unused,url){this.calls.push({state,url});location.hash='';}};return {location,history};}
test('an assistant link opens once and refresh cannot redirect Profile again',async()=>{
 const b=browser();let lookups=0,opens=0;const args={...b,applications:[{id:'app'}],load:async()=>{lookups++;return {application_id:'app'};},open:()=>opens++};
 assert.equal(await openAssistantRoute(args),true);assert.equal(b.location.hash,'');assert.deepEqual(b.history.calls,[{state:{preserve:true},url:'/workspace?view=jobs'}]);
 assert.equal(await openAssistantRoute({...args,applications:[{id:'app'}]}),false);assert.equal(lookups,1);assert.equal(opens,1);
});
test('manual navigation wins over a slow assistant lookup',async()=>{
 const b=browser();let resolve;const pending=openAssistantRoute({...b,applications:[{id:'app'}],load:()=>new Promise(r=>resolve=r),open:()=>assert.fail('Late lookup redirected the page')});
 assert.equal(clearAssistantRoute(b.location,b.history),true);resolve({application_id:'app'});assert.equal(await pending,false);
});
test('a newer link or cancelled effect cannot be replaced by an old response',async()=>{
 for(const changed of ['link','effect']){const b=browser();let resolve,live=true;const pending=openAssistantRoute({...b,applications:[{id:'app'}],load:()=>new Promise(r=>resolve=r),current:()=>live,open:()=>assert.fail('Stale response opened')});if(changed==='link')b.location.hash='#assistant-run='+other;else live=false;resolve({application_id:'app'});assert.equal(await pending,false);assert.equal(b.history.calls.length,0);}
});
test('startup waits for application records without losing a valid link',async()=>{
 const b=browser(),base={...b,load:async()=>({application_id:'app'}),open:()=>{}};
 assert.equal(await openAssistantRoute({...base,applications:[]}),false);assert.equal(assistantRunId(b.location.hash),id);
 assert.equal(await openAssistantRoute({...base,applications:[{id:'app'}]}),true);
});
test('missing or unauthorized runs clear only their own link; other anchors remain',async()=>{
 const b=browser();await assert.rejects(openAssistantRoute({...b,applications:[],load:async()=>{throw Error('Not found');},open:()=>{}}),/Not found/);assert.equal(b.location.hash,'');
 b.location.hash='#education';assert.equal(clearAssistantRoute(b.location,b.history),false);assert.equal(b.location.hash,'#education');
});
