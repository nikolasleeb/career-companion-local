import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const source=ts.transpileModule(readFileSync(new URL('../src/jobNotifications.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {enrollBrowser}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const key=Buffer.alloc(65,1).toString('base64url');
test('denied permission performs no enrollment or provider request',async()=>{
 let calls=0;await assert.rejects(()=>enrollBrowser(async()=>{calls++;},{notification:{requestPermission:async()=>'denied'},serviceWorker:{},pushSupported:true}),/not enabled/);assert.equal(calls,0);
});
test('reopening enrollment reuses an existing device subscription',async()=>{
 const calls=[],sub={toJSON:()=>({endpoint:'fictional-endpoint'})};let subscribed=0;
 const worker={pushManager:{getSubscription:async()=>sub,subscribe:async()=>{subscribed++;return sub;}}};
 await enrollBrowser(async(path,method,body)=>{calls.push([path,method,body]);return {public_key:key};},{notification:{requestPermission:async()=>'granted'},serviceWorker:{register:async()=>{},ready:Promise.resolve(worker)},pushSupported:true});
 assert.equal(subscribed,0);assert.deepEqual(calls[1],['/job-search/push','POST',{endpoint:'fictional-endpoint'}]);
});
test('failed account enrollment rolls back a newly created browser subscription',async()=>{
 let removed=0;const worker={pushManager:{getSubscription:async()=>null,subscribe:async()=>({toJSON:()=>({}),unsubscribe:async()=>{removed++;}})}};
 await assert.rejects(()=>enrollBrowser(async path=>{if(path.endsWith('push-key'))return {public_key:key};throw new Error('Connection lost');},{notification:{requestPermission:async()=>'granted'},serviceWorker:{register:async()=>{},ready:Promise.resolve(worker)},pushSupported:true}),/Connection lost/);assert.equal(removed,1);
});
