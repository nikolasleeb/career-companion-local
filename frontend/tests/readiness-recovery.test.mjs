import {test,beforeEach} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const compile=p=>ts.transpileModule(readFileSync(new URL(p,import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const apiURL='data:text/javascript;base64,'+Buffer.from(compile('../src/apiClient.ts')).toString('base64');
const api=await import(apiURL);
const source=compile('../src/readinessState.ts').replace("'./apiClient'",JSON.stringify(apiURL));
const readiness=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const storage=()=>{const values=new Map();return {getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};};
beforeEach(()=>{globalThis.localStorage=storage();globalThis.sessionStorage=storage();});

test('an unconfirmed readiness start blocks further POSTs and stores no prompt',async()=>{
 const calls=[];
 await assert.rejects(()=>readiness.readinessAction('a','one',{operation:'discover',message:'Private unsent context'},async(...args)=>{calls.push(args);throw new api.ApiError('offline');}));
 const saved=readiness.pendingReadiness('a','one');assert.ok(saved.token);assert.deepEqual(Object.keys(saved),['token']);
 await assert.rejects(()=>readiness.readinessAction('a','one',{operation:'assess'},async()=>assert.fail('Duplicate dispatch')),/saved status/);
 assert.equal(calls.length,1);
});

test('readiness recovery only reads saved status and clears completed references',async()=>{
 await assert.rejects(()=>readiness.readinessAction('a','one',{operation:'discover'},async()=>{throw new api.ApiError('offline');}));
 const calls=[];
 const value=await readiness.recoverReadiness('a','one',async(path,method)=>{assert.equal(method,undefined);calls.push(path);return path.includes('/actions/')?{task_id:'saved-task'}:{status:'completed',result:{report_id:'saved-report'}};});
 assert.equal(value.report_id,'saved-report');assert.equal(calls.length,2);assert.equal(readiness.pendingReadiness('a','one'),null);
});

test('expired access retains readiness recovery instead of replaying it',async()=>{
 await assert.rejects(()=>readiness.readinessAction('a','one',{operation:'assess'},async()=>{throw new api.ApiError('expired',401);}));
 assert.ok(readiness.pendingReadiness('a','one'));
 await assert.rejects(()=>readiness.recoverReadiness('a','one',async()=>{throw new api.ApiError('expired',403);}));
 assert.ok(readiness.pendingReadiness('a','one'));
});

test('readiness drafts and request references are scoped to account and session',()=>{
 sessionStorage.setItem(readiness.readinessDraftKey('a','one'),JSON.stringify({objective:'One direction'}));
 sessionStorage.setItem(readiness.readinessDraftKey('b','one'),JSON.stringify({objective:'Other account'}));
 assert.equal(readiness.readReadinessDraft('a','one',{}).objective,'One direction');
 assert.equal(readiness.readReadinessDraft('b','one',{}).objective,'Other account');
 assert.deepEqual(readiness.readReadinessDraft('a','two',{}),{});
 assert.equal(readiness.pendingReadiness('b','one'),null);
});
