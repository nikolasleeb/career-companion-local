/** One explicit AI action: fetch selected files, save the snapshot, then analyze it. */
type Selection={sourceId?:string;snapshot?:any;paths:string[];experienceId:string;mode:string};
type IO={api:(path:string,method?:string,body?:any)=>Promise<any>;task:(path:string,body:any)=>Promise<any>;snapshotReady:(snapshot:any)=>void;phase:(value:string)=>void};
export function githubLink(value:string){try{const u=new URL(value);const parts=u.pathname.split('/').filter(Boolean);return u.protocol==='https:'&&u.hostname==='github.com'&&!u.username&&!u.password&&parts.length>=2;}catch{return false;}}
export async function analyzeProject(selection:Selection,io:IO){
 let snapshot=selection.snapshot;
 if(!snapshot){
  if(!selection.sourceId||!selection.paths.length)throw new Error('Choose at least one project file.');
  io.phase('Preparing selected files…');
  snapshot=await io.api('/project-sources/'+selection.sourceId+'/select','POST',{file_paths:selection.paths,experience_id:selection.experienceId});
  io.snapshotReady(snapshot);
  if(snapshot.data?.excluded?.length)throw new Error('Some selected files could not be prepared: '+snapshot.data.excluded.map((f:any)=>f.file_path).join(', ')+'. No OpenAI request was started. Retry preparing the files or explicitly analyze the available files.');
 }
 io.phase('Analyzing project…');
 const result=await io.task('/project-snapshots/'+snapshot.id+'/analyze',{mode:selection.mode,request_token:crypto.randomUUID()});
 io.phase('Analysis complete');
 return {snapshot,...result};
}

// Editing must retain empty rows, partial URLs and cursor positions.
export function projectLinkDrafts(data:any):string[]{
 const rows:string[]=Array.isArray(data?.project_urls)?[...data.project_urls]:[];
 const key=(v:string)=>v.trim().replace(/\/+$/,'');
 if(data?.project_url&&!rows.some(v=>key(v)===key(data.project_url)))rows.unshift(data.project_url);
 return rows;
}
export function projectLinks(data:any):string[]{const seen=new Set<string>();return [data?.project_url,...(data?.project_urls||[])].filter((v):v is string=>typeof v==='string'&&!!v.trim()).map(v=>v.trim()).filter(v=>{const key=v.replace(/\/+$/,'');if(seen.has(key))return false;seen.add(key);return true;});}
export type ProfileProjectRequest={id:string;experienceId:string;url:string;urls?:string[];title:string};
export function savedProjectForRecord(snapshots:any[],request:ProfileProjectRequest){const all=request.urls?.length?request.urls:[request.url],supported=all.filter(githubLink),links=(supported.length?supported:all).map(v=>v.replace(/\/+$/,'')).sort();return snapshots.find(row=>!row.data.archived&&row.data.experience_id===request.experienceId&&JSON.stringify((row.data.urls?.length?row.data.urls:[row.data.url||'']).map((v:string)=>v.replace(/\/+$/,'')).sort())===JSON.stringify(links));}

export function latestProjectRecovery(library:any){
 for(const task of library.tasks||[]){
  const snapshot=library.snapshots.find((row:any)=>row.id===task.snapshot_id&&!row.data.archived);
  if(snapshot)return {snapshot,task,draft:library.drafts.find((row:any)=>row.data.snapshot_id===snapshot.id&&!row.data.manual_source)||null};
 }
 return null;
}

// Each Profile dialog sees only snapshots assigned to its own project (or unlinked materials).
export function scopedProjectLibrary(library:any,experienceId:string,projectIds?:string[]){
 const snapshots=(library.snapshots||[]).filter((r:any)=>(r.data.experience_id||'')===experienceId||experienceId===''&&projectIds!==undefined&&!projectIds.includes(r.data.experience_id)),ids=new Set(snapshots.map((r:any)=>r.id)),sourceIds=new Set(snapshots.map((r:any)=>r.data.source_id));
 return {...library,snapshots,sources:(library.sources||[]).filter((r:any)=>sourceIds.has(r.id)),analyses:(library.analyses||[]).filter((r:any)=>ids.has(r.data.snapshot_id)),drafts:(library.drafts||[]).filter((r:any)=>ids.has(r.data.snapshot_id)),tasks:(library.tasks||[]).filter((r:any)=>ids.has(r.snapshot_id))};
}
export function projectMaterialsStatus(library:any,experienceId:string,urls:string[]=[]){
 const scoped=scopedProjectLibrary(library,experienceId),request={id:'',experienceId,url:urls[0]||'',urls,title:''};
 const snapshots=scoped.snapshots.filter((r:any)=>!r.data.archived);
 const pending=scoped.tasks.find((t:any)=>['queued','running'].includes(t.status)&&snapshots.some((r:any)=>r.id===t.snapshot_id));
 const snapshot=pending?snapshots.find((r:any)=>r.id===pending.snapshot_id):urls.length?savedProjectForRecord(snapshots,request):snapshots[0];
 const draft=scoped.drafts.find((r:any)=>r.data.snapshot_id===snapshot?.id&&!r.data.manual_source),task=scoped.tasks.find((t:any)=>t.snapshot_id===snapshot?.id);
 if(pending)return {label:'View analysis',status:'Analysis running'};
 if(snapshot&&scoped.analyses.some((r:any)=>r.data.snapshot_id===snapshot.id))return {label:'View analysis',status:'Materials analyzed'};
 if(draft)return {label:'View analysis',status:draft.data.status==='reviewed'?'Analysis reviewed':'Findings rejected'};
 if(task&&['failed','interrupted'].includes(task.status))return {label:'View analysis',status:'Analysis '+task.status};
 if(snapshot&&scoped.analyses.some((r:any)=>r.data.snapshot_id===snapshot.id))return {label:'View analysis',status:'Analysis saved'};
 return {label:'Analyze project with OpenAI',status:snapshot?'Files saved':''};
}
