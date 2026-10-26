import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/connectionMonitor.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {monitorConnection}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const settle=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
function fixture(probe){
 let now=0,id=0,online=true;const timers=new Map(),states=[];
 function events(){const listeners=new Map();return {listeners,addEventListener:(e,f)=>{if(!listeners.has(e))listeners.set(e,new Set());listeners.get(e).add(f);},removeEventListener:(e,f)=>listeners.get(e)?.delete(f),emit:e=>listeners.get(e)?.forEach(f=>f())};}
 const window=events(),document={...events(),visibilityState:'visible'};
 const env={window,document,online:()=>online,setTimeout:(fn,ms)=>{timers.set(++id,{at:now+ms,fn});return id;},clearTimeout:id=>timers.delete(id)};
 const stop=monitorConnection(probe,v=>states.push(v),env);
 async function advance(ms){const end=now+ms;while(true){const next=[...timers].sort((a,b)=>a[1].at-b[1].at)[0];if(!next||next[1].at>end)break;now=next[1].at;timers.delete(next[0]);next[1].fn();await settle();}now=end;await settle();}
 return {states,window,document,stop,advance,timers,setOnline:v=>{online=v;window.emit(v?'online':'offline');}};
}
test('authenticated checks run initially and at sixty seconds without overlap',async()=>{
 let resolve,calls=0;const f=fixture(()=>{calls++;return new Promise(r=>resolve=r);});
 assert.deepEqual(f.states,['checking']);f.window.emit('focus');f.window.emit('online');assert.equal(calls,1);
 resolve();await settle();assert.equal(f.states.at(-1),'connected');await f.advance(59999);assert.equal(calls,1);await f.advance(1);assert.equal(calls,2);resolve();await settle();f.stop();assert.equal(f.timers.size,0);
});
test('session and access failures recover after successful authenticated check',async()=>{
 for(const status of [401,403]){let failure=true;const f=fixture(async()=>{if(failure)throw {status};});await settle();assert.equal(f.states.at(-1),'signin');failure=false;f.window.emit('focus');await settle();assert.equal(f.states.at(-1),'connected');f.stop();}
});
test('a five-second timeout aborts the request and reports connection loss',async()=>{
 let signal;const f=fixture(s=>{signal=s;return new Promise(()=>{});});await f.advance(4999);assert.equal(signal.aborted,false);await f.advance(1);assert.equal(signal.aborted,true);assert.equal(f.states.at(-1),'lost');f.stop();
});
test('hidden tabs pause polling and becoming visible checks again',async()=>{
 let calls=0;const f=fixture(async()=>{calls++;});await settle();f.document.visibilityState='hidden';f.document.emit('visibilitychange');await f.advance(180000);assert.equal(calls,1);f.document.visibilityState='visible';f.document.emit('visibilitychange');await settle();assert.equal(calls,2);f.stop();
});
test('offline and server failures report loss; online recovery makes a new check',async()=>{
 let fail=false,calls=0;const f=fixture(async()=>{calls++;if(fail)throw {status:503};});await settle();f.setOnline(false);assert.equal(f.states.at(-1),'lost');await f.advance(60000);assert.equal(calls,1);fail=true;f.setOnline(true);await settle();assert.equal(f.states.at(-1),'lost');fail=false;f.window.emit('focus');await settle();assert.equal(f.states.at(-1),'connected');f.stop();
});
test('unmount aborts the probe, ignores late completion and removes listeners',async()=>{
 let resolve,signal;const f=fixture(s=>{signal=s;return new Promise(r=>resolve=r);});f.stop();assert.equal(signal.aborted,true);resolve();await settle();assert.deepEqual(f.states,['checking']);assert.equal(f.timers.size,0);assert.ok([...f.window.listeners.values()].every(v=>v.size===0));
});
