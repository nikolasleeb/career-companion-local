import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/jobSearchHistory.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {orderedSearches,chooseSearch,readSelectedSearch,rememberSelectedSearch,searchHistoryLabel}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const row=(id,date,data={})=>({id,created_at:date,data});
test('newest completed normal and AI searches remain available without mixing in For you',()=>{
 const original=[row('old','2026-01-01'),row('personal','2026-03-01',{discovery_kind:'for_you'}),row('ai','2026-02-01',{ai_brief:{}})];
 const history=orderedSearches(original);assert.deepEqual(history.map(x=>x.id),['ai','old']);assert.equal(original[0].id,'old');
 assert.equal(chooseSearch(history,'old').id,'old');assert.equal(chooseSearch(history,'missing').id,'ai');assert.equal(chooseSearch([], 'old'),undefined);
});
test('only the search ID is persisted and selections cannot cross accounts',()=>{
 const values=new Map(),storage={getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v)};
 rememberSelectedSearch('a','old',storage);rememberSelectedSearch('b','new',storage);
 assert.equal(readSelectedSearch('a',storage),'old');assert.equal(readSelectedSearch('b',storage),'new');assert.equal(readSelectedSearch('c',storage),'');assert.deepEqual([...values.values()],['old','new']);
 assert.equal(chooseSearch([row('b-only','2026-01-01')],readSelectedSearch('a',storage)).id,'b-only');
});
test('disabled browser storage does not prevent viewing saved searches',()=>{
 const storage={getItem(){throw Error('Blocked')},setItem(){throw Error('Blocked')}};assert.equal(readSelectedSearch('a',storage),'');assert.doesNotThrow(()=>rememberSelectedSearch('a','id',storage));
});
test('history labels identify roles and locations without relying on original result counts',()=>{
 const label=searchHistoryLabel(row('id','2026-01-01',{query:{interests:['Data science','Cloud','Research'],location:'Richmond, VA'},retained_matches:99}));
 assert.match(label,/Data science, Cloud \+1/);assert.match(label,/Richmond, VA/);assert.doesNotMatch(label,/99 jobs/);
 const ai=searchHistoryLabel(row('ai','invalid',{discovery_kind:'ai',ai_brief:{summary:'Research roles'}}));assert.match(ai,/AI search.*Date unavailable.*Research roles.*Location not recorded/);
 const long=searchHistoryLabel(row('long','2026-01-01',{query:{title:'x'.repeat(500),location:'y'.repeat(500)}}));assert.ok(long.length<200);
});
test('multi-location history labels include the selected locations rather than only the legacy scalar',()=>{
 const label=searchHistoryLabel(row('multi','2026-01-01',{query:{title:'Analyst',location:'United States',locations:['Richmond, VA','Boston, MA','Virginia']}}));
 assert.match(label,/Richmond, VA; Boston, MA \+1/);assert.doesNotMatch(label,/United States/);
});
