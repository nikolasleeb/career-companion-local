import {useAppRoute,patchRoute,routeNow} from './appRoute';
import {WorkCareerDiscovery} from './WorkCareerDiscovery';
import './workStylesPolish.css';
import {WorkPreferences} from './WorkPreferences';
import React,{useEffect,useRef,useState} from 'react';
import type {Services} from './EvidenceTools';
import {assessmentLayout,missingRatings,restoreResponses} from './workStyleFlow';

export function WorkStyle({services:s}:{services:Services}){
 const [catalog,setCatalog]=useState<any>(null),[rows,setRows]=useState<any[]>([]),[attempt,setAttempt]=useState<any>(null),[answers,setAnswers]=useState<Record<string,number>>({}),[pairs,setPairs]=useState<Record<string,string>>({}),[page,setPage]=useState(0),[status,setStatus]=useState('Saved'),[error,setError]=useState(''),[missing,setMissing]=useState(false);
 const navRoute=useAppRoute();
 useEffect(()=>{if(navRoute.view==='master'&&navRoute.tab==='workstyles'&&navRoute.item&&navRoute.item!==attempt?.id){const row=rows.find((r:any)=>r.id===navRoute.item);if(row)open(row);else if(catalog)setError('This assessment is unavailable. Choose one of your saved attempts or start a new assessment.');}},[navRoute.view,navRoute.tab,navRoute.item,rows]);
 const focus=useRef<HTMLHeadingElement>(null),current=useRef<any>(null),dirty=useRef(false),inflight=useRef(false),serial=useRef(0);
 const prefix='next-step-work-styles:'+s.user.id,buffer=(id:string)=>prefix+':'+id;
 current.current={attempt,answers,pairs,page};
 function open(row:any){
  let a=row.data.answers,p=row.data.comparison_answers||{},pg=row.data.page||0;dirty.current=false;setError('');setStatus('Saved');setMissing(false);
  try{const saved=JSON.parse(localStorage.getItem(buffer(row.id))||'null');const recovered=restoreResponses(row,saved);if(recovered.dirty){a=recovered.answers;p=recovered.pairs;pg=recovered.page;dirty.current=true;setStatus('Saving…');if(recovered.conflict){setError('This attempt changed in another window. Your local responses are retained. Reload the saved version before retrying.');setStatus('Could not save');}}localStorage.setItem(prefix,row.id);}catch{}
  setAttempt(row);setAnswers(a);setPairs(p);setPage(pg);current.current={attempt:row,answers:a,pairs:p,page:pg};
 }
 useEffect(()=>{let live=true;Promise.all([s.api('/work-style/catalog'),s.api('/work-style')]).then(([cat,list])=>{if(!live)return;setCatalog(cat);setRows(list);let id='';try{id=localStorage.getItem(prefix)||'';}catch{}const selected=list.find((r:any)=>r.id===id)||list.find((r:any)=>r.data.status==='draft')||list[0];if(selected)open(selected);}).catch(e=>live&&setError(e.message));return()=>{live=false;};},[]);
 async function save(){
  if(!dirty.current||inflight.current||!current.current.attempt)return;
  const value=current.current,stamp=serial.current;inflight.current=true;
  try{const next=await s.api('/work-style/'+value.attempt.id+'/progress','PUT',{expected_version:value.attempt.data.version,answers:value.answers,comparison_answers:value.pairs,page:value.page});
   setRows(old=>old.map(r=>r.id===next.id?next:r));setAttempt(next);current.current={...current.current,attempt:next};
   if(stamp===serial.current){dirty.current=false;setStatus('Saved');localStorage.removeItem(buffer(next.id));}
   else{setStatus('Saving…');localStorage.setItem(buffer(next.id),JSON.stringify({answers:current.current.answers,pairs:current.current.pairs,page:current.current.page,version:next.data.version}));}
  }catch(e){setStatus('Could not save');setError((e as Error).message);}finally{inflight.current=false;}
 }
 useEffect(()=>{if(!dirty.current||error)return;const t=setTimeout(save,500);return()=>clearTimeout(t);},[answers,pairs,page,attempt?.data.version,error]);
 function change(a=answers,p=pairs,pg=page){
  serial.current++;dirty.current=true;setAnswers(a);setPairs(p);setPage(pg);setStatus(error?'Could not save':'Saving…');
  current.current={attempt,answers:a,pairs:p,page:pg};
  localStorage.setItem(buffer(attempt.id),JSON.stringify({answers:a,pairs:p,page:pg,version:attempt.data.version}));
  if(pg!==page)requestAnimationFrame(()=>focus.current?.focus());
 }
 const cat=attempt?.data.catalog||catalog,{count,size,ratingPages,comparisonPages,pages}=assessmentLayout(cat||{items:[],comparisons:[]}),completed=attempt?.data.status==='completed',report=attempt?.data.report;
 const unanswered=cat?missingRatings(cat,answers):[],answeredCount=count-unanswered.length;
 async function finish(){
  const first=cat.items.findIndex((q:any)=>q.id===unanswered[0]?.id);
  if(first>=0){setMissing(true);const target=Math.floor(first/size);if(target!==page)change(answers,pairs,target);requestAnimationFrame(()=>focus.current?.focus());return;}
  await s.run('Calculating your private report locally',async()=>{const result=await s.api('/work-style/'+attempt.id+'/score','POST',{expected_version:attempt.data.version,answers,comparison_answers:pairs,page});localStorage.removeItem(buffer(attempt.id));open(result);setRows(await s.api('/work-style'));requestAnimationFrame(()=>focus.current?.focus());});
 }
 return <section className="work-styles" aria-labelledby="work-styles-heading">
  <span className="eyebrow">PRIVATE / WORKING PREFERENCES</span><h1 id="work-styles-heading">Work Styles</h1>
  <p className="work-styles-intro">Understand your patterns, the tradeoffs they can bring and the working conditions that may help you. Explore working conditions across careers without a job-category matching score.</p>
  <div className="notice"><strong>Your private report · no AI or API key needed</strong><p>Raw questionnaire answers stay private. After you review and enable AI guidance in Profile, Career Coach can retrieve your report and scores; other guidance receives only your approved summary. It never becomes applicant evidence, resume content or eligibility information. This is self-reflection, with no employer pass score or hiring prediction.</p></div>
  {error&&<div role="alert" className="notice"><p>{error}</p>{attempt&&<div className="card-actions"><button className="button secondary" onClick={()=>{setError('');save();}}>Retry saving</button><button className="button secondary" onClick={()=>s.run('Reloading assessment version',async()=>{const list=await s.api('/work-style');const latest=list.find((r:any)=>r.id===attempt.id);if(latest){setAttempt(latest);current.current={...current.current,attempt:latest};setRows(list);dirty.current=true;localStorage.setItem(buffer(latest.id),JSON.stringify({answers,pairs,page,version:latest.data.version}));setError('');setStatus('Saving…');}})}>Keep my responses & reload version</button></div>}</div>}
  <section className="panel top-space"><h2>Your assessment</h2><p>The published IPIP-NEO-120 has 120 ratings across five dimensions and 30 facets, including personal, emotional and political statements. A separate optional section has 12 optional work comparisons. You can pause and resume.</p>
   <div className="card-actions"><button className="button primary" disabled={!!s.busy||status!=='Saved'||!catalog} onClick={()=>s.run('Opening Work Styles',async()=>{const row=await s.api('/work-style','POST');patchRoute('master',{tab:'workstyles',item:row.id},true);open(row);setRows(await s.api('/work-style'));})}>{rows.some(r=>r.data.status==='draft'&&r.data.catalog_version===catalog?.version)?'Resume assessment':'Start assessment / retake'}</button>
   {!!rows.length&&<label>Saved attempts<select value={attempt?.id||''} disabled={status!=='Saved'||!!s.busy} onChange={e=>{const row=rows.find(r=>r.id===e.target.value);if(row){patchRoute('master',{tab:'workstyles',item:row.id});open(row);}}}><option value="">Choose an attempt</option>{rows.map(r=><option key={r.id} value={r.id}>{new Date(r.created_at).toLocaleString()} · {r.data.catalog?.title||'Historical reflection'} · {r.data.status}</option>)}</select></label>}</div>
  </section>
  {attempt&&!completed&&cat&&<section className="panel top-space questionnaire">
   <h2 tabIndex={-1} ref={focus}>{page<ratingPages?'Part 1 · Rate each statement':'Part 2 · Compare work preferences'}</h2>
   <p>{page<ratingPages?cat.instructions:'Choose the statement that feels more natural for you. Both are reasonable approaches. These original preferences do not change your published personality scores. Leave any pair unanswered or clear a choice to skip it.'}</p>
   <progress value={answeredCount} max={count} aria-label="Published questionnaire responses"/><p>{answeredCount} / {count} ratings saved or selected · {Object.keys(pairs).length} / {cat.comparisons?.length||0} optional comparisons</p>
   <label>Questionnaire page<select value={page} onChange={e=>change(answers,pairs,Number(e.target.value))}>{Array.from({length:pages},(_,i)=><option key={i} value={i}>{i<ratingPages?'Ratings '+(i*size+1)+'–'+Math.min((i+1)*size,count):'Comparisons '+((i-ratingPages)*6+1)+'–'+Math.min((i-ratingPages+1)*6,cat.comparisons.length)}</option>)}</select></label>
   {missing&&<p role="alert">Answer the remaining {unanswered.length} statements. The first missing response is on this page.</p>}
   {page<ratingPages?cat.items.slice(page*size,page*size+size).map((q:any,n:number)=><fieldset className={'work-rating'+(missing&&answers[q.id]==null?' unanswered':'')} key={q.id}><legend>{page*size+n+1}. {q.text}</legend><div className="work-rating-options">{cat.options.map((o:any)=><label key={o.value} className={answers[q.id]===o.value?'chosen':''}><input type="radio" name={'rating-'+attempt.id+'-'+q.id} value={o.value} checked={answers[q.id]===o.value} onChange={()=>change({...answers,[q.id]:o.value})}/><span>{answers[q.id]===o.value?'✓ ':''}{o.label}</span></label>)}</div></fieldset>):cat.comparisons.slice((page-ratingPages)*6,(page-ratingPages+1)*6).map((q:any)=><fieldset className="work-rating" key={q.id}><legend>{q.theme} · Which feels more natural?</legend><div className="work-pair-options">{['left','right'].map(side=><label key={side} className={pairs[q.id]===side?'chosen':''}><input type="radio" name={'preference-'+q.id} checked={pairs[q.id]===side} onChange={()=>change(answers,{...pairs,[q.id]:side})}/><span>{pairs[q.id]===side?'✓ ':''}{q[side]}</span></label>)}</div>{pairs[q.id]&&<button className="text-button" onClick={()=>{const next={...pairs};delete next[q.id];change(answers,next);}}>Clear this choice / skip</button>}</fieldset>)}
   <div className="form-actions"><button className="button secondary" disabled={page===0} onClick={()=>change(answers,pairs,page-1)}>← Previous</button><span>Page {page+1} / {pages}</span><button className="button secondary" disabled={page===pages-1} onClick={()=>change(answers,pairs,page+1)}>Next →</button></div>
   <p role="status">{status} · No provider request</p><button className="button primary" disabled={!!s.busy||status!=='Saved'||!!error} onClick={finish}>{answeredCount===count?'See my private report · no AI':'Review missing responses'}</button>
   {comparisonPages>0&&page<ratingPages&&answeredCount===count&&<button className="button secondary" disabled={status!=='Saved'} onClick={()=>change(answers,pairs,ratingPages)}>Optional: compare work preferences</button>}
  </section>}
  {completed&&<section className="panel top-space" aria-labelledby="work-report-heading"><h2 id="work-report-heading" tabIndex={-1} ref={focus}>Your private report</h2><p>{new Date(attempt.data.completed_at).toLocaleDateString()} · {cat.title}</p>
   {report?<><p>{report.explanation}</p><h3>Your five dimensions</h3><div className="work-report-grid">{report.domains.map((d:any)=><article key={d.dimension_id}><h4>{d.name}</h4><p className="work-score">{d.mean.toFixed(2)} <small>/ 5 response-scale mean</small></p><meter min={1} max={5} value={d.mean} aria-label={d.name+' response-scale mean'}/><p>{d.pattern}</p><p><strong>Potential advantage:</strong> {d.potential}</p><p><strong>Possible friction:</strong> {d.friction}</p><p><strong>Conditions to try:</strong> {d.environment}</p><p><strong>Practical suggestion:</strong> {d.suggestion}</p><details><summary>Explore six facets</summary>{report.facets.filter((f:any)=>f.facet_id.startsWith(d.dimension_id)).map((f:any)=><section className="work-facet" key={f.facet_id}><h5>{f.name} · {f.mean.toFixed(2)} / 5</h5><p>{f.pattern}</p><p>{f.suggestion}</p><p className="small muted">{f.total} / {f.maximum} raw total · Lower end: {f.lower_end}. Upper end: {f.upper_end}.</p></section>)}</details></article>)}</div>
   <details className="top-space"><summary>Your stated work choices · show details</summary><p>These separate choices describe preferences, not skills or personality scores. Different situations may call for different approaches.</p>{report.preferences.length?<div className="work-preferences">{report.preferences.map((p:any)=><article key={p.id}><strong>{p.theme}</strong><p>{p.selected}</p><details><summary>The alternative</summary><p>{p[p.choice==='left'?'right':'left']}</p></details></article>)}</div>:<p>You skipped the optional comparisons. No preferences were inferred.</p>}</details></>:<><p>This historical IPIP-50 reflection retains its original scoring and report. Start a new assessment for the detailed Work Styles report.</p><div className="work-report-grid">{attempt.data.scores.map((d:any)=><article key={d.dimension_id}><h3>{d.name}</h3><strong>{d.total} / {d.maximum}</strong><p>{d.description}</p></article>)}</div></>}
  </section>}
  <WorkPreferences api={s.api}/>{completed&&<WorkCareerDiscovery/>}
  {cat&&<details className="panel top-space"><summary>Published measure, sources & scoring</summary><p>{cat.attribution}</p><p>Instrument version: {cat.version}. Positive items score 1–5; reverse-keyed items score 5–1. {count===120?'Four items form each facet (4–20); six facets form each domain (24–120). Means divide totals by the number of items. Paired preferences are excluded.':'Ten items form each legacy dimension (10–50).'}</p><p><a href={cat.source_url} target="_blank" rel="noreferrer">Published items and key ↗</a> · <a href={cat.scoring_url} target="_blank" rel="noreferrer">Scoring instructions ↗</a></p><p>Completed attempts remain unchanged. Retakes create a separate attempt. Account backups include your private answers and reports.</p></details>}
 </section>;
}
