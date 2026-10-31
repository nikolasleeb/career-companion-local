import React,{useEffect,useState} from 'react';
import {useUnsavedWarning} from './WorkspaceDialog';
import './linkedProjectEvidence.css';

export function LinkedProjectEvidence({session,busy,blocked,onApply,call}:{call:(path:string)=>Promise<any>;session:any;busy:boolean;blocked:boolean;onApply:(placements:any[])=>Promise<any>}){
 const [open,setOpen]=useState(false),[rows,setRows]=useState<any[]>([]),[loading,setLoading]=useState(false),[error,setError]=useState(''),[choices,setChoices]=useState<Record<string,any>>({}),[changed,setChanged]=useState(false);
 const saved=session.current?.data.snapshot?.linked_project_placements||(!session.current?session.data.linked_project_placements:[])||[];
 const key=(row:any)=>row.project_id+':'+row.item_id;
 useUnsavedWarning(changed);
 useEffect(()=>{setChoices(Object.fromEntries(saved.map((c:any)=>[key(c),c])));setChanged(false);setOpen(false);setRows([]);setError('');},[session.id,session.current?.id]);
 async function load(){setOpen(true);setLoading(true);setError('');try{const value=await call('/resume-conversations/'+session.id+'/linked-evidence');setRows(value);}catch(e){setError((e as Error).message);}finally{setLoading(false);}}
 function change(row:any,value:any){setChanged(true);setChoices(old=>({...old,[key(row)]:{project_id:row.project_id,item_id:row.item_id,placement:'project',employment_id:'',replace_overlaps:false,...old[key(row)],...value,source_fingerprint:row.source_fingerprint}}));}
 const stale=rows.some(row=>choices[key(row)]&&choices[key(row)].source_fingerprint!==row.source_fingerprint);
 const missing=Object.values(choices).some((c:any)=>!rows.some(row=>key(row)===key(c)));
 const unavailableRole=rows.some(row=>{const c=choices[key(row)];return c?.placement==='employment'&&!row.jobs.some((j:any)=>j.id===c.employment_id);});
 const overlapPending=rows.some(row=>{const c=choices[key(row)];return c?.placement==='employment'&&row.jobs.find((j:any)=>j.id===c.employment_id)?.overlaps.length&&!c.replace_overlaps;});
 return <section className="linked-project-evidence" aria-label="Linked project evidence">
  <div className="linked-evidence-heading"><h3>Linked project evidence</h3><button type="button" className="button secondary" disabled={busy||loading} aria-expanded={open} onClick={()=>open?setOpen(false):load()}>{open?'Hide placement review':'Review placements · no AI'}</button></div>
  <p className="small">Use confirmed project details under a linked job, as a standalone project, or omit them. Profile records stay unchanged. Choose the exact role for projects linked to several jobs.</p>
  {open&&<><p className="small">Applying placements updates this draft and its PDF without AI. The next AI draft update can select and refine these eligible bullets for the posting. Previous revisions keep their original sources.</p>
   {loading&&<p role="status">Loading confirmed project sources…</p>}{error&&<p role="alert" className="inline-error">{error}</p>}
   {!loading&&!error&&!rows.length&&<p>No confirmed project bullets have confirmed employment links. Add or review those links in Profile first.</p>}
   {(stale||missing)&&<p role="alert">Saved sources or job links changed. Review each changed placement below. Unavailable placements can be removed with “Use standalone project choices”. Your current PDF is unchanged.</p>}
   {rows.map(row=>{const c=choices[key(row)],value=c?.placement==='employment'?c.employment_id:c?.placement||'project';const target=row.jobs.find((j:any)=>j.id===value);return <article key={key(row)} className="linked-evidence-item"><h4>{row.project_title}</h4><blockquote>{row.original}</blockquote><label>Place this detail<select disabled={busy} value={value} onChange={e=>change(row,{placement:e.target.value==='project'||e.target.value==='omit'?e.target.value:'employment',employment_id:e.target.value==='project'||e.target.value==='omit'?'':e.target.value,replace_overlaps:false})}>
    {c?.placement==='employment'&&!target&&<option value={c.employment_id} disabled>Previous role unavailable · choose a current destination</option>}<option value="project">Standalone project · available for selection</option><option value="omit">Omit this detail</option>{row.jobs.map((job:any)=><option value={job.id} key={job.id}>{job.title} · {job.organization} · {job.dates||'Dates not provided'}</option>)}
   </select></label>{row.jobs.length>1&&<p className="small">Confirm where you did this specific work. A project link alone does not establish which role it belongs under.</p>}
   {value==='project'&&row.jobs.some((j:any)=>j.overlaps.length>0)&&<p className="small">Similar evidence is already saved under {row.jobs.filter((j:any)=>j.overlaps.length>0).map((j:any)=>j.title).join(', ')}. Review those job bullets before including the same detail as a standalone project.</p>}
   {c&&c.source_fingerprint!==row.source_fingerprint&&<button type="button" className="button secondary" disabled={busy} onClick={()=>change(row,{})}>Confirm current source & role links</button>}
   {target?.overlaps.length>0&&<div className="linked-evidence-overlap"><strong>Overlapping job evidence needs review</strong><ul>{target.overlaps.map((item:any)=><li key={item.item_id}>{item.text}</li>)}</ul><label className="check-line"><input type="checkbox" disabled={busy} checked={!!c?.replace_overlaps} onChange={e=>change(row,{replace_overlaps:e.target.checked})}/><span>Replace these job bullets with the selected project detail in this draft</span></label></div>}
   {target&&<p className="small">Source: {row.project_title} → {target.title}</p>}</article>;})}
   {(!!rows.length||!!saved.length)&&<div className="card-actions"><button type="button" className="button primary" disabled={busy||blocked||loading||stale||unavailableRole||overlapPending||missing||!changed} onClick={async()=>{setError('');const placements=rows.filter(row=>choices[key(row)]).map(row=>choices[key(row)]);const value=await onApply(placements);if(value){setChanged(false);setOpen(false);}else setError('Placements were not applied. Your choices remain here; resolve the error above before trying again.');}}>{session.current?'Apply placements to draft · no AI':'Save placements for first draft · no AI'}</button><button type="button" className="button secondary" disabled={busy} onClick={()=>{setChoices({});setChanged(true);}}>Use standalone project choices</button><button type="button" className="button secondary" disabled={busy||loading} onClick={load}>Refresh sources</button></div>}
   {blocked&&<p role="status" className="small">Finish saving local draft edits before applying placements.</p>}
  </>}
 </section>;
}
