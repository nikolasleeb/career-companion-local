import React from 'react';
export function ForYouDiagnostics({value}: {value?:any}){
 if(!value)return <p className="small muted">This saved search predates per-posting diagnostics. Its original results are unchanged; no new search was run.</p>;
 const c=value.stage_counts||{};
 return <><p>{c.shortlisted||0} shortlisted · {c.verification_attempts||0} availability checks · {c.availability_verified||0} open postings verified · {c.recommended||0} recommended ({c.needs_review||0} need filter review).</p><ul>{(value.verification_outcomes||[]).map((v:any)=><li key={v.job_id}><strong>{v.title} · {v.company}</strong>: {v.outcome==='verified'?'Open posting verified':'Excluded'} — {v.reason}.{v.page_check&&<> Page check: {v.page_check}.</>}{(v.caveats||[]).map((s:string)=><span key={s}> {s}.</span>)}{value.fit_outcomes?.filter((f:any)=>f.job_id===v.job_id).map((f:any)=><span key={f.job_id}> Profile review: {f.reason}.</span>)}</li>)}</ul></>;
}
