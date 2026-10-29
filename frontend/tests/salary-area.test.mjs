import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/salaryAreaChoices.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {salaryAreaChoices}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const areas=[{id:'US',title:'United States',type:'national',state:'',state_codes:[],search_text:'united states'}, {id:'state:51',title:'Virginia',type:'state',state:'VA',state_codes:['VA'],search_text:'virginia va'}, {id:'metro:47900',title:'Washington-Arlington-Alexandria, DC-VA-MD-WV',type:'metro',state:'DC',state_codes:['DC','VA','MD','WV'],aliases:['dmv','nova','northern virginia','washington dc','washington d c'],search_text:'washington arlington alexandria dc va md wv virginia maryland west virginia'}, {id:'state:04',title:'Arizona',type:'state',state:'AZ',state_codes:['AZ'],search_text:'arizona az'}];
test('salary filtering includes all participating metro states and aliases',()=>{
 for(const query of ['VA','Virginia','dmv','NoVA','Northern Virginia','Washington D.C.','Maryland'])assert(salaryAreaChoices(areas,query).some(a=>a.id==='metro:47900'));
 assert.deepEqual(salaryAreaChoices(areas,'VA').map(a=>a.id),['state:51','metro:47900']);assert.deepEqual(salaryAreaChoices(areas,'unknown'),[]);
 assert.equal(salaryAreaChoices(areas,'').length,areas.length);
});
