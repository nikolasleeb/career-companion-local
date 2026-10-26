import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const transpile=file=>ts.transpileModule(readFileSync(new URL('../src/'+file,import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const url=code=>'data:text/javascript;base64,'+Buffer.from(code).toString('base64');
const apiURL=url(transpile('apiClient.ts'));
const module=await import(url(transpile('foregroundAction.ts').replace("'./apiClient'",JSON.stringify(apiURL))));
const {ApiError}=await import(apiURL);
const store=new Map();globalThis.localStorage={getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)};
test('an ambiguous paid start recovers by token without replaying POST',async()=>{
 let posts=0;const calls=[];
 const call=async(path,method)=>{calls.push([path,method]);if(method==='POST'){posts++;throw new ApiError('Connection lost',0);}if(path.startsWith('/ai-actions/'))return {task_id:'recovered-task'};return {status:'completed',result:{answer:'Saved response'}};};
 await assert.rejects(module.foregroundAction('a','ambiguous','/paid',{text:'Original question'},call));
 const token=module.pendingAction('a','ambiguous').token;
 assert.equal(module.pendingAction('b','ambiguous'),null);
 assert.deepEqual(await module.recoverAction('a','ambiguous',call),{answer:'Saved response'});
 assert.equal(posts,1);assert(calls.some(([path])=>path==='/ai-actions/'+token));assert.equal(module.pendingAction('a','ambiguous'),null);
});
test('changing input cannot silently replace an unresolved paid request',async()=>{
 let posts=0;const call=async()=>{posts++;throw new ApiError('Connection lost',0);};
 await assert.rejects(module.foregroundAction('a','changed','/paid',{text:'Original'},call));
 await assert.rejects(module.foregroundAction('a','changed','/paid',{text:'Different'},call),/previous action/);
 assert.equal(posts,1);assert(module.pendingAction('a','changed'));
});
test('an unconfirmed status lookup leaves input and token available',async()=>{
 const call=async()=>{throw new ApiError('Not confirmed',404);};
 store.set('career-foreground:a:unconfirmed',JSON.stringify({token:'saved-token',signature:'original'}));
 await assert.rejects(module.recoverAction('a','unconfirmed',call));
 assert.equal(module.pendingAction('a','unconfirmed').token,'saved-token');
});
