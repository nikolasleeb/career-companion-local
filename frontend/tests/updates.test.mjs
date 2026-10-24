import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=readFileSync(new URL('../src/updateStatus.ts',import.meta.url),'utf8');
const {updateLabel}=await import('data:text/javascript;base64,'+Buffer.from(ts.transpileModule(code,{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText).toString('base64'));
const current={state:'up_to_date',stale:false,error:'',latest:{version:'1.0.0'}};
test('update labels never call stale or failed checks up to date',()=>{
 assert.equal(updateLabel(current),'Up to date');
 assert.equal(updateLabel({...current,stale:true}),'Check needed');
 assert.equal(updateLabel({...current,error:'Offline'}),'Unable to check');
 assert.equal(updateLabel({...current,state:'custom'}),'Custom build');
 assert.equal(updateLabel({...current,state:'update_available'}),'Update available');
});
