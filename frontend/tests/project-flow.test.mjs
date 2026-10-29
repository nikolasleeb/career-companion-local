import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/projectFlow.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {analyzeProject,githubLink}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const selection={sourceId:'project',paths:['README.md','analysis.ipynb'],experienceId:'profile-project',mode:'custom'};
test('Analyze downloads selected files before exactly one explicit AI task',async()=>{
 const events=[];
 const value=await analyzeProject(selection,{api:async(path,method,body)=>{events.push({path,method,body});return {id:'snapshot'};},snapshotReady:s=>events.push({saved:s.id}),phase:()=>{},task:async(path,body)=>{events.push({path,body});return {draft:{id:'review'},analysis:{id:'result'}};}});
 assert.equal(events[0].path,'/project-sources/project/select');assert.deepEqual(events[0].body,{file_paths:selection.paths,experience_id:'profile-project'});
 assert.deepEqual(events[1],{saved:'snapshot'});assert.equal(events[2].path,'/project-snapshots/snapshot/analyze');assert.equal(events[2].body.mode,'custom');assert.ok(events[2].body.request_token);
 assert.equal(value.draft.id,'review');assert.equal(value.snapshot.id,'snapshot');
});
test('download failure never starts AI and an existing snapshot skips downloading',async()=>{
 let paid=0;const io={api:async()=>{throw Error('Unavailable file');},snapshotReady:()=>{},phase:()=>{},task:async()=>{paid++;return {draft:{id:'review'}};}};
 await assert.rejects(()=>analyzeProject(selection,io),/Unavailable/);assert.equal(paid,0);
 const value=await analyzeProject({...selection,snapshot:{id:'retained'}},io);assert.equal(paid,1);assert.equal(value.snapshot.id,'retained');
});
test('AI failure retains the downloaded snapshot for an explicit retry',async()=>{
 let retained;await assert.rejects(()=>analyzeProject(selection,{api:async()=>({id:'saved'}),snapshotReady:s=>retained=s,phase:()=>{},task:async()=>{throw Error('Provider unavailable');}}),/Provider/);assert.equal(retained.id,'saved');
});
test('empty file selections cannot start a provider request; only GitHub HTTPS links load a list',async()=>{
 await assert.rejects(()=>analyzeProject({...selection,paths:[]},{api:async()=>assert.fail(),task:async()=>assert.fail(),phase:()=>{},snapshotReady:()=>{}}),/Choose/);
 assert.equal(githubLink('https://github.com/owner/project'),true);assert.equal(githubLink('https://github.com/owner/project/blob/main/test.py'),true);
 for(const url of ['https://github.com/owner','https://github.com.evil.test/a/b','http://127.0.0.1/a/b','https://user:password@github.com/a/b'])assert.equal(githubLink(url),false);
});
test('unreadable selected files are disclosed before any AI request',async()=>{
 let calls=0,retained;await assert.rejects(()=>analyzeProject(selection,{api:async()=>({id:'partial',data:{excluded:[{file_path:'report.docx',reason:'Unreadable'}]}}),snapshotReady:s=>retained=s,phase:()=>{},task:async()=>{calls++;}}),/Some selected files/);assert.equal(calls,0);assert.equal(retained.id,'partial');
});

const {savedProjectForRecord}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const {projectLinks}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('multiple project links preserve the primary and require the entire source set for saved reuse',()=>{
 const links=['https://github.com/example/original','https://github.com/example/extension'];
 assert.deepEqual(projectLinks({project_url:links[0],project_urls:[links[0]+'/',links[1],'']}),links);
 const request={id:'click',experienceId:'project',url:links[0],urls:links,title:'Extended project'};
 const old={id:'old-one-repo',data:{experience_id:'project',url:links[0]}};
 const combined={id:'combined',data:{experience_id:'project',url:links[0],urls:[links[1],links[0]+'/']}};
 assert.equal(savedProjectForRecord([old],request),undefined);
 assert.equal(savedProjectForRecord([old,combined],request).id,'combined');
 assert.equal(savedProjectForRecord([{...combined,data:{...combined.data,archived:true}}],request),undefined);
});
const {latestProjectRecovery}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('returning to Profile restores saved analysis and review without any provider action',()=>{
 const library={tasks:[{id:'archived-task',snapshot_id:'archived',status:'completed'},{id:'task',snapshot_id:'saved',status:'running'}],snapshots:[{id:'archived',data:{archived:true}},{id:'saved',data:{}}],drafts:[{id:'manual',data:{snapshot_id:'saved',manual_source:true}},{id:'review',data:{snapshot_id:'saved'}}]};
 const value=latestProjectRecovery(library);assert.equal(value.snapshot.id,'saved');assert.equal(value.task.id,'task');assert.equal(value.draft.id,'review');
 assert.equal(latestProjectRecovery({...library,tasks:[]}),null);
});
test('Profile analysis reuses only the matching owned record/link snapshot and excludes archives',()=>{
 const request={id:'click-1',experienceId:'project-a',url:'https://github.com/example/project/',title:'Project'};
 const rows=[{id:'archived',data:{experience_id:'project-a',url:request.url,archived:true}},{id:'different-record',data:{experience_id:'project-b',url:request.url}},{id:'old-link',data:{experience_id:'project-a',url:'https://github.com/example/old'}},{id:'saved',data:{experience_id:'project-a',url:'https://github.com/example/project'}}];
 assert.equal(savedProjectForRecord(rows,request).id,'saved');assert.equal(savedProjectForRecord(rows.slice(0,3),request),undefined);
});
const {scopedProjectLibrary,projectMaterialsStatus}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const materialsLibrary={snapshots:[{id:'one',data:{experience_id:'a',source_id:'s1',url:'https://github.com/example/a'}},{id:'two',data:{experience_id:'b',source_id:'s2'}},{id:'other',data:{source_id:'s3'}}],sources:[{id:'s1'},{id:'s2'},{id:'s3'}],analyses:[{data:{snapshot_id:'one'}},{data:{snapshot_id:'two'}}],drafts:[{data:{snapshot_id:'one',status:'reviewed'}},{data:{snapshot_id:'two',status:'draft'}}],tasks:[{id:'task',snapshot_id:'two',status:'running'}]};
test('each materials dialog isolates its project snapshots, findings and running tasks',()=>{
 const a=scopedProjectLibrary(materialsLibrary,'a');assert.deepEqual(a.snapshots.map(r=>r.id),['one']);assert.deepEqual(a.sources.map(r=>r.id),['s1']);assert.equal(a.tasks.length,0);assert.equal(a.analyses.length,1);assert.equal(a.drafts.length,1);
 assert.deepEqual(scopedProjectLibrary(materialsLibrary,'').snapshots.map(r=>r.id),['other']);
});
test('card actions distinguish running, reviewed, draft and unanalyzed materials',()=>{
 assert.deepEqual(projectMaterialsStatus(materialsLibrary,'a',['https://github.com/example/a']),{label:'View analysis',status:'Materials analyzed'});
 assert.equal(projectMaterialsStatus(materialsLibrary,'b').status,'Analysis running');
 assert.equal(projectMaterialsStatus({...materialsLibrary,tasks:[]},'b').label,'View analysis');
 assert.equal(projectMaterialsStatus(materialsLibrary,'new').label,'Analyze project with OpenAI');
 assert.equal(projectMaterialsStatus(materialsLibrary,'a',['https://github.com/example/changed']).label,'Analyze project with OpenAI');
});

test('other materials retain orphaned or non-project source history after a Profile record is removed',()=>{assert.deepEqual(scopedProjectLibrary(materialsLibrary,'',['a']).snapshots.map(r=>r.id),['two','other']);});

test('analysis-only completion carries no answer draft and does not dispatch when reopening',async()=>{
 let calls=0;
 const result=await analyzeProject({snapshot:{id:'saved',data:{}},paths:[],experienceId:'project',mode:'economy'},{api:async()=>{throw Error('No downloads for saved files');},snapshotReady:()=>{},phase:()=>{},task:async()=>{calls++;return {analysis:{id:'analysis',data:{snapshot_id:'saved'}},draft:null};}});
 assert.equal(calls,1);assert.equal(result.draft,null);
 const library={snapshots:[{id:'saved',data:{experience_id:'project'}}],analyses:[result.analysis],drafts:[],tasks:[{id:'done',snapshot_id:'saved',status:'completed'}]};
 assert.equal(latestProjectRecovery(library).draft,null);
 assert.deepEqual(projectMaterialsStatus(library,'project'),{label:'View analysis',status:'Materials analyzed'});
 assert.equal(calls,1);
});

const {projectLinkDrafts}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('project link drafts retain added empty rows, partial text and duplicates until save',()=>{
 const first='https://github.com/example/original';const data={project_url:first,project_urls:[first,'','https://github.com/example/ext ' ,first]};
 assert.deepEqual(projectLinkDrafts(data),data.project_urls);assert.deepEqual(projectLinks(data),[first,'https://github.com/example/ext']);
 const rows=projectLinkDrafts(data);rows[0]='changed';assert.equal(data.project_urls[0],first);
 assert.deepEqual(projectLinkDrafts({project_url:first,project_urls:[]}),[first]);assert.deepEqual(projectLinkDrafts({project_url:first,project_urls:['https://example.test/extra','']}),[first,'https://example.test/extra','']);assert.deepEqual(projectLinkDrafts({project_urls:['']}),['']);
});

test('ZIP-based projects recover uploaded materials with reference links after reopening',()=>{
 const saved={id:'zip-snapshot',data:{provider:'mixed',experience_id:'aws-project',urls:['https://example.org/aws-project']}};
 const request={id:'open-again',experienceId:'aws-project',url:'',urls:[],title:'AWS project'};
 assert.equal(savedProjectForRecord([saved],request).id,'zip-snapshot');
 assert.equal(savedProjectForRecord([saved],{...request,experienceId:'another-project'}),undefined);
 assert.equal(savedProjectForRecord([{...saved,data:{...saved.data,archived:true}}],request),undefined);
 assert.equal(savedProjectForRecord([saved],{...request,url:'https://github.com/example/new-project'}),undefined);
});
test('mixed sources compare every saved reference without discarding non-GitHub links',()=>{
 const urls=['https://github.com/example/project','https://example.org/report'];
 const request={id:'open',experienceId:'p',url:urls[0],urls,title:'Project'};
 const row={id:'mixed',data:{provider:'mixed',experience_id:'p',urls}};
 assert.equal(savedProjectForRecord([row],request).id,'mixed');
 assert.equal(savedProjectForRecord([row],{...request,urls:[urls[0],'https://example.org/different-report']}),undefined);
});

test('pending ZIP previews remain in their own project library before analysis',()=>{
 const library={snapshots:[],sources:[{id:'upload-a',data:{experience_id:'a',available_files:[{file_path:'main.py',text:'fixture'}]}},{id:'upload-b',data:{experience_id:'b',available_files:[]}}]};
 assert.deepEqual(scopedProjectLibrary(library,'a').sources.map(r=>r.id),['upload-a']);
});

const {selectedProjectFiles}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('adding ZIPs or links preserves exclusions, including an entirely unchecked selection',()=>{
 const initial=[{file_path:'zip/a.py',suggested:true},{file_path:'zip/b.py',suggested:true}],expanded=[...initial,{file_path:'README.md',suggested:true}];
 assert.deepEqual(selectedProjectFiles([],[],initial),['zip/a.py','zip/b.py']);
 assert.deepEqual(selectedProjectFiles(['zip/a.py'],initial.map(f=>f.file_path),expanded),['zip/a.py']);
 assert.deepEqual(selectedProjectFiles([],initial.map(f=>f.file_path),expanded),[]);
});
