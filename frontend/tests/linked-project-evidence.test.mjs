import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/linkedProjectEvidenceState.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {linkedProjectUses}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('only selected linked items count as project evidence under Work Experience',()=>{
 const catalog=[{id:'intern',category:'employment',title:'Intern',items:[{item_id:'own'},{item_id:'linked',project_source:{project_id:'project'}}]},{id:'contractor',category:'employment',title:'Contractor',items:[{item_id:'unselected',project_source:{project_id:'project'}}]},{id:'project',category:'project',title:'Project',items:[{item_id:'original'}]}];
 const form={experience_ids:['intern','contractor'],content:{intern:[0,1],contractor:[]}};
 assert.deepEqual(linkedProjectUses(catalog,form,'project').map(v=>v.title),['Intern']);
 assert.deepEqual(linkedProjectUses(catalog,{...form,content:{intern:[0]}},'project'),[]);
 assert.deepEqual(linkedProjectUses(catalog,{...form,experience_ids:[]},'project'),[]);
 assert.deepEqual(linkedProjectUses(catalog,form,'other-project'),[]);
});
