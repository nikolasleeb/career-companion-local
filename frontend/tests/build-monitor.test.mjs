import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/buildMonitor.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {monitorBuild,UPDATE_INTERVAL,validBuild}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const settle=async()=>{for(let i=0;i<15;i++)await Promise.resolve();};
function fixture(probe){
 let now=0,id=0,online=true;const timers=new Map(),builds=[];
 function events(){const listeners=new Map();return {listeners,addEventListener:(e,f)=>{if(!listeners.has(e))listeners.set(e,new Set());listeners.get(e).add(f);},removeEventListener:(e,f)=>listeners.get(e)?.delete(f),emit:e=>listeners.get(e)?.forEach(f=>f())};}
 const window=events(),document={...events(),visibilityState:'visible'};
 const env={window,document,online:()=>online,now:()=>now,setTimeout:(fn,ms)=>{timers.set(++id,{at:now+ms,fn});return id;},clearTimeout:id=>timers.delete(id)};
 const stop=monitorBuild(probe,id=>builds.push(id),env);
 async function advance(ms){const end=now+ms;while(true){const next=[...timers].sort((a,b)=>a[1].at-b[1].at)[0];if(!next||next[1].at>end)break;now=next[1].at;timers.delete(next[0]);next[1].fn();await settle();}now=end;await settle();}
 return {builds,window,document,stop,advance,timers,setOnline:v=>{online=v;window.emit(v?'online':'offline');}};
}
test('checks on load then every three hours; focus does not increase frequency',async()=>{
 let calls=0;const f=fixture(async()=>{calls++;return {build_id:'a'.repeat(32)};});await settle();
 assert.equal(UPDATE_INTERVAL,10800000);assert.equal(calls,1);f.window.emit('focus');await settle();assert.equal(calls,1);
 await f.advance(UPDATE_INTERVAL-1);assert.equal(calls,1);await f.advance(1);assert.equal(calls,2);assert.equal(f.builds.length,2);f.stop();assert.equal(f.timers.size,0);
});
test('pauses hidden polling and only checks on return when due',async()=>{
 let calls=0;const f=fixture(async()=>{calls++;return {};});await settle();f.document.visibilityState='hidden';f.document.emit('visibilitychange');await f.advance(UPDATE_INTERVAL*2);assert.equal(calls,1);assert.equal(f.timers.size,0);
 f.document.visibilityState='visible';f.document.emit('visibilitychange');await settle();assert.equal(calls,2);f.stop();
});
test('auth, offline and malformed responses never announce an update',async()=>{
 for(const value of [null,{},'<html>login</html>',{build_id:'not-a-build'}]){const f=fixture(async()=>value);await settle();assert.deepEqual(f.builds,[]);f.stop();}
 for(const status of [401,403,503]){const f=fixture(async()=>{throw {status};});await settle();assert.deepEqual(f.builds,[]);f.stop();}
 assert.equal(validBuild('a'.repeat(32)),true);assert.equal(validBuild('a'.repeat(33)),false);
});
test('timeouts abort without overlapping requests and cleanup ignores late responses',async()=>{
 let calls=0,signal,resolve;const f=fixture(s=>{signal=s;calls++;return new Promise(r=>resolve=r);});f.window.emit('focus');assert.equal(calls,1);await f.advance(5000);assert.equal(signal.aborted,true);assert.deepEqual(f.builds,[]);
 await f.advance(UPDATE_INTERVAL-5000);assert.equal(calls,2);f.stop();assert.equal(signal.aborted,true);resolve({build_id:'b'.repeat(32)});await settle();assert.deepEqual(f.builds,[]);assert.equal(f.timers.size,0);assert.ok([...f.window.listeners.values()].every(v=>v.size===0));
});
test('an offline due check waits for reconnection without polling or losing cadence',async()=>{
 let calls=0;const f=fixture(async()=>{calls++;return {build_id:'a'.repeat(32)};});await settle();f.setOnline(false);await f.advance(UPDATE_INTERVAL);assert.equal(calls,1);assert.equal(f.timers.size,0);f.setOnline(true);await settle();assert.equal(calls,2);f.stop();
});
test('returning from a briefly hidden tab keeps the original three-hour schedule',async()=>{
 let calls=0;const f=fixture(async()=>{calls++;return {};});await settle();f.document.visibilityState='hidden';f.document.emit('visibilitychange');await f.advance(60000);f.document.visibilityState='visible';f.document.emit('visibilitychange');await settle();assert.equal(calls,1);await f.advance(UPDATE_INTERVAL-60000);assert.equal(calls,2);f.stop();
});
