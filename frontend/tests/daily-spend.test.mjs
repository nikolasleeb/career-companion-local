import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/dailySpendData.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {spendLabel,spendDescription}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('unknown and partial recorded estimates do not masquerade as zero',()=>{
 assert.equal(spendLabel({estimated_cost_usd:null}),'Today —');
 assert.equal(spendLabel({estimated_cost_usd:0}),'Today ~$0.00');
 assert.equal(spendLabel({estimated_cost_usd:1.236,partial:true}),'Today ~$1.24+');
 const description=spendDescription({date:'2026-10-29',timezone:'America/Phoenix',percent:100,warning_limit_usd:5,warning_state:'limit',partial:true,unpriced_requests:1,pending_requests:2});
 assert.match(description,/100%/);assert.match(description,/requests remain available/);assert.match(description,/Partial estimate/);assert.match(description,/2 requests awaiting/);
});
