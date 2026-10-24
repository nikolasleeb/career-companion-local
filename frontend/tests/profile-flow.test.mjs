import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const review=ts.transpileModule(readFileSync(new URL('../src/answerReview.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const source=ts.transpileModule(readFileSync(new URL('../src/profileFlow.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText.replace('./answerReview','data:text/javascript;base64,'+Buffer.from(review).toString('base64'));
const {restoreProfile,profileHome,setupTarget,storyInScope,sectionStatus}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const sections=[{id:'education',status:'complete',confirmed_count:1},{id:'employment',status:'empty'},{id:'project',status:'needs_review',draft_count:2},{id:'volunteering',status:'not_started'},{id:'skills',status:'complete'},{id:'coursework',status:'complete'}];
test('first entry opens the first unfinished section without adding a second checklist',()=>{assert.deepEqual(restoreProfile(null,sections).open,['project']);assert.deepEqual(setupTarget(sections),{pane:'project',heading:'profile-project-title'});});
test('coursework remains its own requirement but focuses its parent education pane',()=>{const ready=sections.map(s=>({...s,status:s.id==='coursework'?'not_started':'complete'}));assert.deepEqual(setupTarget(ready),{pane:'education',heading:'profile-coursework-title'});assert.deepEqual(restoreProfile(null,ready).open,['education']);});
test('all ready sections focus the finish action, without changing completion',()=>{assert.deepEqual(setupTarget(sections.map(s=>({...s,status:'complete'}))),{pane:'',heading:'profile-finish-title'});});
test('account presentation state restores multiple panes, story filter and return position',()=>{const saved={version:1,view:'stories',scope:{experienceId:'my-record'},open:['education','project'],returnY:900};assert.deepEqual(restoreProfile(saved,sections),saved);assert.deepEqual(restoreProfile(null,sections).scope,{});});
test('invalid storage cannot introduce arbitrary panes, view or scroll state',()=>{const restored=restoreProfile({version:1,view:'jobs',scope:{experienceId:7},open:['unknown','project','project'],returnY:-5},sections);assert.equal(restored.view,'resume');assert.deepEqual(restored.open,['project']);assert.equal(restored.returnY,0);assert.deepEqual(restored.scope,{});assert.deepEqual(restoreProfile({version:99,open:['skills']},sections).open,['project']);});
test('an intentionally closed set of panes is preserved on reload',()=>{assert.deepEqual(restoreProfile({version:1,open:[]},sections).open,[]);});
test('related stories are filtered by exact experience identity',()=>{assert.ok(storyInScope({data:{experience_id:'a'}},{experienceId:'a'}));assert.ok(!storyInScope({data:{experience_id:'b'}},{experienceId:'a'}));});
test('standalone project stories exclude drafts, motivations, linked field evidence and unrelated categories',()=>{const data={status:'confirmed',answer_kind:'experience',category:'project'};assert.ok(storyInScope({data},{standalone:true}));for(const change of [{status:'draft'},{answer_kind:'motivation'},{experience_id:'record'},{backed_fields:{description:'old linked detail'}},{category:'employment'}])assert.ok(!storyInScope({data:{...data,...change}},{standalone:true}));});
test('section statuses distinguish needs review from reviewed entries and explicit empty decisions',()=>{assert.equal(sectionStatus(sections[0]),'1 reviewed entry');assert.equal(sectionStatus(sections[1]),'Nothing to add yet');assert.equal(sectionStatus(sections[2]),'2 drafts need review');assert.match(sectionStatus({id:'education',status:'required'}),/Required/);});

test('an empty student Profile begins with required education',()=>{assert.deepEqual(restoreProfile(null,[{id:'education',status:'required'},{id:'employment',status:'not_started'}]).open,['education']);});

test('unfinished targeting follows the visual order, including coursework inside Education',()=>{assert.deepEqual(setupTarget([{id:'employment',status:'not_started'},{id:'coursework',status:'not_started'},{id:'education',status:'complete'}]),{pane:'education',heading:'profile-coursework-title'});});
const {setupBlockers}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
test('finish area names unfinished acknowledgements and the exact draft needing review',()=>{
 const sections=[{id:'education',title:'Education',status:'complete'},{id:'volunteering',title:'Volunteering',status:'not_started'},{id:'skills',title:'Skills',status:'needs_review',draft_count:1},{id:'coursework',status:'complete'}];
 const result=setupBlockers(sections,[{data:{category:'skills',title:'Certifications',confirmed:false}},{data:{category:'skills',title:'Programming',confirmed:true}}]);
 assert.deepEqual(result.map(v=>v.id),['volunteering','skills']);assert.match(result[0].message,/Nothing to add yet/);assert.equal(result[1].message,'Review and confirm: Certifications.');assert.equal(result[1].heading,'profile-skills-title');
});
test('finish explanations follow server states and route coursework to Education',()=>{
 assert.deepEqual(setupBlockers(sections.map(s=>({...s,status:'empty'})),[]),[]);
 const result=setupBlockers([{id:'coursework',title:'Coursework',status:'needs_review',draft_count:1}],[]);
 assert.equal(result[0].pane,'education');assert.equal(result[0].heading,'profile-coursework-title');assert.match(result[0].message,/source findings/);
});
const {finishSetupReason}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
test('finish tooltip lists actual blockers and disappears when none remain',()=>{
 const blockers=setupBlockers([{id:'volunteering',title:'Volunteering',status:'not_started'},{id:'skills',status:'needs_review',draft_count:1}],[{data:{category:'skills',title:'Certifications',confirmed:false}}]);
 const reason=finishSetupReason(blockers,'');assert.match(reason,/Volunteering.*Nothing to add yet/);assert.match(reason,/Skills & certifications.*Certifications/);assert.ok(!reason.includes('eligibility'));assert.equal(finishSetupReason([],''),'');assert.match(finishSetupReason([],'Saving progress'),/Please wait: Saving progress/);
});

 test('explicit Profile navigation exits stories and clears its filter while preserving expanded sections',()=>{
 const saved={version:1,view:'stories',scope:{experienceId:'project-id'},open:['education','project'],returnY:900};
 const home=profileHome(restoreProfile(saved,sections));
 assert.deepEqual(home,{...saved,view:'resume',scope:{},returnY:0});
 assert.equal(saved.view,'stories');
 assert.equal(restoreProfile(saved,sections).view,'stories');
 assert.deepEqual(profileHome(home),home);
 });

test('a shared story is visible under either role without being classified standalone',()=>{const data={answer_kind:'experience',status:'confirmed',experience_id:'a',experience_ids:['a','b'],category:'project'};assert.ok(storyInScope({data},{experienceId:'a'}));assert.ok(storyInScope({data},{experienceId:'b'}));assert.ok(!storyInScope({data},{standalone:true}));assert.ok(!storyInScope({data},{experienceId:'c'}));});
