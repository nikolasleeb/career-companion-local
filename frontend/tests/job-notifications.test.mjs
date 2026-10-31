import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import ts from 'typescript';
const source=ts.transpileModule(readFileSync(new URL('../src/jobNotifications.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {retireJobNotifications}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
test('retirement removes only the job-alert worker without permission or provider calls',async()=>{
 const removed=[],unsubscribed=[];
 const worker=(name,script)=>({active:{scriptURL:'https://example.org/'+script},pushManager:{getSubscription:async()=>({unsubscribe:async()=>unsubscribed.push(name)})},unregister:async()=>removed.push(name)});
 await retireJobNotifications({getRegistrations:async()=>[worker('job','job-notifications.js'),worker('other','another-worker.js')]});
 assert.deepEqual(removed,['job']);assert.deepEqual(unsubscribed,['job']);
});
test('unsupported browsers and inaccessible registrations do not break search',async()=>{
 await retireJobNotifications({getRegistrations:async()=>{throw Error('blocked');}});
 await retireJobNotifications({getRegistrations:async()=>[]});
});
test('retired worker ignores queued pushes and unregisters on activation',async()=>{
 const listeners={};let removed=0,unsubscribed=0;
 runInNewContext(readFileSync(new URL('../public/job-notifications.js',import.meta.url),'utf8'),{self:{addEventListener:(event,fn)=>listeners[event]=fn,skipWaiting:async()=>{},registration:{pushManager:{getSubscription:async()=>({unsubscribe:async()=>unsubscribed++})},unregister:async()=>removed++}}});
 listeners.push({data:{json:()=>({body:'must not display'})}});
 await new Promise((resolve,reject)=>listeners.activate({waitUntil:p=>p.then(resolve,reject)}));
 assert.equal(removed,1);assert.equal(unsubscribed,1);
});

test('failed subscription cleanup still unregisters the retired worker',async()=>{
 let removed=0;await retireJobNotifications({getRegistrations:async()=>[{active:{scriptURL:'https://example.org/job-notifications.js'},pushManager:{getSubscription:async()=>{throw Error('revoked');}},unregister:async()=>removed++}]});assert.equal(removed,1);
});
