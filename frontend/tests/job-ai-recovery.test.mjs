import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const compile=p=>ts.transpileModule(readFileSync(new URL(p,import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const apiURL='data:text/javascript;base64,'+Buffer.from(compile('../src/apiClient.ts')).toString('base64');
const api=await import(apiURL);
const code=compile('../src/jobAIRecovery.ts').replace("'./apiClient'",JSON.stringify(apiURL));
const {paidJobAction,pendingJobAI,recoverJobAction}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const storage=()=>{const values=new Map();return {getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};};
test('a lost start response keeps only an account-scoped token and input fingerprint',async()=>{
 const data=storage(),calls=[];
 const call=async(path,method,body)=>{calls.push(body);throw new api.ApiError('offline');};
 await assert.rejects(()=>paidJobAction('a','/job-search/ai/discover',{prompt:'private typed preferences'},call,null,data));
 const first=pendingJobAI('a',data);assert.ok(first.token);assert.equal(JSON.stringify(first).includes('private typed preferences'),false);assert.equal(pendingJobAI('b',data),null);
 await assert.rejects(()=>paidJobAction('a','/job-search/ai/discover',{prompt:'private typed preferences'},call,null,data));assert.equal(calls[0].request_token,calls[1].request_token);
 await assert.rejects(()=>paidJobAction('a','/job-search/ai/discover',{prompt:'changed'},call,null,data),/unconfirmed outcome/);assert.equal(calls.length,2);
});
test('recovering an unconfirmed completed action uses GET only and clears its token',async()=>{
 const data=storage();await assert.rejects(()=>paidJobAction('a','/job-search/ai/discover',{prompt:'data roles'},async()=>{throw new api.ApiError('offline');},null,data));
 const paths=[];const result=await recoverJobAction('a',async(path,method)=>{paths.push(path);assert.equal(method,undefined);return path.includes('/actions/')?{task_id:'saved-task'}:{status:'completed',result:{id:'search-result'}};},data);
 assert.equal(result.id,'search-result');assert.equal(paths.length,2);assert.equal(pendingJobAI('a',data),null);
});
