import {test} from 'node:test';import assert from 'node:assert/strict';import {readFileSync} from 'node:fs';import ts from 'typescript';
const js=ts.transpileModule(readFileSync(new URL('../src/usageChartData.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {chartPeriods,recordedTokens,tokenMissing,tokenText,tokenTotalText,periodLabel}=await import('data:text/javascript;base64,'+Buffer.from(js).toString('base64'));
test('input/output totals do not double-count included cached input and reasoning',()=>{
 const row={key:'2026-10-23',requests:2,input_tokens:100,output_tokens:40,cached_input_tokens:25,reasoning_tokens:15,token_requests_missing:0};assert.equal(recordedTokens(row),140);assert.equal(tokenText(140,0),'140');assert.equal(tokenMissing(row),0);
});
test('no-request periods are distinct from missing and partially reported tokens',()=>{
 const rows=chartPeriods([{key:'2026-10-23',requests:1,token_requests_missing:1,estimated_cost_usd:null}],['2026-10-23','2026-10-24']);assert.equal(rows[1].requests,0);assert.equal(tokenMissing(rows[1]),0);assert.equal(rows[0].estimated_cost_usd,null);assert.equal(tokenTotalText(rows[0]),'Token counts not reported');assert.equal(tokenText(1200,1),'At least 1,200');assert.equal(rows.length,2);
});
test('weekly and monthly labels describe clipped periods without timezone shifts',()=>{
 assert.equal(periodLabel('2026-10-19','week','2026-10-21','2026-10-27'),'Oct 21, 2026 – Oct 25, 2026');assert.equal(periodLabel('2026-10','month','','2026-10-27'),'Oct 1, 2026 – Oct 27, 2026');assert.equal(periodLabel('2026-10-23','day'),'Oct 23, 2026');
});
