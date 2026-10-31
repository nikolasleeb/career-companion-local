import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/comparisonEvidence.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {comparisonEvidenceText}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('private eligibility evidence has readable labels without reversing sponsorship answers',()=>{
 for(const [field,label] of Object.entries({us_citizen:'U.S. citizen',authorized_us:'Authorized to work in the U.S.',sponsorship_now:'Employer sponsorship required now',sponsorship_future:'Employer sponsorship required in the future'})){
  for(const [answer,display] of Object.entries({yes:'Yes',no:'No',unsure:'Unsure'})){
   const evidence=Object.freeze({record_id:'profile:'+field,quote:field+' = '+answer});
   assert.equal(comparisonEvidenceText(evidence),label+': '+display);
   assert.equal(evidence.quote,field+' = '+answer);
  }
 }
});
test('historical answer-only quotes use the field identity and tolerate whitespace and case',()=>{
 assert.equal(comparisonEvidenceText({record_id:'profile:authorized_us',quote:' Yes '}),'Authorized to work in the U.S.: Yes');
 assert.equal(comparisonEvidenceText({record_id:'profile:us_citizen',quote:' US_CITIZEN = YES '}),'U.S. citizen: Yes');
});
test('ordinary evidence, unknown answers and mismatched private fields stay literal',()=>{
 for(const evidence of [
  {record_id:'project-1',quote:'us_citizen = yes'},
  {record_id:'profile:unknown',quote:'yes'},
  {record_id:'profile:us_citizen',quote:'us_citizen = unknown'},
  {record_id:'profile:us_citizen',quote:'authorized_us = yes'},
  {record_id:'profile:us_citizen',quote:'yes; sponsorship_now = no'},
  {record_id:'profile:us_citizen',quote:'<b>yes</b>'},
 ])assert.equal(comparisonEvidenceText(evidence),evidence.quote);
});
