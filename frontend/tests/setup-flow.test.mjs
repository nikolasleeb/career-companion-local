import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const source=ts.transpileModule(readFileSync(new URL('../src/setupFlow.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {setupView,restoredSetup}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
test('fresh sign-in starts in Profile and old application navigation cannot bypass setup',()=>{
 assert.equal(restoredSetup(null,false).view,'master');
 for(const view of ['applications','jobs','tailor','cover','agent','prep','interests','guide'])assert.deepEqual(restoredSetup({view,jobId:'stale',applicationId:'stale'},false),{view:'master',jobId:'',applicationId:''});
});
test('Profile and Settings remain available while resources require education',()=>{
 for(const view of ['master','settings'])assert.equal(setupView(view,false),view);
 assert.equal(restoredSetup({view:'prep',jobId:'old'},false).view,'master');
});
test('completed accounts retain Applications-first and exact workspace restoration',()=>{
 assert.equal(restoredSetup(null,true).view,'applications');
 assert.deepEqual(restoredSetup({view:'cover',jobId:'posting',applicationId:'application'},true),{view:'cover',jobId:'posting',applicationId:'application'});
});
