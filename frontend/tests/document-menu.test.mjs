import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/documentMenuPosition.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {documentMenuPosition}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('document menu stays anchored below a desktop trigger when there is room',()=>{
 const p=documentMenuPosition({left:800,right:860,top:200,bottom:240},{width:210,height:100},{left:0,right:1200,top:150,bottom:750});
 assert.equal(p.left,650);assert.equal(p.top,246);
});
test('menu flips above near the scrolling body footer and remains inside narrow viewport edges',()=>{
 const p=documentMenuPosition({left:300,right:380,top:510,bottom:550},{width:210,height:120},{left:0,right:390,top:160,bottom:570});
 assert.equal(p.top,384);assert.ok(p.left>=8&&p.left+210<=382);
 const left=documentMenuPosition({left:2,right:60,top:200,bottom:240},{width:210,height:120},{left:0,right:390,top:160,bottom:570});
 assert.equal(left.left,8);
});
test('long menus get a scrolling height rather than escaping a short viewport',()=>{
 const p=documentMenuPosition({left:150,right:210,top:220,bottom:260},{width:210,height:500},{left:0,right:320,top:180,bottom:380});
 assert.equal(p.maxHeight,184);assert.ok(p.top>=188&&p.top+p.maxHeight<=372);
});
