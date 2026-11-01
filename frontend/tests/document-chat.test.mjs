import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const source=ts.transpileModule(readFileSync(new URL('../src/documentChat.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText.replace("import { useState } from 'react';",'const useState=()=>{throw Error("Hook not rendered in storage contract test");};');
const {chatBufferKey,readChatBuffer,writeChatBuffer}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const memory=()=>{const map=new Map();return {getItem:k=>map.get(k)||null,setItem:(k,v)=>map.set(k,v),removeItem:k=>map.delete(k)};};
test('unsent conversations survive application switching and remain account/resume scoped',()=>{
 const storage=memory(),first=chatBufferKey('a','resume','job-1'),second=chatBufferKey('a','resume','job-2');writeChatBuffer(first,'Keep my project wording',storage);writeChatBuffer(second,'Focus on reporting',storage);
 assert.equal(readChatBuffer(first,storage),'Keep my project wording');assert.equal(readChatBuffer(second,storage),'Focus on reporting');
 assert.equal(readChatBuffer(chatBufferKey('b','resume','job-1'),storage),'');assert.notEqual(chatBufferKey('a','cover','job-1','r1'),chatBufferKey('a','cover','job-1','r2'));
 writeChatBuffer(first,'',storage);assert.equal(readChatBuffer(first,storage),'');assert.equal(readChatBuffer(second,storage),'Focus on reporting');
});
