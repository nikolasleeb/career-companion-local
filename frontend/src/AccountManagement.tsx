import React,{useEffect,useRef,useState} from 'react';
import './settingsManagement.css';
export function BackupControls({call,download,onRefresh}:{call:any;download:()=>Promise<any>;onRefresh:()=>Promise<any>}){
 const input=useRef<HTMLInputElement>(null),[filename,setFilename]=useState(''),[busy,setBusy]=useState(false),[notice,setNotice]=useState(''),[error,setError]=useState('');
 async function run(fn:()=>Promise<any>){setBusy(true);setError('');setNotice('');try{await fn();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 return <section className="panel top-space"><h2>Backup and restore</h2><p>Export your Profile, source documents, saved versions, practice and assessment results. Store the downloaded personal information deliberately.</p><div className="backup-controls"><div><button className="button secondary" disabled={busy} onClick={()=>void run(download)}>Download account backup ↓</button><p className="small muted">API credentials and private-answer vault data are excluded.</p></div><div><button className="button secondary" disabled={busy} onClick={()=>input.current?.click()}>Import account backup ↑</button><input ref={input} hidden type="file" accept=".json" aria-label="Choose account backup" onChange={e=>{const file=e.target.files?.[0];if(file){setFilename(file.name);void run(async()=>{const form=new FormData();form.append('file',file);const result=await call('/account/import','POST',form);await onRefresh();setNotice(result.message);});}e.target.value='';}}/><p className="small muted" aria-live="polite">{filename||'Choose a JSON backup'} · up to 256 MB</p></div></div><p className="small muted">Import adds records with new IDs and preserves existing records. It restores profile details and saved AI choices.</p>{busy&&<p role="status">Working on your backup…</p>}{notice&&<p role="status">{notice}</p>}{error&&<p role="alert">{error}</p>}</section>;
}
const cleanupGroups=[
 {id:'profile',title:'Profile & Career Goals',categories:['personal','profile:education','profile:employment','profile:project','profile:volunteering','profile:skills','profile:coursework','profile:certifications','supporting','goals']},
 {id:'private',title:'Work Styles & private answers',categories:['work_assessments','work_summary','private']},
 {id:'files',title:'Files & documents',categories:['uploads','documents','document_conversations']},
 {id:'resources',title:'Saved Resources & conversations',categories:['careers','plans','coach','interviews','skills']},
 {id:'jobs',title:'Job Search history',categories:['jobs']},
];
export function AccountCleanup({call,download}:{call:any;download:()=>Promise<any>}){
 const [inventory,setInventory]=useState<any>(null),[categories,setCategories]=useState<string[]>([]),[opened,setOpened]=useState<Record<string,boolean>>({}),[start,setStart]=useState(''),[end,setEnd]=useState(''),[preview,setPreview]=useState<any>(null),[receipt,setReceipt]=useState<any>(null),[password,setPassword]=useState(''),[confirmation,setConfirmation]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const previewHeading=useRef<HTMLHeadingElement>(null);const datesValid=!!start&&!!end&&start<=end;
 async function load(){const value=await call('/account/cleanup');setInventory(value);if(value.last_operation_id)setReceipt(await call('/account/cleanup/'+value.last_operation_id));}
 useEffect(()=>{void load().catch(e=>setError(e.message));},[]);
 useEffect(()=>{if(!receipt?.files_pending)return;const timer=setTimeout(()=>void call('/account/cleanup/'+receipt.operation_id).then(setReceipt).catch((e:Error)=>setError(e.message)),3000);return()=>clearTimeout(timer);},[receipt]);
 function discardPreview(source?:string){if(!source||preview?.source===source)setPreview(null);setPassword('');setConfirmation('');setError('');}
 async function show(source:'information'|'applications',action:'archive'|'delete'){
  if(source==='applications'&&!datesValid)return;
  setBusy(true);setError('');setPreview(null);setPassword('');setConfirmation('');
  try{const body=source==='applications'?{action,categories:['applications'],application_scope:action==='delete'?'all':'current',start,end,timezone:Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC'}:{action:'delete',categories};const result=await call('/account/cleanup/preview','POST',body);setPreview({...result,source});requestAnimationFrame(()=>previewHeading.current?.focus());}
  catch(e){setError((e as Error).message);}finally{setBusy(false);}
 }
 async function apply(){
  setBusy(true);setError('');
  try{const result=await call('/account/cleanup/apply','POST',{preview_id:preview.preview_id,confirmation:preview.action==='delete'?confirmation:'CONFIRM',password:preview.action==='delete'?password:''});setReceipt(result);if(preview.source==='information')setCategories([]);setPreview(null);setPassword('');setConfirmation('');await load();}
  catch(e){setError((e as Error).message);setPassword('');}finally{setBusy(false);}
 }
 function review(source:string){
  if(preview?.source!==source)return null;
  const applications=source==='applications',count=preview.application_count||0;
  const affected=preview.records.length+preview.personal_fields+preview.private_sections+Object.values(preview.search_history_counts||{}).reduce((a:number,b:any)=>a+Number(b),0);
  return <div className="cleanup-preview">
   <h3 ref={previewHeading} tabIndex={-1}>{applications?(preview.action==='archive'?'Review application archive':'Review application deletion'):'Review selected deletion'}</h3>
   {applications?<p><strong>{count} matching {count===1?'application':'applications'}</strong> · {preview.application_range.start} through {preview.application_range.end}. {preview.action==='delete'?'Includes current and archived applications.':'Already archived applications stay unchanged.'}</p>:<p>{preview.records.length} records · {preview.personal_fields} personal fields · {preview.private_sections} private sections.</p>}
   {(!affected||applications&&!count)&&<p className="notice">{applications?'No applications match this date range. Nothing will change.':'No saved information matches this selection. Nothing will change.'}</p>}
   {preview.action==='delete'?<><p className="small">{preview.retained_copies_notice}</p><p className="small">{preview.preserved_documents_notice} {preview.files.length} files will be removed; {preview.preserved_shared_records.length} shared records/files stay saved.</p><p className="small">{preview.backup_notice} Save unfinished work first: browser views and recovery drafts refresh after cleanup.</p></>:<p className="small">Statuses, dates, documents, offers and conversations stay saved. Archived applications leave current lists and charts; Career Coach can still retrieve them as historical records.</p>}
   <p className="small muted">This preview expires after ten minutes. Changes to saved information require a fresh preview.</p>
   {preview.blockers.map((b:string)=><p role="alert" key={b}>{b}</p>)}
   {!!affected&&<ul className="cleanup-preview-list">{[...preview.records,...(preview.private_records||[])].map((r:any)=><li key={r.kind+':'+r.id}>{r.kind==='application'?<><strong>{r.company||'Application'}</strong>{r.role&&' — '+r.role}<div className="cleanup-application-meta"><span>{r.date_basis}: {r.effective_date}</span><span>{r.archived?'Archived':'Current'}</span>{r.status&&<span>{r.status.replaceAll('_',' ')}</span>}</div></>:<>{r.title} <small>({r.kind.replaceAll('_',' ')})</small></>}</li>)}</ul>}
   {Object.values(preview.search_history_counts||{}).some(Boolean)&&<p className="small">Daily-check history and delivery/cache markers to remove: {Object.values(preview.search_history_counts).reduce((a:any,b:any)=>a+b,0) as number}</p>}
   {preview.personal_field_names?.length>0&&<p className="small">Personal fields: {preview.personal_field_names.join(', ')}</p>}
   {preview.preserved_records?.length>0&&<details><summary>Shared records kept</summary><ul>{preview.preserved_records.map((r:any)=><li key={r.id}>{r.title} ({r.kind})</li>)}</ul></details>}
   {preview.action==='delete'&&!!affected&&<><button className="text-button" disabled={busy} onClick={()=>void download().catch((e:Error)=>setError(e.message))}>Download ordinary account backup first ↓</button><div className="form-grid"><label>Type DELETE to confirm<input value={confirmation} autoComplete="off" onChange={e=>setConfirmation(e.target.value)}/></label><label>Your account password<input type="password" value={password} autoComplete="current-password" onChange={e=>setPassword(e.target.value)}/></label></div></>}
   <div className="cleanup-buttons"><button className="button primary" disabled={busy||!affected||applications&&!count||preview.blockers.length>0||preview.action==='delete'&&(confirmation!=='DELETE'||!password)} onClick={()=>void apply()}>{preview.action==='archive'?'Confirm archive':applications?'Permanently delete matching applications':'Permanently delete selected information'}</button><button className="button secondary" disabled={busy} onClick={()=>discardPreview()}>Cancel</button></div>
  </div>;
 }
 return <>
  <section className="panel top-space account-cleanup"><h2>Manage saved information</h2><p>Choose the information to remove. Your account, API connections, preferences and cost history stay saved.</p>
   {!inventory&&!error&&<p role="status">Loading saved information…</p>}
   {inventory?.blockers.map((b:string)=><p className="notice" key={b}>{b}</p>)}
   <div className="cleanup-groups">{cleanupGroups.map(group=>{
    const items=(inventory?.categories||[]).filter((c:any)=>group.categories.includes(c.id));const count=items.reduce((n:number,c:any)=>n+c.count,0),selected=items.filter((c:any)=>categories.includes(c.id)).length;
    return <section className="cleanup-group" key={group.id}><h3><button type="button" className="cleanup-group-heading" disabled={!count||busy} aria-expanded={!!opened[group.id]} aria-controls={'cleanup-group-'+group.id} onClick={()=>setOpened(v=>({...v,[group.id]:!v[group.id]}))}><span>{group.title}<small>{count?count+(count===1?' saved item':' saved items')+(selected?' · '+selected+' categories selected':''):'Nothing saved'}</small></span><span aria-hidden="true">{opened[group.id]?'−':'+'}</span></button></h3><div id={'cleanup-group-'+group.id} hidden={!opened[group.id]}><div className="management-choice-grid">{items.map((c:any)=><label className={'check-line'+(!c.count?' empty-cleanup-category':'')} key={c.id}><input type="checkbox" disabled={busy||!c.count} checked={categories.includes(c.id)} onChange={e=>{setCategories(e.target.checked?[...categories,c.id]:categories.filter(v=>v!==c.id));discardPreview('information');}}/>{c.label} · {c.count}</label>)}</div></div></section>;
   })}</div>
   <div className="cleanup-buttons"><button className="button secondary" disabled={busy||!categories.length} onClick={()=>void show('information','delete')}>Review selected deletion</button>{!!categories.length&&<span className="small muted" role="status">{categories.length} {categories.length===1?'category':'categories'} selected</span>}</div>
   {review('information')}
  </section>
  <section className="panel top-space account-cleanup application-range-cleanup" aria-labelledby="manage-applications-title"><h2 id="manage-applications-title">Manage applications</h2><p>Choose a date range, then review the applications to archive or permanently delete.</p>
   <div className="application-cleanup-dates"><label>From<input type="date" required disabled={busy} value={start} onChange={e=>{setStart(e.target.value);discardPreview('applications');}}/></label><label>Through<input type="date" required disabled={busy} value={end} min={start||undefined} onChange={e=>{setEnd(e.target.value);discardPreview('applications');}}/></label></div>
   <p className="small muted">Both dates are included. Date applied is used, otherwise Date added in your displayed time zone.</p>
   {!start||!end?<p className="small muted">Choose both dates to review matching applications.</p>:start>end?<p role="alert">Choose a Through date on or after From.</p>:null}
   <div className="cleanup-buttons"><button className="button secondary" disabled={busy||!datesValid} onClick={()=>void show('applications','archive')}>Archive applications</button><button className="button secondary cleanup-delete-button" disabled={busy||!datesValid} onClick={()=>void show('applications','delete')}>Delete applications</button></div>
   <p className="small muted">Archive affects current applications. Delete includes current and archived applications in the date range. You’ll review matches before confirming.</p>
   {review('applications')}
  </section>
  {receipt&&<div className="notice" role="status">Last cleanup: {receipt.action} · {receipt.application_range?receipt.application_count+(receipt.application_count===1?' application':' applications'):receipt.records_affected+' records, '+(receipt.personal_fields||0)+' personal fields and '+(receipt.private_sections||0)+' private sections'} affected. {receipt.files_pending?'Finishing file removal ('+receipt.files_pending+' pending). Saved records are already unavailable.':'File removal is complete.'}{receipt.file_removal?.some((r:any)=>r.error)&&<p>The server will retry pending file removal. No paid request is involved.</p>}</div>}
  {error&&<p role="alert">{error}</p>}
 </>;
}
