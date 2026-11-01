import './resumeQuality.css';
import React from 'react';
const labels:Record<string,string>={ready:'Ready for your review',needs_input:'Needs your input',needs_manual_changes:'Needs manual changes',unavailable:'Review unavailable',not_rechecked:'Not rechecked'};
export function ResumeQualityPanel({review,busy,estimate,onRecheck,kind='resume'}:{kind?:'resume'|'cover';review:any;busy:boolean;estimate:any;onRecheck:()=>void}){
 const reviewEstimate=kind==='cover'?estimate?.review_usd:estimate?.usd;
 return <details className={'resume-quality quality-'+(review?.status||'not_rechecked')}><summary>{kind==='cover'?'Cover Letter':'Resume'} quality review · {labels[review?.status]||'Not rechecked'}</summary><p><strong>{labels[review?.status]||'Not rechecked'}</strong></p>
 {!review&&<p>This draft has not had an independent quality review. Choose Recheck draft quality to review it, or Optimize for this posting to rebuild and review it.</p>}
 {review?.note&&<p className="small">{review.note}</p>}
 {!!review?.strengths?.length&&<><h4>Strengths</h4><ul>{review.strengths.map((s:string,i:number)=><li key={i}>{s}</li>)}</ul></>}
 {!!review?.findings?.length&&<><h4>Remaining issues</h4><ul>{review.findings.map((f:any,i:number)=><li key={i}><strong>{f.material?'Priority: ':'Suggestion: '}</strong>{f.issue}{f.resume_quote&&<blockquote>{f.resume_quote}</blockquote>}{f.posting_quote&&<details><summary>Posting reference</summary><blockquote>{f.posting_quote}</blockquote></details>}<p>{f.action}</p></li>)}</ul></>}
 {!!review?.next_actions?.length&&<><h4>Next actions</h4><ol>{review.next_actions.map((s:string,i:number)=><li key={i}>{s}</li>)}</ol></>}
 <p className="small muted">This reviews the document against the posting. It is not an employer ATS score or hiring prediction. Missing evidence may need clarification.</p>
 <button type="button" className="button secondary" disabled={busy||reviewEstimate==null} onClick={onRecheck}>Recheck draft quality · AI</button><p className="small muted">Estimated review: {reviewEstimate==null?'unavailable':'about $'+Number(reviewEstimate).toFixed(4)}. Reviews this version without rewriting it.</p></details>;
}
export function RefinementResults({items}:{items:any[]}){
 const names:Record<string,string>={pending:'Checking changes',updated:'Updated',already_satisfied:'Already satisfied',awaiting_approval:'Awaiting approval',needs_clarification:'Needs clarification',not_applied:'Not applied'};
 return <ul className="refinement-results">{items.map(r=><li key={r.request_id}><strong>{r.request_id}: {names[r.status]||'Not applied'}</strong> — {r.text}<p>{r.explanation}</p></li>)}</ul>;
}
export function hasRefinementText(text:string){return text.split('\n').some(line=>line.replace(/^\s*(?:[•●▪*-]|\d+[.)])\s*/, '').trim());}
