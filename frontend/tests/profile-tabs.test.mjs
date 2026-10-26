import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/profileTabState.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {profileTabs,savedProfileTab}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('Profile presents goals immediately before private information',()=>{assert.deepEqual(profileTabs.map(p=>p.label),['Upload / import','Personal details','Resume content','Career Goals','Private application answers']);});
test('first visit and invalid stored tabs safely open Resume content',()=>{for(const v of [null,'education','__proto__'])assert.equal(savedProfileTab('a',{getItem:()=>v}),'resume');assert.equal(savedProfileTab('a',{getItem:()=>{throw Error();}}),'resume');});
test('tab selection is account-scoped and only known identifiers restore',()=>{const values={'career-profile-tab:a':'goals','career-profile-tab:b':'private'};const storage={getItem:k=>values[k]};assert.equal(savedProfileTab('a',storage),'goals');assert.equal(savedProfileTab('b',storage),'private');assert.equal(savedProfileTab('c',storage),'resume');});
