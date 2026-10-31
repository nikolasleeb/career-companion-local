import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/searchSettingsState.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {selectedSourceCount,selectedEmployerCount}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const rows=[{key:'a',employer_id:'one',industries:['tech']},{key:'b',employer_id:'one',industries:['tech']},{key:'c',employer_id:'two',industries:['health']},{key:'d',employer_id:'external',coverage_status:'external',industries:['tech']}];
test('counts reflect available sources without counting unconfigured credentials',()=>{assert.equal(selectedSourceCount({sources:['greenhouse','adzuna','usajobs']},{adzuna:false,usajobs:true}),2);assert.equal(selectedSourceCount({sources:['adzuna']},{adzuna:true}),1);});
test('employer counts deduplicate feeds and respect sectors, individual selections and no selection',()=>{assert.equal(selectedEmployerCount({},rows),2);assert.equal(selectedEmployerCount({employer_selection_mode:'industries',employer_industries:['tech']},rows),1);assert.equal(selectedEmployerCount({employer_boards:['b','c']},rows),2);assert.equal(selectedEmployerCount({employer_selection_mode:'custom',employer_boards:[]},rows),0);assert.equal(selectedEmployerCount({}),0);});
