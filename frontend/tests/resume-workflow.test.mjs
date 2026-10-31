import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/resumeWorkflow.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {editChosen,emptyPreparation,canAutoRender,wordingChanges,resumeNeedsClarification,resumeRetryAction}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('only the exact committed wording is chosen; candidate edits need an explicit choice',()=>{
 assert.equal(editChosen(undefined,'Reworded','Reworded'),false);
 assert.equal(editChosen({action:'accept',text:'Reworded'},'Reworded','Reworded'),true);
 assert.equal(editChosen({action:'accept',text:'Reworded'},'Changed candidate','Reworded'),false);
 assert.equal(editChosen({action:'edit',text:'Custom wording'},'Custom wording','Reworded'),true);
 assert.equal(editChosen({action:'reject',text:'Reworded'},'Reworded','Reworded'),false);
});
test('empty retained preparation never auto-renders; meaningful selections and existing drafts do',()=>{
 const value={current:null,data:{workspace_request:{experience_ids:[],content:{project:[]}}}};
 assert.equal(emptyPreparation(value),true);assert.equal(canAutoRender(null,value.data.workspace_request),false);
 assert.equal(emptyPreparation({...value,current:{id:'revision'}}),false);
 assert.equal(emptyPreparation({data:{workspace_request:{experience_ids:['project'],content:{project:[]}}}}),false);
 assert.equal(emptyPreparation({data:{workspace_request:{experience_ids:[],content:{project:[0]}}}}),false);
 assert.equal(canAutoRender({id:'draft'},{experience_ids:[]}),true);
 assert.equal(canAutoRender(null,{experience_ids:['project']}),true);
});
const suggestions=[{record_id:'a',original:'Cleaned data.',proposed:'Prepared data.'},{record_id:'b',original:'Wrote reports.',proposed:'Documented findings.'}];
const catalog=[{id:'a',items:[{item_id:'a1',original:'Cleaned data.'}]},{id:'b',items:[{item_id:'b1',original:'Wrote reports.'}]}];
test('committed changes stay independent and Keep original undoes just that wording',()=>{
 const form={overrides:{},content:{a:[0],b:[0]}};
 const accepted=wordingChanges(form,{0:{action:'accept',text:'Prepared data.'},1:{action:'edit',text:'Authored reports.'}},suggestions,catalog);
 assert.deepEqual(accepted.overrides,{a1:'Prepared data.',b1:'Authored reports.'});
 const undone=wordingChanges({...form,...accepted},{0:{action:'reject',text:'Prepared data.'},1:{action:'edit',text:'Authored reports.'}},suggestions,catalog);
 assert.deepEqual(undone.overrides,{a1:'Cleaned data.',b1:'Authored reports.'});
 assert.deepEqual(form.overrides,{});
});

test('first draft starts directly when no clarification questions remain',()=>{
 assert.equal(resumeNeedsClarification(null),false);
 assert.equal(resumeNeedsClarification({data:{questions:[]}}),false);
 for(const status of ['reviewed','answered','skipped','superseded'])
  assert.equal(resumeNeedsClarification({data:{asked_questions:[{text:'Explain your contribution.',status}]}}),false);
 assert.equal(resumeNeedsClarification({data:{questions:[{text:' ',status:'open'}]}}),false);
});
test('unanswered and saved-but-unreviewed questions keep clarification visible',()=>{
 assert.equal(resumeNeedsClarification({data:{questions:[{text:'What did you build?',status:'open'}]}}),true);
 assert.equal(resumeNeedsClarification({data:{asked_questions:[{text:'What did you build?',answer:'A test pipeline.',status:'open'}]}}),true);
 assert.equal(resumeNeedsClarification({data:{asked_questions:[{text:'Earlier question',status:'superseded'},{text:'Current question',status:'open'}]}}),true);
});
test('retry retains full optimization instead of falling back to refinement',()=>{
 const fresh={mode:'custom',template:'education',decisions:[]};
 const value=resumeRetryAction({operation:'build',asTask:true,body:{refresh_linked_evidence:true,mode:'economy'}},null,fresh,{});
 assert.equal(value.body.refresh_linked_evidence,true);assert.equal(value.operation,'build');assert.equal(value.body.mode,'custom');
});
test('failed full optimization survives reload through server-owned action metadata',()=>{
 const failed={operation:'build',body:{refresh_linked_evidence:true}};
 assert.equal(resumeRetryAction(null,failed,{template:'education'},{}).body.refresh_linked_evidence,true);
 assert.equal(resumeRetryAction(null,{operation:'build',body:{refresh_linked_evidence:false}},{},{}).body.refresh_linked_evidence,false);
});
test('local builds stay local on retry and unknown actions do not default to paid builds',()=>{
 const retry=resumeRetryAction(null,{operation:'build?manual=true',body:{}},{mode:'deep'},{});
 assert.equal(retry.operation,'build?manual=true');assert.equal(retry.body.refresh_linked_evidence,false);
 assert.equal(resumeRetryAction(null,null,{},{}),null);
});
test('retry of a local render uses the current reviewed form and retains its token',()=>{
 const form={headline:'Current headline'};const retry=resumeRetryAction({operation:'render',asTask:true,body:{request_token:'same-token',resume:{}}},null,{},form);
 assert.equal(retry.body.resume,form);assert.equal(retry.body.request_token,'same-token');
});
