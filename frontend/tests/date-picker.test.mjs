import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/datePicker.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {blankDate,dateParts,updateDateParts,formatDate,dateAllowed,dateError,dateYears,daysInMonth,entryDatePolicy}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const today=new Date(2026,9,21);
for(const order of ['ymd','ydm','myd','mdy','dym','dmy'])test(`date parts can be chosen in ${order} order`,()=>{
 let value=blankDate();const chosen={y:'2025',m:'8',d:'12'};
 for(const key of order)value=updateDateParts(value,key,chosen[key]);
 assert.equal(formatDate(value),'August 12, 2025');assert.equal(dateError(value,'past',today),'');
});
test('month/day without a year stays pending instead of becoming a different saved date',()=>{
 let value=updateDateParts(blankDate(),'m','8');assert.equal(formatDate(value),'');assert.match(dateError(value,'past',today),/year/);
 value=updateDateParts(value,'d','12');assert.equal(formatDate(value),'');
 value=updateDateParts(value,'y','2025');assert.equal(formatDate(value),'August 12, 2025');
 value=updateDateParts(value,'m','');assert.match(dateError(value,'past',today),/month/);assert.equal(formatDate(value),'');
});
test('start year list starts with current year; future choices stop at ten years',()=>{
 const past=dateYears('past',today).normal,future=dateYears('future',today).normal,end=dateYears('end',today).normal;
 assert.equal(past[0],2026);assert.equal(Math.max(...past),2026);assert.equal(past.at(-1),1900);
 assert.deepEqual(future,Array.from({length:11},(_,i)=>2026+i));assert.equal(end[0],2026);assert.equal(Math.max(...end),2036);assert.ok(end.includes(2025));
});
test('attendance starts exclude today and future days but permit honest partial dates',()=>{
 assert.equal(dateAllowed(dateParts('October 20, 2026'),'past',today),true);
 assert.equal(dateAllowed(dateParts('October 21, 2026'),'past',today),false);
 assert.equal(dateAllowed(dateParts('October 22, 2026'),'past',today),false);
 assert.equal(dateAllowed(dateParts('November 2026'),'past',today),false);
 assert.equal(dateAllowed(dateParts('October 2026'),'past',today),true);
 assert.equal(dateAllowed(dateParts('2026'),'past',today),true);
});
test('expected graduation starts after today and future ends stop at the exact ten-year boundary',()=>{
 assert.equal(dateAllowed(dateParts('October 21, 2026'),'future',today),false);
 assert.equal(dateAllowed(dateParts('October 22, 2026'),'future',today),true);
 for(const policy of ['future','end']){
  assert.equal(dateAllowed(dateParts('October 21, 2036'),policy,today),true);
  assert.equal(dateAllowed(dateParts('October 22, 2036'),policy,today),false);
  assert.equal(dateAllowed(dateParts('November 2036'),policy,today),false);
 }
 assert.equal(dateAllowed(dateParts('May 2025'),'end',today),true);
});
test('year ranges roll forward at New Year without hard-coded calendar years',()=>{
 const jan=new Date(2027,0,1);
 assert.equal(dateYears('past',jan).normal[0],2027);
 assert.equal(dateAllowed(dateParts('December 31, 2026'),'past',jan),true);
 assert.equal(dateAllowed(dateParts('January 1, 2027'),'past',jan),false);
 assert.equal(dateYears('future',jan).normal.at(-1),2037);
});
test('leap days and month lengths remain accurate before or after choosing the year',()=>{
 assert.equal(daysInMonth('','2'),29);assert.equal(daysInMonth('2028','2'),29);assert.equal(daysInMonth('2027','2'),28);
 let value={y:'',m:'2',d:'29',legacy:false};value=updateDateParts(value,'y','2027');assert.match(dateError(value,'end',today),/valid day/);
 value=updateDateParts(value,'y','2028');assert.equal(dateError(value,'end',today),'');
 assert.equal(dateAllowed(dateParts('February 28, 2034'),'future',new Date(2024,1,29)),true);
 assert.equal(dateAllowed(dateParts('March 1, 2034'),'future',new Date(2024,1,29)),false);
});
test('named and ISO imports preserve precision; unsupported or invalid imports remain legacy text',()=>{
 assert.deepEqual(dateParts('Aug 2025'),dateParts('2025-08'));
 assert.deepEqual(dateParts('12 August 2025'),dateParts('2025-08-12'));
 assert.equal(formatDate(dateParts('2025')),'2025');
 for(const text of ['Spring 2025','February 31, 2025','[date missing]'])assert.equal(dateParts(text).legacy,true);
});
test('out-of-range saved dates are retained without offering an unbounded future range',()=>{
 const value=dateParts('May 2040');assert.equal(dateError(value,'future',today,'','May 2040'),'');
 assert.match(dateError(updateDateParts(value,'m','6'),'future',today,'','May 2040'),/10 years/);
 const years=dateYears('future',today,'May 2040');assert.equal(years.normal[0],2026);assert.equal(years.normal.at(-1),2036);assert.equal(years.saved,2040);
});
test('ends cannot precede a known start; overlapping partial dates are not invented conflicts',()=>{
 assert.match(dateError(dateParts('May 2024'),'end',today,'August 2025'),/before the start/);
 assert.equal(dateError(dateParts('2025'),'end',today,'August 2025'),'');
 assert.match(dateError(dateParts('May 2024'),'end',today,'August 2025','May 2024'),/before the start/);
});

test('employment starts must precede today, including previously imported future values',()=>{
 for(const date of ['October 21, 2026','October 22, 2026','November 2026','2027']){
  assert.equal(dateAllowed(dateParts(date),'employment-start',today),false);
  assert.match(dateError(dateParts(date),'employment-start',today,'',date),/before today/);
 }
 for(const date of ['October 20, 2026','September 2026','2025'])assert.equal(dateError(dateParts(date),'employment-start',today),'');
 assert.equal(Math.max(...dateYears('employment-start',today).normal),2026);
});
test('employment ends allow historical dates and cap the exact calendar anniversary at one year',()=>{
 for(const date of ['May 2025','October 21, 2027','October 2027','2027'])assert.equal(dateAllowed(dateParts(date),'employment-end',today),true);
 for(const date of ['October 22, 2027','November 2027','2028']){
  assert.equal(dateAllowed(dateParts(date),'employment-end',today),false);
  assert.match(dateError(dateParts(date),'employment-end',today,'',date),/one year/);
 }
 const years=dateYears('employment-end',today,'May 2040');assert.deepEqual(years.normal.slice(0,3),[2026,2027,2025]);assert.equal(Math.max(...years.normal),2027);assert.equal(years.saved,2040);
});
test('employment limits roll forward and clamp February 29 to the following February 28',()=>{
 const leap=new Date(2024,1,29);
 assert.equal(dateAllowed(dateParts('February 28, 2025'),'employment-end',leap),true);
 assert.equal(dateAllowed(dateParts('March 1, 2025'),'employment-end',leap),false);
 const jan=new Date(2027,0,1);
 assert.equal(dateAllowed(dateParts('January 1, 2028'),'employment-end',jan),true);
 assert.equal(dateAllowed(dateParts('January 2, 2028'),'employment-end',jan),false);
 assert.equal(dateAllowed(dateParts('December 31, 2026'),'employment-start',jan),true);
});
test('employment dates retain partial precision and chronological validation',()=>{
 assert.equal(dateAllowed(dateParts('October 2026'),'employment-start',today),true);
 assert.equal(dateAllowed(dateParts('2026'),'employment-start',today),true);
 assert.match(dateError(dateParts('May 2025'),'employment-end',today,'August 2025'),/before the start/);
 assert.equal(dateError(dateParts('August 2025'),'employment-end',today,'June 2025'),'');
 assert.match(dateError({y:'',m:'6',d:'',legacy:false},'employment-start',today),/year/);
});
test('employment policies apply to the shared editor without changing other date ranges',()=>{
 assert.equal(entryDatePolicy('employment','start_date'),'employment-start');assert.equal(entryDatePolicy('employment','end_date'),'employment-end');
 assert.equal(entryDatePolicy('education','start_date'),'past');assert.equal(entryDatePolicy('education','end_date'),'education-end');assert.equal(entryDatePolicy('education','expected_graduation'),'future');
 for(const category of ['project','volunteering','coursework'])assert.equal(entryDatePolicy(category,'end_date'),'end');
 assert.equal(dateAllowed(dateParts('October 21, 2036'),entryDatePolicy('education','end_date'),today),true);
});


test('education end lists current and past years first, with future years separate',()=>{
 const policy=entryDatePolicy('education','end_date'),years=dateYears(policy,today);
 assert.deepEqual(years.normal.slice(0,4),[2026,2025,2024,2023]);assert.equal(years.normal.at(-1),1900);
 assert.deepEqual(years.future,Array.from({length:10},(_,i)=>2027+i));
 assert.equal(dateYears(policy,today,'May 2030').saved,null);
 assert.equal(dateYears(policy,today,'May 2040').saved,2040);
});

test('graduates can choose past attendance ends in either month/year order',()=>{
 const policy=entryDatePolicy('education','end_date');
 for(const order of ['my','ym']){
  let parts=blankDate();for(const k of order)parts=updateDateParts(parts,k,k==='m'?'5':'2025');
  assert.equal(formatDate(parts),'May 2025');assert.equal(dateAllowed(parts,policy,today,'August 2021'),true);assert.equal(dateError(parts,policy,today,'August 2021'),'');
 }
 assert.match(dateError(dateParts('May 2021'),policy,today,'August 2021'),/before the start/);
 assert.equal(dateError(dateParts('2021'),policy,today,'August 2021'),'');
 assert.equal(dateError(dateParts('May 2020'),policy,today,'August 2016'),'');
});
