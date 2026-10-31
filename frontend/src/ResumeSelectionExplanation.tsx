import React from 'react';

export function ResumeSelectionExplanation({snapshot}:{snapshot:any}){
 const explanation=snapshot?.optimization?.strategy;
 if(!explanation)return null;
 const facts=(snapshot.sections||[]).flatMap((s:any)=>s.entries.flatMap((e:any)=>e.content_items.flatMap((i:any)=>i.source_refs||[])));
 return <details className="posting-extra" aria-label="Resume content selection"><summary>Why this content was selected</summary>
  <h4>{explanation.focus}</h4><p>{explanation.rationale}</p>
  <p className="small muted">Based on the content in this rendered revision. These findings describe evidence coverage, not an ATS score or a prediction of hiring.</p>
  {(explanation.priorities||[]).map((p:any)=><article key={p.id} className="top-space"><strong>{p.text}</strong><p className="small">{p.evidence==='unresolved'?'Needs clarification':p.included?(p.evidence==='transferable'?'Included · transferable experience':'Included · direct evidence'):'Reviewed evidence available · omitted from this version'}</p><p className="small">{p.reason}</p><details><summary>Posting and supporting evidence</summary><blockquote>{p.posting_quote}</blockquote>{facts.filter((f:any,n:number,all:any[])=>p.included_source_ids?.includes(f.source_id)&&all.findIndex(v=>v.source_id===f.source_id)===n).map((f:any)=><blockquote key={f.source_id}><small>Reviewed Profile evidence</small><p>{f.quote}</p></blockquote>)}</details></article>)}
  {explanation.omissions?.length>0&&<details><summary>Important omissions</summary>{explanation.omissions.map((o:any)=><p className="small" key={o.record_id}><strong>{o.title}</strong>: {o.reason}</p>)}</details>}
  {explanation.unresolved?.length>0&&<><h4>Unresolved evidence</h4><ul>{explanation.unresolved.map((v:string,n:number)=><li key={n}>{v}</li>)}</ul></>}
 </details>;
}
