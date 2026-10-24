import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/processing.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {ProcessingStore,actionLabel}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const task=(id,status='running')=>({id,status,kind:'cover_letter',created_at:'2026-10-22T12:00:00Z'});
test('Review answers is visible before start response and remains visible through task completion',async()=>{
 const store=new ProcessingStore(),start=deferred();const result=store.request('/cover-workspaces/one/answers/review','POST',()=>start.promise);
 assert.equal(store.snapshot().length,1);assert.match(store.snapshot()[0].progress.label,/Reviewing cover-letter answers/);assert.equal(store.snapshot()[0].progress.kind,'request');
 start.resolve({task_id:'review',status:'queued'});await result;
 assert.equal(store.snapshot()[0].id,'review');assert.equal(store.snapshot()[0].status,'queued');
 await store.request('/tasks/review','GET',async()=>({...task('review'),progress:{code:'reviewing',label:'Reviewing answers',kind:'provider'}}));
 assert.equal(store.snapshot()[0].progress.kind,'provider');
 await store.request('/tasks/review','GET',async()=>({...task('review','completed'),result:{id:'workspace'}}));assert.equal(store.snapshot().length,0);
});
test('all foreground writes are tracked, GET polling and cached results create no duplicate action',async()=>{
 const store=new ProcessingStore();let dispatches=0;
 for(const path of ['/analyses','/project-snapshots/s/analyze','/resume-conversations/r/build','/cover-workspaces/c/questions','/cover-workspaces/c/generate','/preparation','/interviews','/jobs/search']){
  await store.request(path,'POST',async()=>{dispatches++;return {task_id:path};});
 }
 assert.equal(store.snapshot().length,8);assert.equal(dispatches,8);
 const before=store.snapshot().length;await store.request('/tasks/active','GET',async()=>[]);assert.equal(store.snapshot().length,before);
 await store.request('/jobs/search','POST',async()=>({cached:true,result:{id:'cached'}}));assert.equal(store.snapshot().length,before);
 assert.match(actionLabel('/cover-workspaces/c/render'),/locally/);assert.match(actionLabel('/cover-workspaces/c/answers'),/Saving responses/);
});
test('concurrent completion and failures do not clear another operation',async()=>{
 const store=new ProcessingStore();store.update(task('one'));store.update(task('two'));
 store.update({...task('one','failed'),error:'Fictional review failure'});
 assert.deepEqual(store.snapshot().map(v=>v.id),['two']);assert.equal(store.failure,'Fictional review failure');
 store.clearFailure();assert.equal(store.failure,'');store.update(task('two','completed'));assert.equal(store.snapshot().length,0);
});
test('recovery merges active server metadata without removing a just-started task from an older response',()=>{
 const store=new ProcessingStore(),before=store.serial;store.update(task('started-later'));
 store.reconcile([],before);assert.equal(store.snapshot().length,1);
 store.reconcile([task('recovered')],store.serial);assert.deepEqual(store.snapshot().map(v=>v.id),['recovered']);
 store.disconnected();assert.equal(store.snapshot()[0].connection_lost,true);
 store.reconcile([task('recovered')],store.serial);assert.equal(store.snapshot()[0].connection_lost,false);
 store.reconcile([],store.serial);assert.equal(store.snapshot().length,0);
});
test('lost start response remains unknown until GET recovery; no dispatch is repeated',async()=>{
 const store=new ProcessingStore();let count=0;
 await assert.rejects(store.request('/cover-workspaces/c/message','POST',async()=>{count++;throw new Error('connection lost');}));
 assert.equal(store.snapshot()[0].status,'unknown');assert.equal(count,1);
 store.reconcile([task('server-accepted')],store.serial);assert.deepEqual(store.snapshot().map(v=>v.id),['server-accepted']);assert.equal(count,1);
});
test('rejected requests clear sending state and owner changes ignore old completions',async()=>{
 const store=new ProcessingStore();await assert.rejects(store.request('/cover-workspaces/c/message','POST',async()=>{throw Object.assign(new Error('conflict'),{status:409});}));assert.equal(store.snapshot().length,0);
 store.setOwner('one');const d=deferred(),request=store.request('/analyses','POST',()=>d.promise);store.setOwner('two');d.resolve({task_id:'private-old-task'});await request;assert.equal(store.snapshot().length,0);
});
