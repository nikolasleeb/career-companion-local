import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/finishedResumeState.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {finishedResume,finishedResumeWorkflow}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const uploaded={id:'upload',data:{origin:'uploaded',job_id:'job'}},generated={id:'generated',data:{origin:'generated',job_id:'job'}};
const app={id:'application',data:{job_id:'job',resume_ids:['upload','generated'],workflow:{resume_id:'upload',step:'resume',cover_letter_id:'letter',cover_skipped:false}}};
test('continue uses exact attached upload; generated, missing, detached and foreign versions are unavailable',()=>{
 assert.equal(finishedResume(app,[uploaded,generated]),uploaded);
 for(const data of [{...app.data,workflow:{resume_id:'generated'}},{...app.data,resume_ids:[]},{...app.data,job_id:'different-job'}])assert.equal(finishedResume({...app,data},[uploaded,generated]),undefined);
 assert.equal(finishedResume(app,[]),undefined);assert.equal(finishedResume(undefined,[uploaded]),undefined);
 assert.throws(()=>finishedResumeWorkflow(app,[uploaded,generated],'generated',true),/Choose an uploaded resume/);
});
test('continuing keeps a letter tied to the same upload; switching resets only the working selection',()=>{
 const before=structuredClone(app),other={id:'other',data:{origin:'uploaded',job_id:'job'}};
 assert.deepEqual(finishedResumeWorkflow(app,[uploaded],'upload',true),{step:'cover',resume_id:'upload',cover_letter_id:'letter',cover_skipped:false});
 const more={...app,data:{...app.data,resume_ids:[...app.data.resume_ids,'other']}};
 assert.deepEqual(finishedResumeWorkflow(more,[uploaded,other],'other',false),{step:'resume',resume_id:'other',cover_letter_id:'',cover_skipped:false});
 assert.deepEqual(app,before);assert.equal(more.data.resume_ids.includes('generated'),true);
});
