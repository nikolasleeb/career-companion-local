import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const src=ts.transpileModule(readFileSync(new URL('../src/assistantText.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {chatBlocks,coachResearchLabel}=await import('data:text/javascript;base64,'+Buffer.from(src).toString('base64'));
const text=s=>chatBlocks(s).map(b=>b.parts.map(p=>p.text).join('')).join('\n');
test('historical headings and paired emphasis become ordinary conversational prose',()=>{
 const original='## AWS culture\n\nThe **company** and _employees_ differ.\n\n- First\n- Second';
 assert.equal(text(original),'AWS culture\nThe company and employees differ.\n- First\n- Second');
 assert(original.includes('**company**'));
});
test('literal math, unmatched markers, URLs, quotations, and HTML-like strings stay literal',()=>{
 for(const s of ['2 ** 3; 4 * 5','Use *.py and foo_bar','https://example.org/a_**b**?x=1','"**quoted**"','> ## **source quotation**','<img src=x onerror=alert(1)>','\\*literal\\*'])assert.equal(text(s),s);
});
test('inline and fenced code preserve all code contents',()=>{
 assert.deepEqual(chatBlocks('Use `**literal**` here.')[0].parts.map(p=>p.text),['Use ','**literal**',' here.']);
 assert.equal(chatBlocks('```python\n# title\nprint("**value**")\n```')[0].parts[0].text,'# title\nprint("**value**")');
});
test('research status distinguishes relevance and legacy metadata honestly',()=>{
 assert.equal(coachResearchLabel({research_diagnostics:{outcome:'limited_evidence'}}),'Limited relevant web evidence');
 assert.match(coachResearchLabel({research_used:true}),/relevance not assessed/);
 assert.match(coachResearchLabel({}),/general guidance/);
});
