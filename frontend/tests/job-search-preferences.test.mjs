import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const source=ts.transpileModule(readFileSync(new URL('../src/jobSearchPreferences.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {addRole,recentRoles,roleChoices,preferenceSaver,addBundle}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
test('custom roles survive deselection in the remembered choices, without case duplicates',()=>{
 const selected=addRole(['Nursing'],'  Museum   education ');const history=recentRoles([],selected);
 assert.deepEqual(selected,['Nursing','Museum education']);assert.deepEqual(addRole(selected,'museum EDUCATION'),selected);
 assert.ok(roleChoices([],history,'museum').includes('Museum education'));
 assert.throws(()=>addRole(Array.from({length:12},(_,i)=>'Role '+i),'New role'),/12 roles/);assert.throws(()=>addRole([],'a'),/2–80/);
});
const catalog=JSON.parse(readFileSync(new URL('../../backend/app/role_catalog.json',import.meta.url),'utf8'));
test('multiple disciplines remain available from the shared suggested catalog',()=>{assert.ok(roleChoices([],[],'nurs',catalog.roles.map(r=>r.label)).includes('Nursing'));assert.ok(roleChoices([],[],'civil',catalog.roles.map(r=>r.label)).includes('Civil engineering'));assert.ok(roleChoices([],[],'cloud',catalog.roles.map(r=>r.label)).includes('Cloud infrastructure'));});
test('preference writes are ordered and closing immediately flushes the latest choices',async()=>{
 let release;const seen=[],states=[];const gate=new Promise(r=>release=r);const saver=preferenceSaver(async value=>{seen.push(value);if(seen.length===1)await gate;},v=>states.push(v),10000);
 saver.prime({roles:[]});saver.update({roles:['Nursing']});const first=saver.flush();await Promise.resolve();saver.update({roles:['Nursing','Museum education']});saver.dispose();release();await first;await saver.flush();
 assert.deepEqual(seen,[{roles:['Nursing']},{roles:['Nursing','Museum education']}]);
});
test('a failed autosave remains retryable and unchanged acknowledged values are not rewritten',async()=>{
 let count=0;const states=[];const saver=preferenceSaver(async()=>{if(++count===1)throw Error('Offline');},v=>states.push(v),10000);
 saver.prime({roles:[]});saver.update({roles:['Finance']});await assert.rejects(saver.flush(),/Offline/);assert.equal(states.at(-1),'error');await saver.flush();assert.equal(states.at(-1),'saved');await saver.flush();assert.equal(count,2);saver.dispose();
});

test('returning to the saved selection while a write is in flight still persists the return',async()=>{
 let release;const gate=new Promise(r=>release=r),seen=[];
 const saver=preferenceSaver(async value=>{seen.push(value);if(seen.length===1)await gate;},()=>{},10000);
 saver.prime({roles:['Nursing']});saver.update({roles:['Finance']});const first=saver.flush();await Promise.resolve();saver.update({roles:['Nursing']});const latest=saver.flush();release();await first;await latest;assert.deepEqual(seen,[{roles:['Finance']},{roles:['Nursing']}]);saver.dispose();
});

test('field bundles are atomic, additive and case-insensitively deduplicated',()=>{assert.deepEqual(addBundle(['Accounting'],['accounting','Nursing']),['Accounting','Nursing']);const original=Array.from({length:11},(_,i)=>'Role '+i);assert.throws(()=>addBundle(original,['Nursing','Accounting']),/no roles were added/);assert.equal(original.length,11);for(const roles of Object.values(catalog.groups))assert.ok(roles.length<=12);});
