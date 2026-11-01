import {test} from 'node:test';import assert from 'node:assert/strict';import {readFileSync} from 'node:fs';import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/classStatus.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {classReadGuard}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('late class list reads cannot undo a successful save or a later refresh',()=>{const guard=classReadGuard();const old=guard.start();guard.invalidate();assert.equal(guard.current(old),false);const a=guard.start(),b=guard.start();assert.equal(guard.current(a),false);assert.equal(guard.current(b),true);});
