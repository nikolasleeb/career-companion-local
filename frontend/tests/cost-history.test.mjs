import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/costHistoryData.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {costRange,costQuery,dollars,costAmount}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('costs distinguish historical ranges, partial subtotals and fully unknown requests',()=>{
 assert.equal(costAmount({estimated_cost_usd:.04,estimated_cost_upper_usd:.05}),'$0.0400–$0.0500');
 assert.equal(costAmount({estimated_cost_usd:.04,partial:true}),'At least $0.0400');
 assert.equal(costAmount({estimated_cost_usd:null,unpriced_requests:2}),'Unpriced');
 assert.equal(costAmount({estimated_cost_usd:0}),'$0.0000');
});
test('inclusive cost ranges use calendar days across months, leap years and DST',()=>{
 assert.deepEqual(costRange(30,new Date(2026,9,21)),{start:'2026-09-22',end:'2026-10-21'});
 assert.deepEqual(costRange(7,new Date(2024,2,3)),{start:'2024-02-26',end:'2024-03-03'});
 assert.deepEqual(costRange(7,new Date(2026,2,10)),{start:'2026-03-04',end:'2026-03-10'});
});
test('filter query preserves model and timezone and exports all matching pages',()=>{
 const filter={start:'2026-10-01',end:'2026-10-21',model:'model+snapshot',process:'project_analysis',tz:'America/Phoenix',bucket:'day'};
 const query=new URLSearchParams(costQuery(filter,30));assert.equal(query.get('tz'),'America/Phoenix');assert.equal(query.get('model'),'model+snapshot');assert.equal(query.get('offset'),'30');assert.equal(query.get('limit'),'30');
 const exportQuery=new URLSearchParams(costQuery(filter));assert.ok(!exportQuery.has('limit'));assert.ok(!exportQuery.has('offset'));
});
test('small measured costs stay visible and unknown amounts are never rendered as free',()=>{
 assert.equal(dollars(null),'Unpriced');assert.equal(dollars(undefined),'Unpriced');assert.equal(dollars(0),'$0.0000');assert.equal(dollars(.000012),'$0.000012');assert.equal(dollars(.0436),'$0.0436');
});
