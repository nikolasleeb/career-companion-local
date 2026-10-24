import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/educationFlow.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {subjects,educationPayload,educationTitle,replacementCourses,activeImportWarnings}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('transcript replacement contains selected titles only and preserves internal commas',()=>{
 const courses=[{id:'1',title:'Ethics, Policy and Law'},{id:'2',title:'Statistics'},{id:'3',title:' statistics '},{id:'4',title:'Not selected'}];
 assert.deepEqual(replacementCourses(courses,['1','2','3']),{value:'Ethics, Policy and Law; Statistics'});
});
test('empty and oversized course selections return an error without a replacement value',()=>{
 for(const replacement of [replacementCourses([],[]),replacementCourses([{id:'x',title:'x'.repeat(4001)}],['x'])]){assert.ok(replacement.error);assert.equal(replacement.value,undefined);}
 assert.equal(replacementCourses([{id:'x',title:'x'.repeat(4000)}],['x']).value.length,4000);
});
test('legacy combined subjects stay one item, explicit empty arrays clear the compatibility field',()=>{
 assert.deepEqual(subjects({major:'Economics & Politics'},'major'),['Economics & Politics']);
 assert.deepEqual(educationPayload({major:'Old major',minor:'Old minor',majors:[],minors:[]}),{major:'',minor:'',majors:[],minors:[]});
});
test('multiple subjects generate a title and mirror only their first compatibility value',()=>{
 const data={category:'education',degree:'BS',majors:[' Computer Science ','Mathematics','computer science'],minors:['Music','History']};
 assert.equal(educationTitle(data),'BS in Computer Science & Mathematics');
 assert.deepEqual(educationPayload(data),{major:'Computer Science',minor:'Music',majors:['Computer Science','Mathematics'],minors:['Music','History']});
});
const role='Role and employer were not separately identified; review this heading.';
test('role warning resolves after correction without clearing unrelated parser warnings or metadata',()=>{
 const item={data:{category:'employment',title:'Associate',organization:'Example Employer'},warnings:[role,'Dates need review.'],source_text:'Original heading'};
 assert.deepEqual(activeImportWarnings(item),['Dates need review.']);assert.deepEqual(item.warnings,[role,'Dates need review.']);assert.equal(item.source_text,'Original heading');
 for(const data of [{title:' Employer ',organization:'employer'},{title:'Associate',organization:''},{title:'',organization:'Employer'}])assert.deepEqual(activeImportWarnings({...item,data:{category:'employment',...data}}),item.warnings);
});
