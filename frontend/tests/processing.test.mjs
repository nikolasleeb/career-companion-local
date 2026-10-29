import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/processing.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {ProcessingStore,actionLabel,processingGroups}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
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

test('uncertain writes are separated from active work and cleared by read-only recovery',async()=>{
 const store=new ProcessingStore();let posts=0;
 for(let n=0;n<2;n++)await assert.rejects(store.request('/resume-conversations/r/messages','POST',async()=>{posts++;throw new Error('offline');}));
 const lost=store.snapshot();assert.equal(processingGroups(lost).confirmed.length,0);assert.equal(processingGroups(lost).uncertain.length,2);assert.ok(lost.every(v=>v.checked_at));
 store.disconnected();assert.deepEqual(store.snapshot().map(v=>v.checked_at),lost.map(v=>v.checked_at));
 store.update(task('real'));assert.equal(processingGroups(store.snapshot()).confirmed.length,1);
 store.reconcile([],store.serial);assert.equal(store.snapshot().length,0);assert.equal(posts,2);
});
test('a Stop POST does not create a second progress entry',async()=>{
 const store=new ProcessingStore();store.update({...task('one'),can_cancel:true});const stop=deferred();const pending=store.request('/tasks/one/cancel','POST',()=>stop.promise);
 assert.equal(store.snapshot().length,1);stop.resolve({id:'one',status:'cancelling'});await pending;
 store.update({id:'one',status:'cancelling'});assert.equal(store.snapshot().length,1);store.update({id:'one',status:'cancelled'});assert.equal(store.snapshot().length,0);assert.equal(store.failure,'');
});

test('project file preparation transitions to one confirmed AI task without another dispatch',async()=>{
 const store=new ProcessingStore(),selection=deferred();let posts=0;
 const preparing=store.request('/project-sources/source/select','POST',()=>{posts++;return selection.promise;});
 assert.equal(store.snapshot().length,1);assert.equal(store.snapshot()[0].progress.kind,'source_preparation');
 assert.equal(store.snapshot()[0].progress.label,'Preparing selected project files');
 selection.resolve({id:'snapshot'});await preparing;assert.equal(store.snapshot().length,0);
 await store.request('/project-snapshots/snapshot/analyze','POST',async()=>{posts++;return {task_id:'analysis',status:'queued'};});
 assert.equal(store.snapshot()[0].label,'Analyzing project materials');
 await store.request('/tasks/analysis','GET',async()=>({...task('analysis'),kind:'project_analysis',progress:{code:'provider',kind:'provider',label:'Waiting for AI response'}}));
 assert.equal(store.snapshot().length,1);assert.equal(store.snapshot()[0].progress.kind,'provider');
 store.reconcile(store.snapshot(),store.serial);assert.equal(posts,2);
 store.update({...task('analysis','completed')});assert.equal(store.snapshot().length,0);
});

test('project ZIP previews and combining files report local preparation before analysis',async()=>{
 const store=new ProcessingStore();
 for(const path of ['/project-sources/upload-preview','/project-sources/combine']){
  const pending=deferred();const result=store.request(path,'POST',()=>pending.promise);
  assert.equal(store.snapshot()[0].progress.kind,path.endsWith('/upload-preview')?'upload':'local');assert.match(store.snapshot()[0].progress.label,/project/i);
  pending.resolve({id:'local-source'});await result;assert.equal(store.snapshot().length,0);
 }
});

test('upload byte progress changes to waiting without resetting total time or crossing accounts',async()=>{
 const store=new ProcessingStore();store.setOwner('one');const wait=deferred();let report;
 const pending=store.request('/project-sources/upload-preview','POST',callback=>{report=callback;return wait.promise;});const started=store.snapshot()[0].progress.started_at;
 report({loaded:1024,total:2048,sent:false});assert.equal(store.snapshot()[0].progress.kind,'upload');assert.equal(store.snapshot()[0].progress.loaded_bytes,1024);
 report({loaded:2048,total:2048,sent:true});assert.equal(store.snapshot()[0].progress.kind,'upload_wait');assert.equal(store.snapshot()[0].progress.label,'Waiting for ZIP preview');assert.equal(store.snapshot()[0].progress.started_at,started);
 store.setOwner('two');report({loaded:2048,total:2048,sent:true});assert.deepEqual(store.snapshot(),[]);wait.resolve({id:'source'});await pending;assert.deepEqual(store.snapshot(),[]);
});

test('Work Styles autosaves and free estimates never flash a processing entry',async()=>{
 const store=new ProcessingStore();store.setOwner('one');let notices=0;store.subscribe(()=>{if(store.snapshot().length)notices++;});
 for(const [path,method] of [['/work-style/example/progress','PUT'],['/profile/work-preferences/summary/estimate','POST'],['/project-sources/source/estimate?mode=deep','POST']]){
  const pending=deferred(),request=store.request(path,method,()=>pending.promise);
  assert.equal(store.snapshot().length,0);pending.resolve({saved:true});await request;
 }
 assert.equal(notices,0);
});

test('A failed background Work Styles save rejects locally without inventing an AI task',async()=>{
 const store=new ProcessingStore();store.setOwner('one');store.update({...task('real-ai'),progress:{code:'provider',kind:'provider',label:'Waiting for AI response'}});
 await assert.rejects(store.request('/work-style/example/progress','PUT',async()=>{throw new Error('Offline');}));
 assert.equal(store.snapshot().length,1);assert.equal(store.snapshot()[0].id,'real-ai');assert.equal(store.snapshot()[0].connection_lost,false);
});

test('free Explorer pagination stays inline, including errors, without hiding real AI progress',async()=>{
 const store=new ProcessingStore(),page=deferred();let calls=0;
 const result=store.request('/career-explorer/explore','POST',()=>{calls++;return page.promise;});assert.deepEqual(store.snapshot(),[]);
 page.resolve({total:86,offset:24,results:[]});await result;assert.deepEqual(store.snapshot(),[]);assert.equal(calls,1);
 await assert.rejects(store.request('/career-explorer/explore','POST',async()=>{throw Error('offline');}));assert.deepEqual(store.snapshot(),[]);
 const review=deferred();const action=store.request('/career-explorer/occupations/15-1243.00/profile-review/actions','POST',()=>review.promise);assert.equal(store.snapshot().length,1);
 review.resolve({task_id:'real-review',status:'queued'});await action;assert.equal(store.snapshot()[0].id,'real-review');
});
