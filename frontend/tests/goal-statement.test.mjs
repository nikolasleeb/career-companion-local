import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/goalStatement.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {emptyStatementEditor,buildStatement,statementText,meaningfulStatement,cleanEditor}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const editor=(education,fields)=>({...emptyStatementEditor(),education,fields:{...emptyStatementEditor().fields,...fields}});
test('student statement combines only completed clauses and keeps timing separate',()=>{
 assert.equal(buildStatement(editor('yes',{graduation:'May 2027',degree:'Data Science (MS)',skills:'Python and SQL',certifications:'AWS Data Engineer',timing:'before graduation'})), 'I aim to graduate in May 2027 with a degree in Data Science (MS). I want to develop Python and SQL skills. I want to earn AWS Data Engineer certifications. My target timeframe is before graduation.');
 assert.equal(buildStatement(editor('yes',{graduation:'2028'})),'I aim to graduate in 2028.');
 assert.equal(buildStatement(editor('yes',{degree:'Computer Science'})),'I aim to graduate with a degree in Computer Science.');
});
test('non-student and skip paths never imply enrollment, employment or a degree',()=>{
 const e=editor('no',{completed_degree:'a BS in Physics',future_education:'a part-time master’s degree',graduation:'HIDDEN_DATE',degree:'HIDDEN_DEGREE',field:'cloud operations'});
 assert.equal(buildStatement(e),'I have completed a BS in Physics. My future education plans include a part-time master’s degree. I would like to work in cloud operations.');
 assert.equal(buildStatement({...e,education:'skip'}),'I would like to work in cloud operations.');
 assert.equal(e.fields.graduation,'HIDDEN_DATE');
 assert.match(buildStatement({...e,education:'yes'}),/HIDDEN_DATE/);
});
test('blank markers and punctuation alone cannot produce a statement',()=>{
 assert.equal(buildStatement(editor('yes',{degree:'[blank]',graduation:' ',skills:'...',priorities:'___'})),'');
 for(const text of ['[blank]','  [blank]  ','___','…'])assert.equal(meaningfulStatement(text),false);
 assert.equal(statementText('Explore cloud [blank] engineering.'),'Explore cloud engineering.');
 assert.equal(cleanEditor(editor('skip',{skills:' [blank] '})).fields.skills,'');
});
test('independent focus and reason fields form complete sentences without orphan clauses',()=>{
 assert.equal(buildStatement(editor('skip',{focus:'reliable systems',reason:'practical impact'})),'I would like my work to focus on reliable systems. I am motivated by practical impact.');
 assert.equal(buildStatement(editor('skip',{priorities:'continued learning',reason:'I enjoy solving problems',skills:'technical skills'})),'I want to develop technical skills. What matters to me is continued learning because I enjoy solving problems.');
});
