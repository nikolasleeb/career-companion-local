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
const {editImportFields}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('editing inline subjects reconciles legacy fields and the education title without modifying source data',()=>{
 const original={category:'education',degree:'Master of Science (MS)',major:'Old',majors:['Old'],title:'Old title'};
 const result=editImportFields(original,{majors:['Data Science','Statistics']});
 assert.equal(result.data.major,'Data Science');assert.equal(result.data.title,'Master of Science (MS) in Data Science & Statistics');
 assert.deepEqual(result.touched.sort(),['major','majors','title']);assert.equal(original.major,'Old');
 const scalar=editImportFields(original,{major:'Economics'});assert.deepEqual(scalar.data.majors,['Economics']);
});
test('editing structured dates reconciles original wording with explicit dates and preserves date precision',()=>{
 const result=editImportFields({category:'education',start_date:'2020',end_date:'',expected_graduation:'May 2027',dates:'Unresolved source dates'},{end_date:'2024'});
 assert.equal(result.data.dates,'2020 – 2024; Expected graduation May 2027');assert.deepEqual(result.touched,['end_date','dates']);
 assert.equal(editImportFields(result.data,{description:'Reviewed notes'}).data.dates,result.data.dates);
});
test('explicit source list and scalar choices stay synchronized, including omissions',()=>{
 assert.deepEqual(editImportFields({category:'project',project_urls:['old']},{project_url:'https://example.test/project'}).data.project_urls,['https://example.test/project']);
 assert.equal(editImportFields({category:'project'},{project_urls:[]}).data.project_url,'');
 assert.deepEqual(editImportFields({category:'education',minors:['Old'],minor:'Old'},{minor:''}).data.minors,[]);
});

const {subjectDrafts}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('major and minor drafts retain spaces through character-by-character edits and newly added empty rows',()=>{
 for(const field of ['major','minor']){
  let data={category:'education',degree:'Bachelor of Science',[field+'s']:['']};
  for(const char of 'Business Information Technology'){
   const values=subjectDrafts(data,field);values[0]+=char;
   data=editImportFields(data,{[field+'s']:values}).data;
   assert.equal(subjectDrafts(data,field)[0],values[0]);
  }
  data=editImportFields(data,{[field+'s']:[...subjectDrafts(data,field),'']}).data;
  assert.deepEqual(subjectDrafts(data,field),['Business Information Technology','']);
  assert.deepEqual(educationPayload(data)[field+'s'],['Business Information Technology']);
  const values=subjectDrafts(data,field);values[0]='changed';assert.equal(data[field+'s'][0],'Business Information Technology');
 }
});
test('draft subjects preserve whitespace and duplicates until payload normalization',()=>{
 const data={majors:['  Business Information Technology  ','business information technology',''],minor:'Applied Statistics '};
 assert.deepEqual(subjectDrafts(data,'major'),data.majors);assert.deepEqual(subjectDrafts(data,'minor'),['Applied Statistics ']);
 assert.deepEqual(educationPayload(data).majors,['Business Information Technology']);assert.equal(educationPayload(data).minor,'Applied Statistics');
});
