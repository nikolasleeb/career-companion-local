import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/explicitContextData.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const data=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('handoffs cannot silently overwrite an unrelated unsent draft',()=>{
 let confirmations=0;globalThis.window={confirm:()=>{confirmations++;return false;}};
 const detail={prompt:'Explore this occupation'};
 assert.equal(data.acceptHandoff(detail,''),true);assert.equal(data.acceptHandoff(detail,detail.prompt),true);assert.equal(confirmations,0);
 assert.equal(data.acceptHandoff(detail,'My own unfinished message'),false);assert.equal(confirmations,1);
 globalThis.window.confirm=()=>true;assert.equal(data.acceptHandoff(detail,'My own unfinished message'),true);
 delete globalThis.window;
});
test('context draft recovery is account and destination scoped',()=>{
 const values=new Map();globalThis.sessionStorage={getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v)};
 const items=[{context_ref:{kind:'occupation',id:'15-1252.00',revision:'a'.repeat(64)},title:'Software Developers'}];
 data.saveContextDraft('alice','plans:new',items);
 assert.deepEqual(data.readContextDraft('alice','plans:new'),items);assert.deepEqual(data.readContextDraft('bob','plans:new'),[]);assert.deepEqual(data.readContextDraft('alice','knowledge'),[]);
 values.set('career-explicit-draft:alice:plans:new','broken-json');assert.deepEqual(data.readContextDraft('alice','plans:new'),[]);
 delete globalThis.sessionStorage;
});
test('saved context retains the exact submitted revision until explicitly refreshed',async()=>{
 const items=data.contextFromSources([{record_id:'application-one',kind:'explicit_offer',revision:'a'.repeat(64),snapshot:{label:'Example offer',details:{compensation:'84000'}}}]);
 assert.equal(items[0].context_ref.kind,'offer');assert.equal(items[0].context_ref.id,'application-one');assert.equal(items[0].context_ref.revision,'a'.repeat(64));
 const calls=[];const updated=await data.refreshExplicit(items[0],async(path,...args)=>{calls.push([path,...args]);return {context_ref:{revision:'b'.repeat(64)}};});
 assert.equal(updated.context_ref.revision,'b'.repeat(64));assert.deepEqual(calls,[['/applications/application-one/offer/preview']]);assert.equal(items[0].context_ref.revision,'a'.repeat(64));
});
