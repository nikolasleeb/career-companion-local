import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
async function module(path){const js=ts.transpileModule(readFileSync(new URL(path,import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;return import('data:text/javascript;base64,'+Buffer.from(js).toString('base64'));}
const {costTicks}=await module('../src/costChartTicks.ts'),{encodeWav,audioActionKey}=await module('../src/interviewAudioData.ts');
test('dates label all sparse bars, thin dense charts and preserve endpoints on resize',()=>{
 const rows=Array.from({length:30},(_,i)=>({key:'2026-10-'+String(i+1).padStart(2,'0')}));
 const desktop=costTicks(rows,'day',900),mobile=costTicks(rows,'day',240);
 assert.equal(desktop.ticks[0].index,0);assert.equal(desktop.ticks.at(-1).index,29);assert.ok(mobile.ticks.length<desktop.ticks.length);
 for(const ticks of [desktop.ticks,mobile.ticks])for(let i=1;i<ticks.length;i++)assert.ok(ticks[i].x-ticks[i-1].x>=70);
 const sparse=costTicks([rows[0],rows[10],rows[29]],'day',900);assert.ok(sparse.ticks.length>3);assert.ok(sparse.ticks.some(v=>!['2026-10-01','2026-10-11','2026-10-30'].includes(v.key)));
 assert.ok(costTicks([{key:'2026-12-28'},{key:'2027-01-04'}],'week',900).ticks.every(v=>v.label.startsWith('Wk ')));
});
test('recording encoder produces bounded mono PCM WAV and clamps samples',async()=>{
 const samples=new Float32Array(24000);samples[0]=2;samples[1]=-2;const blob=encodeWav(samples),view=new DataView(await blob.arrayBuffer());
 assert.equal(blob.type,'audio/wav');assert.equal(blob.size,48044);assert.equal(view.getUint16(22,true),1);assert.equal(view.getUint32(24,true),24000);assert.equal(view.getInt16(44,true),32767);assert.equal(view.getInt16(46,true),-32768);
 assert.throws(()=>encodeWav(new Float32Array(100)));assert.throws(()=>encodeWav(new Float32Array(24000*301)));
 assert.notEqual(audioActionKey('a','s','q'),audioActionKey('b','s','q'));
});

test('calendar labels include unused days and the whole selected window without inventing costs',()=>{
 const rows=[{key:'2026-10-23'},{key:'2026-10-25'},{key:'2026-10-27'}];
 const calendar=costTicks(rows,'day',900);assert.deepEqual(calendar.ticks.map(v=>v.key),['2026-10-23','2026-10-24','2026-10-25','2026-10-26','2026-10-27']);
 const range=costTicks(rows,'day',900,'2026-09-28','2026-10-27');assert.equal(range.ticks[0].key,'2026-09-28');assert.equal(range.ticks.at(-1).key,'2026-10-27');assert.equal(range.times.length,3);
 const empty=costTicks([],'day',900,'2026-10-23','2026-10-27');assert.equal(empty.ticks.length,5);assert.equal(empty.times.length,0);
 const week=costTicks([{key:'2026-10-12'},{key:'2026-10-26'}],'week',900);assert.ok(week.ticks.some(v=>v.key==='2026-10-19'));
 const months=costTicks([{key:'2026-08'},{key:'2026-10'}],'month',900);assert.ok(months.ticks.some(v=>v.key==='2026-09'));
});
