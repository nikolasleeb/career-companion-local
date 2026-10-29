import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/careerPages.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {careerPages}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('short result sets expose every page; large catalogs keep useful bounded page buttons',()=>{
 assert.deepEqual(careerPages(8,2),[1,2,3,4,5,6,7,8]);
 assert.deepEqual(careerPages(85,42),[1,'gap',40,41,42,43,44,'gap',85]);
 assert.deepEqual(careerPages(85,1),[1,2,3,'gap',85]);
 assert.deepEqual(careerPages(85,85),[1,'gap',83,84,85]);
});
