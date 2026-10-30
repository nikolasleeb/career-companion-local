import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/bulletEditing.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {bulletDefault,bulletFormat,bulletSelection,bulletEnter,bulletBackspace,bulletInsert,editValue}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('format conversion keeps the selection on the same wording across lines',()=>{
 const text='First\nSecond';assert.deepEqual(bulletSelection(text,true,2,9),{start:4,end:13});
 assert.deepEqual(bulletSelection('• First\n• Second',false,4,13),{start:2,end:9});
 assert.deepEqual(bulletSelection('  • First',false,3,8),{start:2,end:6});
});
test('empty fields enable bullets while saved paragraphs stay unchanged',()=>{
 assert(bulletDefault(''));assert(bulletDefault('  '));assert(!bulletDefault('Two sentences. Same paragraph.'));assert(bulletDefault('- First\n  continued'));
 assert.equal(bulletFormat('Two sentences. Same paragraph.\nAnother line.',true),'• Two sentences. Same paragraph.\n• Another line.');
});
test('formatting preserves blank lines, existing markers and continuation wording',()=>{
 const text='• First\n  continued\n\n- Second\n* Third';assert.equal(bulletFormat(text,true),text);assert.equal(bulletFormat(text,false),'First\n  continued\n\nSecond\nThird');
});
test('first insertion starts a bullet without modifying an untouched empty field',()=>{
 assert.equal(editValue('',bulletInsert('',0,0,'Develop')),'• Develop');assert.equal(editValue('\n',bulletInsert('\n',0,0,'Test')),'• Test\n');
});
test('Enter splits at the caret and replaces selections without dropping the suffix',()=>{
 const text='• Test and document';assert.equal(editValue(text,bulletEnter(text,6,6)),'• Test\n•  and document');assert.equal(editValue(text,bulletEnter(text,6,11)),'• Test\n• document');
});
test('empty bullet exits instead of creating another marker',()=>{
 for(const text of ['• ','- ','* ']){const edit=bulletEnter(text,text.length,text.length);assert.equal(editValue(text,edit),'');assert(edit.exit);}
 const text='• Done\n• ';assert.equal(editValue(text,bulletEnter(text,text.length,text.length)),'• Done\n');
 assert.equal(editValue('',bulletEnter('',0,0)),'\n');
});
test('Shift+Enter continues a bullet including an existing indented continuation',()=>{
 assert.equal(editValue('• First\n  ',bulletInsert('• First\n  ',10,10,'continue')),'• First\n  continue');
 for(const text of ['• First','• First\n  more'])assert.equal(editValue(text,bulletEnter(text,text.length,text.length,true)),text+'\n  ');
});
test('Backspace at the marker removes formatting without losing content',()=>{
 assert.equal(editValue('• Test',bulletBackspace('• Test',2,2)),'Test');assert.equal(bulletBackspace('• Test',3,3),null);assert.equal(bulletBackspace('• Test',2,4),null);
});
test('pasting preserves paragraph sentences and list markers without doubled bullets',()=>{
 assert.equal(editValue('',bulletInsert('',0,0,'First. Still first.\r\nSecond\n\nThird')),'• First. Still first.\n• Second\n\n• Third');
 const pasted='• First\n  continued\n- Second';assert.equal(editValue('',bulletInsert('',0,0,pasted)),pasted);
 assert.equal(editValue('• ',bulletInsert('• ',2,2,'• First\n• Second')),'• First\n• Second');
});
test('selection replacement and insertion inside text retain surrounding wording',()=>{
 assert.equal(editValue('• alpha beta',bulletInsert('• alpha beta',2,7,'new')),'• new beta');assert.equal(editValue('old',bulletInsert('old',0,3,'New')),'• New');
 assert.equal(editValue('• alphabeta',bulletInsert('• alphabeta',7,7,' AND ')),'• alpha AND beta');
});
