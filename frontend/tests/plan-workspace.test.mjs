import {test} from 'node:test';import assert from 'node:assert/strict';import {readFileSync} from 'node:fs';import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/planWorkspaceData.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {readPlanningDraft,planningDraftKey}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('legacy form objectives survive; optional planning drafts stay account and chat scoped',()=>{
 const store=new Map(),storage={getItem:key=>store.get(key)||null};store.set(planningDraftKey('a'),JSON.stringify({objective:'Legacy unsent plan',time_available:'2 hours'}));
 assert.equal(readPlanningDraft('a','new',{},storage).objective,'Legacy unsent plan');assert.deepEqual(readPlanningDraft('a','new',{},storage).goal_ids,[]);
 store.set(planningDraftKey('a','chat'),JSON.stringify({target:'Summer',goal_ids:['goal','goal',3]}));assert.equal(readPlanningDraft('a','chat',{},storage).target,'Summer');assert.deepEqual(readPlanningDraft('a','chat',{},storage).goal_ids,['goal']);assert.equal(readPlanningDraft('b','chat',{},storage).target,'');
 assert.equal(readPlanningDraft('a','other',{budget:'Free'},storage).budget,'Free');
});
