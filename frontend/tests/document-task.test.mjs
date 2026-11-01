import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const transpile=file=>ts.transpileModule(readFileSync(new URL(file,import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const apiURL='data:text/javascript;base64,'+Buffer.from(transpile('../src/apiClient.ts')).toString('base64');
const {ApiError}=await import(apiURL);
const source=transpile('../src/documentTask.ts').replace("'./apiClient'",JSON.stringify(apiURL));
const {documentTask}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const storage=()=>{const rows=new Map();return {getItem:k=>rows.get(k)||null,setItem:(k,v)=>rows.set(k,v),removeItem:k=>rows.delete(k),rows};};
test('lost document start is recovered by token without another paid start',async()=>{
 const saved=storage(),seen=[];let lose=true;
 const call=async(path,method,body)=>{seen.push({path,method,body});if(method==='POST'){assert(body.request_token);if(lose){lose=false;throw new ApiError('lost response');}throw Error('Duplicate POST');}if(path.startsWith('/document-models/tasks/status'))return {task_id:'existing',status:'completed'};return {status:'completed',result:{id:'revision'}};};
 const status=[];await assert.rejects(()=>documentTask('account','/resume-conversations/workspace/build',{expected_version:1},call,x=>status.push(x),saved));
 const revision=await documentTask('account','/resume-conversations/workspace/build',{expected_version:999},call,undefined,saved);
 assert.equal(revision.id,'revision');assert.equal(seen.filter(x=>x.method==='POST').length,1);assert.equal(status.at(-1).status,'unknown');assert.equal(saved.rows.size,0);
});
test('terminal cancellation clears token and never restarts generation',async()=>{
 const saved=storage(),seen=[];const call=async(path,method)=>{seen.push({path,method});return method==='POST'?{task_id:'stopped'}:{status:'cancelled'};};
 await assert.rejects(()=>documentTask('a','/cover-workspaces/w/generate',{},call,undefined,saved),e=>e.status===499);
 assert.equal(seen.filter(x=>x.method==='POST').length,1);assert.equal(saved.rows.size,0);
});
test('account and workspace storage keys isolate pending recovery',async()=>{
 const saved=storage();const call=async(path,method)=>{if(method==='POST')throw new ApiError('disconnected');throw Error('Should not read another account token');};
 for(const [account,path] of [['a','/cover-workspaces/one/generate'],['b','/cover-workspaces/one/generate'],['a','/cover-workspaces/two/generate']])await assert.rejects(()=>documentTask(account,path,{},call,undefined,saved));
 assert.equal(saved.rows.size,3);assert.equal(new Set([...saved.rows.values()].map(v=>JSON.parse(v).token)).size,3);
});
test('explicit retry after terminal failure gets a new token, uncertain recovery retains its token',async()=>{
 const saved=storage(),tokens=[];let failed=true;
 const call=async(path,method,body)=>{if(method==='POST'){tokens.push(body.request_token);return {task_id:failed?'failed':'retry'};}return failed?{status:'failed',error:'Fictional validation failure'}:{status:'completed',result:{id:'new-revision'}};};
 await assert.rejects(()=>documentTask('a','/cover-workspaces/w/generate',{request_token:'old-caller-token'},call,undefined,saved));
 failed=false;assert.equal((await documentTask('a','/cover-workspaces/w/generate',{request_token:'old-caller-token'},call,undefined,saved)).id,'new-revision');assert.notEqual(tokens[0],tokens[1]);
});
