import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const source=ts.transpileModule(readFileSync(new URL('../src/locationChoices.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {locationChoices,groupLocationChoices}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
test('location history is complete, first, case-insensitive and searchable',()=>{
 const history=Array.from({length:80},(_,i)=>'Fictional City '+i);
 const choices=locationChoices(['  Boston,   MA',...history],['boston, ma','East Coast'],'');
 assert.equal(choices[0],'Boston, MA');assert.equal(choices.length,82);assert.ok(choices.includes(history[79]));assert.equal(choices.at(-1),'East Coast');
 assert.deepEqual(locationChoices(['Richmond, VA','Boston, MA'],['Virginia','East Coast'],' va'),['Richmond, VA']);
 assert.deepEqual(locationChoices(['Richmond, VA'],['East Coast'],'unknown'),[]);
});

test('location categories stay distinct and filtering keeps their headings',()=>{
 const catalog={Nationwide:['United States'],Regions:['East Coast','West Coast'],States:['Virginia','Massachusetts'],Cities:['Boston, MA','Richmond, VA']};
 const choices=locationChoices(['Boston, MA','My custom region'],Object.values(catalog).flat(),'');
 const grouped=groupLocationChoices(choices,catalog);
 assert.deepEqual(grouped.map(g=>g.name),['Nationwide','Regions','States','Cities','Your locations']);
 assert.deepEqual(grouped.find(g=>g.name==='Cities').values,['Boston, MA','Richmond, VA']);
 assert.equal(grouped.flatMap(g=>g.values).filter(v=>v==='Boston, MA').length,1);
 assert.deepEqual(groupLocationChoices(locationChoices([],Object.values(catalog).flat(),'Virginia'),catalog),[{name:'States',values:['Virginia']}]);
 assert.deepEqual(groupLocationChoices([],catalog),[]);
 assert.deepEqual(groupLocationChoices(['Custom city'],{}),[{name:'Your locations',values:['Custom city']}]);
});
