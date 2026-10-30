import React from 'react';
const date=(value:string)=>new Date(value).toLocaleDateString();
export function InterviewRefs({rows=[]}:{rows?:any[]}){return <>{rows.length>0&&<details className="interview-references"><summary>Supporting Profile and preparation sources · {rows.length}</summary>{rows.map((s:any,i:number)=><blockquote key={i}><strong>{s.label}</strong><p>{s.quote}</p>{s.url&&<a href={s.url} target="_blank" rel="noreferrer">Source ↗</a>}{s.checked_at&&<small>Checked {date(s.checked_at)}</small>}</blockquote>)}</details>}</>;}
function Items({title,values}:{title:string;values?:string[]}){return values?.length?<section><h4>{title}</h4><ul>{[...new Set(values)].map((text,i)=><li key={i}>{text}</li>)}</ul></section>:null;}
function Draft({text}:{text:string}){return <p className="preserve interview-profile-example">{text.split(/(\[[^\]]+\])/g).map((part,i)=>part.startsWith('[')?<mark key={i}>{part}</mark>:<React.Fragment key={i}>{part}</React.Fragment>)}</p>;}
export function InterviewFeedback({attempt,currentRevision,coding}:{attempt:any;currentRevision:string;coding:boolean}){
 const f=attempt.data.feedback,review=attempt.data.operation==='review',examples=attempt.data.operation==='examples'?f.example_answers:null;
 return <article className={'interview-feedback '+(review?'interview-result-review':'interview-result-preparation')}>
 <span className="eyebrow">{review?'SAVED ANSWER REVIEW':examples?'EXAMPLE ANSWERS':'ANSWER OUTLINE'} · {date(attempt.created_at)}</span>
 {!review&&<p className="small muted">Preparation help. No answer is evaluated in this result.</p>}
 <p>{f.summary}</p>
 {examples?<div className="interview-example-answers"><section><h4>Illustrative model answer</h4><p className="small muted">Fictional teaching example. Its people, actions and outcomes are invented.</p><p className="small">Structure: {examples.structure_label}</p><p className="preserve">{examples.fictional_answer}</p><Items title="Why it works" values={examples.why_it_works}/></section><section><h4>Draft from your Profile</h4><p className="small muted">{f.references?.length?'Based on reviewed Profile facts. Fill the highlighted placeholders with accurate details before using it.':'No Profile facts were cited for this draft. Use the highlighted placeholders to add your real details.'}</p><Draft text={examples.profile_draft}/><Items title="Details to add" values={examples.missing_details}/><Items title="Questions to help you fill the gaps" values={examples.follow_up_questions}/></section></div>:<>
 {review&&f.reviewer_takeaway&&<section><h4>What your answer communicates</h4><p>{f.reviewer_takeaway}</p><p className="small muted">An interpretation of this response, not a prediction of a hiring decision.</p></section>}
 {coding&&review&&<p className="interview-review-label">AI review only · code was not executed</p>}
 {review?<>{[['What worked',f.strengths],['What to improve',f.improvements],['Connections to your Profile',f.profile_connections],['Claims to clarify',f.claims_to_clarify],['Edge cases to consider',f.edge_cases]].map(([title,values]:any)=><Items key={title} title={title} values={values}/>)}</>:<><Items title="Useful starting points" values={f.strengths}/><Items title="Useful Profile connections" values={f.profile_connections}/><Items title="Details to add" values={[...(f.improvements||[]),...(f.claims_to_clarify||[])]}/><Items title="Cases to think through" values={f.edge_cases}/></>}
 {!coding&&f.star?.length>0&&<section><h4>{review?'STAR feedback':'Suggested structure'}</h4>{f.star.map((part:any)=><div key={part.part}><strong>{part.part}</strong><p>{part.guidance}</p></div>)}</section>}
 {f.correctness&&<section><h4>{review?'Code and reasoning':'Suggested approach'}</h4><p>{f.correctness}</p></section>}{f.complexity&&<section><h4>{review?'Complexity':'Complexity to consider'}</h4><p>{f.complexity}</p></section>}
 {f.follow_up&&<p><strong>{review?'Try next:':'Question to help you prepare:'}</strong> {f.follow_up}</p>}
 </>}
 {attempt.data.profile_revision!==currentRevision&&<p className="small muted">Your Profile has changed since this result. It keeps its original context.</p>}
 <InterviewRefs rows={f.references}/><p className="small muted">{attempt.data.ai?.model} · Usage recorded in Settings → Usage &amp; costs. This saved result does not automatically update Profile.</p>
 </article>;
}
