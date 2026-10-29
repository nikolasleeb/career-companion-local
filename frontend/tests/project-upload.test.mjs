import {test} from 'node:test';import assert from 'node:assert/strict';import {readFileSync} from 'node:fs';import ts from 'typescript';
const moduleFor=async file=>{const code=ts.transpileModule(readFileSync(new URL('../src/'+file,import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;return import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));};
const {projectUploadError}=await moduleFor('projectFlow.ts');const {requestJSON,ApiError}=await moduleFor('apiClient.ts');
test('1.28 GB ZIP is rejected before upload and total, file and count limits match the server',()=>{
 assert.match(projectUploadError([{name:'project.zip',size:1_280_000_000}]),/32 MB.*Nothing was uploaded/s);
 assert.match(projectUploadError([{name:'one.zip',size:20*1024*1024},{name:'two.zip',size:20*1024*1024}]),/32 MB/);
 assert.match(projectUploadError([{name:'large.csv',size:11*1024*1024}]),/10 MB/);
 assert.match(projectUploadError(Array.from({length:31},()=>({name:'x.py',size:1}))),/at most 30/);
 assert.equal(projectUploadError([{name:'ok.ZIP',size:32*1024*1024}]),'');assert.equal(projectUploadError([{name:'ok.csv',size:10*1024*1024}]),'');
});
class FakeXHR{
 static instances=[];upload={};headers={};status=200;statusText='OK';responseText='{"id":"preview"}';responseURL='https://workspace.example/api/project-sources/upload-preview';aborted=false;
 constructor(){FakeXHR.instances.push(this);}open(method,path){this.method=method;this.path=path;}setRequestHeader(k,v){this.headers[k]=v;}getAllResponseHeaders(){return 'Content-Type: application/json\r\n';}send(body){this.body=body;}abort(){this.aborted=true;this.onabort?.();}
}
async function mocked(fn){const xhr=globalThis.XMLHttpRequest,fetch=globalThis.fetch;FakeXHR.instances=[];globalThis.XMLHttpRequest=FakeXHR;globalThis.fetch=async()=>{throw Error('Fetch must not replay a project upload');};try{await fn();}finally{globalThis.XMLHttpRequest=xhr;globalThis.fetch=fetch;}}
test('upload sends once with CSRF and credentials, reports bytes and keeps shared JSON handling',()=>mocked(async()=>{
 const form=new FormData();form.append('files',new Blob(['fixture']),'project.zip');const transfers=[];const pending=requestJSON('/project-sources/upload-preview','POST',form,'fictional-csrf',undefined,v=>transfers.push(v));const xhr=FakeXHR.instances[0];
 assert.equal(xhr.method,'POST');assert.equal(xhr.path,'/api/project-sources/upload-preview');assert.equal(xhr.withCredentials,true);assert.equal(xhr.headers['X-CSRF-Token'],'fictional-csrf');assert.equal(xhr.headers['X-Requested-With'],'XMLHttpRequest');assert(!('Content-Type' in xhr.headers));assert.equal(xhr.body,form);
 xhr.upload.onprogress({loaded:1024,total:2048,lengthComputable:true});xhr.upload.onload();xhr.onload();assert.deepEqual(await pending,{id:'preview'});assert.deepEqual(transfers,[{loaded:1024,total:2048,sent:false},{loaded:1024,total:2048,sent:true}]);assert.equal(FakeXHR.instances.length,1);
}));
test('upload rejection, Access HTML and network failure are surfaced without retry',()=>mocked(async()=>{
 for(const [status,text,check] of [[400,'{"detail":"ZIP contents exceed the expanded limit"}',e=>e.status===400&&e.message.includes('expanded limit')],[403,'<html>Sign in</html>',e=>e.recovery==='access'],[0,'',e=>e instanceof ApiError&&e.transient]]){
  const pending=requestJSON('/project-sources/upload-preview','POST',new FormData(),'csrf');const xhr=FakeXHR.instances.at(-1);xhr.status=status;xhr.responseText=text;if(status)xhr.onload();else xhr.onerror();await assert.rejects(pending,check);
 }
 assert.equal(FakeXHR.instances.length,3);
}));
test('abort stops the free upload once, with no replay',()=>mocked(async()=>{
 const controller=new AbortController(),pending=requestJSON('/project-sources/upload-preview','POST',new FormData(),'csrf',controller.signal);controller.abort();await assert.rejects(pending,e=>e instanceof ApiError&&e.transient);assert(FakeXHR.instances[0].aborted);assert.equal(FakeXHR.instances.length,1);
}));
