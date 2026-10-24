import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/applicationCharts.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {localToday,chartRange,chartRangeError,applicationStatusChange,applicationInChartStage,applicationChartSummary,bucketLabel,filteredApplications,applicationDeletionPrompt}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('past year includes a whole trailing year and handles leap day',()=>{assert.deepEqual(chartRange('year','2026-10-22'),{start:'2025-10-23',end:'2026-10-22'});assert.deepEqual(chartRange('year','2024-02-29'),{start:'2023-03-01',end:'2024-02-29'});assert.equal(chartRangeError('2024-01-01','2024-12-31'),'');});
test('shorter presets and month-end clamping stay inclusive',()=>{assert.equal(chartRange('2w','2026-10-22').start,'2026-10-09');assert.equal(chartRange('1m','2026-10-22').start,'2026-09-23');assert.equal(chartRange('3m','2026-10-22').start,'2026-07-23');assert.equal(chartRange('6m','2026-08-31').start,'2026-03-01');});
test('custom dates reject missing invalid reversed and over-year ranges',()=>{for(const [start,end] of [['','2026-01-01'],['2026-02-30','2026-03-01'],['2026-10-22','2026-10-21'],['2025-01-01','2026-12-31']])assert.ok(chartRangeError(start,end));});
test('today uses local calendar components rather than UTC conversion',()=>{assert.equal(localToday(new Date(2026,9,22,23,59)),'2026-10-22');});
test('marking Applied visibly seeds today and preserves existing historical dates',()=>{const data={status:'preparing',applied_date:'',notes:'Keep this'};assert.equal(applicationStatusChange(data,'applied','2026-10-22').applied_date,'2026-10-22');assert.equal(data.applied_date,'');assert.equal(applicationStatusChange({...data,applied_date:'2026-09-12'},'applied','2026-10-22').applied_date,'2026-09-12');assert.equal(applicationStatusChange({...data,status:'applied'},'interviewing','2026-10-22').applied_date,'');});
test('Preparing stays available and chart stage selection is a precise cohort',()=>{const dashboard={paths:{p:['preparing'],a:['applied','waiting_applied']},added_date_ids:['p'],missing_date_ids:[]};assert.ok(applicationInChartStage({id:'p'},'',dashboard));assert.ok(applicationInChartStage({id:'p'},'preparing',dashboard));assert.ok(!applicationInChartStage({id:'a'},'preparing',dashboard));assert.ok(applicationInChartStage({id:'p'},'added',dashboard));assert.ok(!applicationInChartStage({id:'outside'},'applied',dashboard));});
test('bucket dates are labeled without local-time midnight shifts',()=>{assert.match(bucketLabel('2026-01-01','month'),/Jan.*2026/);assert.match(bucketLabel('2026-01-05','week'),/Jan.*5.*2026/);});

test('current statuses count each cohort record once rather than each journey stage',()=>{
 const records=[{id:'a',data:{status:'applied',archived:false}},{id:'b',data:{status:'preparing',archived:true}},{id:'outside',data:{status:'offer'}}];
 const dashboard={chart_dates:{a:{date:'2026-10-22'},b:{date:'2026-10-21'}},paths:{a:['applied','waiting_applied'],b:['preparing']}};
 const summary=applicationChartSummary([...records,records[0]],dashboard);
 assert.deepEqual(summary,{total:2,archived:1,statuses:{applied:1,preparing:1}});
 assert.equal(Object.values(summary.statuses).reduce((a,b)=>a+b,0),summary.total);
 assert.ok(applicationInChartStage(records[0],'current:applied',dashboard));
 assert.ok(!applicationInChartStage(records[0],'current:preparing',dashboard));
 assert.ok(applicationInChartStage(records[1],'all',dashboard));
 assert.ok(!applicationInChartStage(records[2],'all',dashboard));
});
test('current status filters differ from historical stages and exclude dates outside the cohort',()=>{
 const records=[{id:'i',data:{status:'interviewing'}},{id:'outside',data:{status:'interviewing'}}];
 const dashboard={chart_dates:{i:{date:'2026-10-10'}},paths:{i:['applied','interviewing','waiting_interviewing']}};
 assert.deepEqual(applicationChartSummary(records,dashboard),{total:1,archived:0,statuses:{interviewing:1}});
 assert.ok(applicationInChartStage(records[0],'applied',dashboard));
 assert.ok(!applicationInChartStage(records[0],'current:applied',dashboard));
 assert.ok(!applicationInChartStage(records[1],'current:interviewing',dashboard));
});
test('archive inclusion follows the server cohort without merging similar titles or mutating records',()=>{
 const records=[{id:'a',data:{company:'Same',title:'Same',status:'applied',archived:false}},{id:'b',data:{company:'Same',title:'Same',status:'preparing',archived:true}}];
 const before=JSON.stringify(records);
 assert.deepEqual(applicationChartSummary(records,{chart_dates:{a:{}}}),{total:1,archived:0,statuses:{applied:1}});
 assert.equal(applicationChartSummary(records,{chart_dates:{a:{},b:{}}}).total,2);
 assert.equal(JSON.stringify(records),before);
 assert.deepEqual(applicationChartSummary(records,null),{total:0,archived:0,statuses:{}});
});

test('every calendar preset has an inclusive local end and bounded range',()=>{
 const expected={'2w':'2026-10-09','1m':'2026-09-23','3m':'2026-07-23','6m':'2026-04-23','9m':'2026-01-23',year:'2025-10-23'};
 for(const [preset,start] of Object.entries(expected)){const range=chartRange(preset,'2026-10-22');assert.deepEqual(range,{start,end:'2026-10-22'});assert.equal(chartRangeError(range.start,range.end),'');}
 assert.equal(chartRange('1m','2024-03-31').start,'2024-03-01');
 assert.equal(chartRange('1m','2023-03-31').start,'2023-03-01');
 assert.equal(chartRange('9m','2024-11-30').start,'2024-03-01');
 assert.equal(chartRange('2w','2026-01-01').start,'2025-12-19');
});
test('list search, status and archive scope are independent of chart dates and archive inclusion',()=>{
 const records=[{id:'old',data:{company:'Engine Co',title:'Engineer',status:'applied',applied_date:'2024-01-01',archived:false}},{id:'recent',data:{company:'Data Co',title:'Analyst',status:'preparing',archived:false}},{id:'archived',data:{company:'Engine Co',title:'Old role',status:'rejected',archived:true}}];
 const before=JSON.stringify(records);
 for(const preset of ['2w','1m','3m','6m','9m','year']){chartRange(preset,'2026-10-22');assert.deepEqual(filteredApplications(records,'','','current').map(r=>r.id),['old','recent']);}
 assert.deepEqual(filteredApplications(records,'ENGINE','','all').map(r=>r.id),['old','archived']);
 assert.deepEqual(filteredApplications(records,'','applied','current').map(r=>r.id),['old']);
 assert.deepEqual(filteredApplications(records,'','','archived').map(r=>r.id),['archived']);
 assert.equal(JSON.stringify(records),before);
});
test('deletion confirmation identifies the tracker entry and retained documents',()=>{
 const prompt=applicationDeletionPrompt({data:{company:'Example Engines',title:'Cloud Engineer'}});
 assert.match(prompt,/Cloud Engineer at Example Engines/);assert.match(prompt,/permanently removes the tracker entry and its application history/);assert.match(prompt,/Saved postings, resumes and cover letters are kept/);
});
