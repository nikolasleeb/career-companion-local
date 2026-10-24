import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/applicationDetailsState.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {applicationConflicts,mergeApplicationDraft,applicationDirty,applicationSavePayload,applicationDocumentCounts,relevantResumes}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const base=()=>({title:'Analyst',status:'preparing',notes:'Saved note',resume_ids:['r1'],submitted_resume_id:'',attachments:[],history:[],interviews:[],workflow:{step:'resume',resume_id:'r1'}});
test('file refresh keeps pending status, submitted choice and notes while incorporating uploaded links',()=>{
 const saved=base(),draft={...saved,status:'applied',notes:'Unsaved contact',submitted_resume_id:'r1'},remote={...saved,resume_ids:['r1','r2'],attachments:[{kind:'document',record_id:'d2'}],workflow:{step:'resume',resume_id:'r2'}};
 const merged=mergeApplicationDraft(saved,draft,remote);assert.equal(merged.status,'applied');assert.equal(merged.notes,'Unsaved contact');assert.equal(merged.submitted_resume_id,'r1');assert.deepEqual(merged.resume_ids,['r1','r2']);assert.equal(merged.workflow.resume_id,'r2');assert.ok(applicationDirty(remote,merged));
});
test('pending attach and detach choices survive a simultaneous upload without dropping its new record',()=>{
 const saved={...base(),resume_ids:['r1','old']},draft={...saved,resume_ids:['r1','chosen'],attachments:[{kind:'cover_letter',record_id:'letter'}]},remote={...saved,resume_ids:['r1','old','uploaded'],attachments:[{kind:'document',record_id:'file'}]};
 const merged=mergeApplicationDraft(saved,draft,remote);assert.deepEqual(merged.resume_ids,['r1','uploaded','chosen']);assert.deepEqual(merged.attachments,[{kind:'document',record_id:'file'},{kind:'cover_letter',record_id:'letter'}]);assert.deepEqual(saved.resume_ids,['r1','old']);
});
test('successful save establishes a clean baseline and another note edit does not duplicate history',()=>{
 const saved=base(),first=applicationSavePayload(saved,{...saved,status:'applied'},'2026-10-24');assert.equal(first.history.length,1);assert.equal(first.history[0].date,'2026-10-24');assert.equal(applicationDirty(first,structuredClone(first)),false);
 const second=applicationSavePayload(first,{...first,notes:'Updated after save'},'2026-10-25');assert.equal(second.history.length,1);assert.equal(second.notes,'Updated after save');
});
test('cleared status date remains unknown and an unchanged status adds no event',()=>{
 const saved=base();assert.equal(applicationSavePayload(saved,{...saved,status:'applied'},'').history[0].date,'');assert.equal(applicationSavePayload(saved,{...saved,notes:'Only notes'},'2026-10-24').history.length,0);
});
test('document counts distinguish submitted source files, uploaded letters and supporting material',()=>{
 const data={resume_ids:['r'],attachments:[{kind:'document',record_id:'resume'},{kind:'document',record_id:'letter'},{kind:'document',record_id:'email'},{kind:'cover_letter',record_id:'generated'}]},documents=[{id:'resume',data:{category:'resume'}},{id:'letter',data:{category:'cover_letter'}},{id:'email',data:{category:'email'}}];
 assert.deepEqual(applicationDocumentCounts(data,documents),{resumes:1,letters:2,files:1});
});
test('other jobs stay out of the picker while legacy attached versions remain available',()=>{
 const rows=[{id:'same',data:{job_id:'job'}},{id:'wrong',data:{job_id:'elsewhere'}},{id:'legacy',data:{job_id:'elsewhere'}},{id:'historic',data:{analysis_id:'a'}}];assert.deepEqual(relevantResumes(rows,{job_id:'job',resume_ids:['legacy']},[{id:'a',data:{job_id:'job'}}]).map(r=>r.id),['same','legacy','historic']);
});

test('file refresh detects same-field conflicts instead of silently rebasing an overwrite',()=>{
 const saved=base(),draft={...saved,notes:'Local draft',submitted_resume_id:'chosen'},remote={...saved,notes:'Changed in another window',resume_ids:['r1','new'],attachments:[{kind:'document',record_id:'upload'}]};
 assert.deepEqual(applicationConflicts(saved,draft,remote),['notes']);
 assert.equal(mergeApplicationDraft(saved,draft,remote).notes,'Local draft');
 assert.deepEqual(applicationConflicts(saved,draft,{...remote,notes:'Local draft'}),[]);
 assert.deepEqual(applicationConflicts(saved,draft,{...remote,notes:saved.notes}),[]);
});
