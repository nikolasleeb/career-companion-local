import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/taskProgress.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {elapsed,duration,progressView}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const start='2026-10-22T17:41:40Z',stage='2026-10-22T17:44:24Z';
const task={status:'running',created_at:start,progress:{code:'drafting',label:'Writing the tailored draft',kind:'provider',started_at:start,stage_started_at:stage}};
test('elapsed timers use server timestamps and separate task and stage time',()=>{
 const v=progressView(task,Date.parse('2026-10-22T17:47:09Z'));
 assert.equal(v.total,'5:29');assert.equal(v.stage,'2:45');assert.equal(v.label,'Writing the tailored draft');assert.match(v.detail,/Waiting for AI response/);
 assert.equal(duration(3601),'60:01');assert.equal(elapsed('invalid',1),0);assert.equal(elapsed(start,0),0);
});
test('local work never claims AI is thinking and legacy tasks have an honest fallback',()=>{
 assert.match(progressView({...task,progress:{...task.progress,kind:'local',label:'Rendering and inspecting the PDF'}},Date.now()).detail,/Processing locally/);
 const legacy=progressView({status:'running',created_at:start},Date.now());assert.equal(legacy.label,'Resume action running');assert.equal(legacy.stage,null);assert.match(legacy.detail,/Checking saved task status/);
});
test('unknown connection freezes both clocks at the last confirmed update',()=>{
 const v=progressView({...task,connection_lost:true,checked_at:'2026-10-22T17:45:24Z'},Date.parse('2026-10-22T17:48:40Z'));
 assert.equal(v.running,false);assert.equal(v.unknown,true);assert.equal(v.label,'Status connection lost');assert.equal(v.stage,'1:00');assert.equal(v.total,'3:44');assert.deepEqual(progressView({...task,connection_lost:true,checked_at:'2026-10-22T17:45:24Z'},Date.parse('2026-10-22T18:48:40Z')),v);assert.match(v.detail,/may still be running/);
});
test('completed and failed tasks stop clocks at server completion',()=>{
 for(const status of ['completed','failed','interrupted']){
  const v=progressView({...task,status,progress:{...task.progress,finished_at:'2026-10-22T17:48:41Z'}},Date.parse('2026-10-22T18:00:00Z'));
  assert.equal(v.running,false);assert.equal(v.total,'7:01');assert.equal(v.stage,'4:17');
 }
});
