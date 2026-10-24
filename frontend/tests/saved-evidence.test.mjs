import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const education=ts.transpileModule(readFileSync(new URL('../src/educationFlow.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const code=ts.transpileModule(readFileSync(new URL('../src/savedEvidence.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText.replace('./educationFlow','data:text/javascript;base64,'+Buffer.from(education).toString('base64'));
const {savedEvidenceText,addSavedEvidence}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('saved evidence retains individual contribution and project link without inventing results',()=>{
 const text=savedEvidenceText({data:{title:'Demand study',description:'Prepared data.',contribution:'My teammate trained the model.',project_url:'https://github.com/example/project',gpa:'4.0',us_citizen:'yes'}});
 assert.ok(text.includes('My teammate trained the model.'));assert.ok(text.includes('https://github.com/example/project'));assert.ok(!text.includes('4.0'));assert.ok(!text.includes('us_citizen'));assert.ok(!text.includes('I trained'));
});
test('adding saved evidence preserves typed text and does not duplicate the same excerpt',()=>{
 const combined=addSavedEvidence('My own notes.','Saved project excerpt.');assert.equal(combined,'My own notes.\n\nSaved project excerpt.');assert.equal(addSavedEvidence(combined,'Saved project excerpt.'),combined);
});
test('both repository links remain available when adding saved experience to an answer',()=>{
 const links=['https://github.com/example/original','https://github.com/example/extension'];
 const text=savedEvidenceText({data:{title:'Extended study',project_url:links[0],project_urls:links}});
 assert.ok(links.every(link=>text.includes(link)));assert.equal(text.split(links[0]).length,2);
});

test('all education subjects are available when reusing saved experience',()=>{const text=savedEvidenceText({data:{title:'BS',major:'stale',majors:['Computer Science','Mathematics'],minors:['Music','History']}});for(const value of ['Computer Science','Mathematics','Music','History'])assert.ok(text.includes(value));assert.ok(!text.includes('stale'));});
