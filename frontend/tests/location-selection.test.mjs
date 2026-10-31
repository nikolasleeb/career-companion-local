import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/locationSelection.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {selectedLocations,locationQuery,addLocation}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('legacy and AI multi-location queries retain their selected places',()=>{
 assert.deepEqual(selectedLocations({location:'United States'}),['United States']);
 assert.deepEqual(selectedLocations({location:'United States',locations:['Richmond, VA','Boston, MA']}),['Richmond, VA','Boston, MA']);
 assert.deepEqual(selectedLocations({locations:[' Richmond,   VA ','richmond, va']}),['richmond, va']);
 assert.deepEqual(locationQuery([]),{location:'',locations:[]});
 assert.deepEqual(locationQuery(['Boston, MA']),{location:'Boston, MA',locations:[]});
 assert.deepEqual(locationQuery(['Richmond, VA','Boston, MA']),{location:'Richmond, VA',locations:['Richmond, VA','Boston, MA']});
});
test('nationwide and narrower selections cannot silently override each other',()=>{
 assert.deepEqual(addLocation(['United States'],'  Richmond,   VA '),['Richmond, VA']);
 assert.deepEqual(addLocation(['Richmond, VA'],'Boston, MA'),['Richmond, VA','Boston, MA']);
 assert.deepEqual(addLocation(['Richmond, VA','Boston, MA'],'United States'),['United States']);
 assert.deepEqual(addLocation(['USA'],'Virginia'),['Virginia']);
 assert.deepEqual(addLocation(['Boston, MA'],'boston, ma'),['Boston, MA']);
});
test('bounded selections reject invalid text and allow replacing a full selection with nationwide',()=>{
 const ten=Array.from({length:10},(_,i)=>'City '+i);
 assert.throws(()=>addLocation(ten,'City eleven'),/up to ten/);
 assert.deepEqual(addLocation(ten,'United States'),['United States']);
 for(const invalid of [' ','x','x'.repeat(121)])assert.throws(()=>addLocation([],invalid),/2 to 120/);
 assert.equal(ten.length,10);
});
