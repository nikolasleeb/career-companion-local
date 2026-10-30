import {test} from 'node:test';import assert from 'node:assert/strict';import {readFileSync} from 'node:fs';import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/interviewGuideNavigation.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {interviewPage,guideTab}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('guide and setup routes round trip for five formats while coding bypasses guides',()=>{
 for(const kind of ['behavioral','case','domain','presentation','other']){
  assert.deepEqual(interviewPage(guideTab(kind)),{type:kind,setup:false});
  assert.deepEqual(interviewPage(guideTab(kind,true)),{type:kind,setup:true});
 }
 assert.deepEqual(interviewPage(guideTab('coding')),{type:'coding',setup:true});
 assert.deepEqual(interviewPage(guideTab('coding',true)),{type:'coding',setup:true});
});
test('legacy STAR sessions link to Behavioral without changing saved session identity',()=>{
 assert.equal(guideTab('star'),'behavioral');assert.equal(guideTab('star',true),'behavioral-setup');
 for(const tab of ['',undefined,'unknown','coding-setup','behavioral-setup-setup'])assert.deepEqual(interviewPage(tab),{type:'',setup:false});
});
