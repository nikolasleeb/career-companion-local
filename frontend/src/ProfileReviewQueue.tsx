import React from 'react';
export function profileReviewCounts(workspace:any){
 const records=workspace.experience||[],known=new Map<string,any>(records.map((r:any)=>[r.id,r.data]));
 const unresolved=records.filter((r:any)=>{
  const d=r.data;return (d.linked_employment_ids||[]).some((id:string)=>!known.get(id)?.confirmed)||(d.linked_education_ids||[]).some((id:string)=>!known.get(id)?.confirmed)||(d.linked_courses||[]).some((link:any)=>{const target=known.get(link.education_id);return !target?.confirmed||!String(target.relevant_courses||'').split(/[\n;,]+/).map(v=>v.trim()).includes(link.course);});
 });
 return {imports:(workspace.document||[]).filter((r:any)=>r.data.purpose==='resume'&&!r.data.reviewed),unconfirmed:records.filter((r:any)=>!r.data.confirmed),details:(workspace.profile_answer||[]).filter((r:any)=>r.data.status==='draft'),unresolved,unlinked:(workspace.profile_answer||[]).filter((r:any)=>r.data.needs_related_experience)};
}
export function ProfileReviewQueue({workspace,onImports,onRecord,onDetails}:{workspace:any;onImports:()=>void;onRecord:(r:any)=>void;onDetails:()=>void}){
 const q=profileReviewCounts(workspace);
 return <details className="profile-review-summary"><summary>Review queue · {q.imports.length} imports · {q.unconfirmed.length} unconfirmed records · {q.details.length} Supporting Details · {q.unresolved.length+q.unlinked.length} unresolved relationships</summary><p className="small muted">Review and approve each item yourself. Saved resume snapshots stay unchanged.</p><div className="card-actions"><button type="button" className="button secondary" onClick={onImports}>Import reviews · {q.imports.length}</button><button type="button" className="button secondary" onClick={onDetails}>Supporting Details &amp; links · {q.details.length+q.unlinked.length}</button></div>{[...new Map([...q.unconfirmed,...q.unresolved].map((r:any)=>[r.id,r])).values()].map((r:any)=><p key={r.id}><button type="button" className="text-button" onClick={()=>onRecord(r)}>{r.data.title||r.data.organization||'Untitled record'} · {!r.data.confirmed?'Needs confirmation':'Review relationships'}</button></p>)}</details>;
}
