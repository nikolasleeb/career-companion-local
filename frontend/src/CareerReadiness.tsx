import React,{useEffect,useRef,useState} from 'react';
import {useAppRoute,setRoute} from './appRoute';
import {confirmAction,useUnsavedWarning} from './WorkspaceDialog';
import {CareerGoalReview} from './CareerGoalReview';
import {CareerPay} from './CareerPay';
import {offerResourceHandoff} from './resourceHandoff';
import {pendingReadiness,clearReadiness,readinessAction,recoverReadiness,readReadinessDraft,readinessDraftKey} from './readinessState';
import './careerReadiness.css';

type Props={accountId:string;call:any;mode:string;aiAvailable:boolean;webAvailable:boolean;openSettings:()=>void};
const blank={title:'Career exploration',objective:'',interests:'',activities:'',time_available:'',preparation_budget:'',occupation_codes:[] as string[],selected_code:'',job_ids:[] as string[],salary_area:'US',research_enabled:false,action_budget_usd:1};
const money=(v:number)=>'$'+v.toFixed(3);
const stamp=(v:string)=>new Date(v).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'});
function Sources({references=[],sources=[]}:{references?:any[];sources?:any[]}){
 if(!references.length)return null;
 return <details className="readiness-sources"><summary>Supporting sources · {references.length}</summary>{references.map((ref:any,i:number)=>{const s=sources.find((v:any)=>v.source_id===ref.source_id);return <blockquote key={i}><strong>{s?.label||'Saved source'}</strong><p>{ref.quote}</p><small>{s?.kind==='reviewed_profile'?'Reviewed professional evidence':s?.kind?.startsWith('session_')?'Session statement · not confirmed qualifications':s?.kind==='curated'?'Original app guidance':s?.kind==='generated_readiness'?'Generated assessment · not qualification evidence':'Career information'}{s?.checked_at?' · Checked '+stamp(s.checked_at):''}</small>{s?.url&&<p><a href={s.url} target="_blank" rel="noreferrer">Open source ↗</a></p>}</blockquote>;})}</details>;
}
function Findings({title,rows=[],sources}:{title:string;rows?:any[];sources:any[]}){
 if(!rows.length)return null;
 return <section className="readiness-findings"><h3>{title}</h3>{rows.map((r:any,i:number)=><article key={i}><p>{r.text}</p><Sources references={r.references} sources={sources}/></article>)}</section>;
}

export function CareerReadiness({accountId,call,mode,aiAvailable,webAvailable,openSettings}:Props){
 const route=useAppRoute(),id=route.view==='readiness'?route.item||'':'';
 const [sessions,setSessions]=useState<any[]>([]),[options,setOptions]=useState<any>(null),[data,setData]=useState<any>(null);
 const [draft,setDraft]=useState<any>(()=>readReadinessDraft(accountId,'new',blank)),[message,setMessage]=useState(''),[busy,setBusy]=useState(''),[error,setError]=useState(''),[notice,setNotice]=useState('');
 const [search,setSearch]=useState(''),[matches,setMatches]=useState<any[]>([]),[occupations,setOccupations]=useState<Record<string,any>>({}),[reportId,setReportId]=useState(''),[turnId,setTurnId]=useState('');
 const [progress,setProgress]=useState<any>(null),[estimate,setEstimate]=useState<any>(null),[reviewChanges,setReviewChanges]=useState<any>(null),[goal,setGoal]=useState<any>(null),[recover,setRecover]=useState(false);
 const idRef=useRef(id),loading=useRef(false),heading=useRef<HTMLHeadingElement>(null);idRef.current=id;
 const session=data?.session,dirty=!!session&&JSON.stringify(draft)!==JSON.stringify(session.data.inputs);
 useUnsavedWarning(dirty);
 async function list(){setSessions(await call('/career-readiness/sessions'));}
 async function load(selected:string,resetDraft=true){
  const result=await call('/career-readiness/sessions/'+selected);if(idRef.current!==selected)return;
  setData(result);if(resetDraft)setDraft(readReadinessDraft(accountId,selected,result.session.data.inputs));
  setReportId(current=>result.reports.some((r:any)=>r.id===current)?current:result.session.data.report_id||'');
  setTurnId(result.turns.at(-1)?.id||'');setRecover(!!pendingReadiness(accountId,selected));
  setEstimate(await call('/career-readiness/sessions/'+selected+'/estimate?mode='+encodeURIComponent(mode)));return result;
 }
 useEffect(()=>{void Promise.all([list(),call('/career-readiness/options').then(setOptions)]).catch((e:Error)=>setError(e.message));},[accountId,route.view]);
 useEffect(()=>{
  if(route.view!=='readiness')return;setError('');setNotice('');setGoal(null);setReviewChanges(null);setData(null);setMessage('');setProgress(null);setReportId('');
  if(!id){setDraft(readReadinessDraft(accountId,'new',blank));setRecover(false);return;}
  loading.current=true;void load(id).catch((e:Error)=>setError(e.message)).finally(()=>{loading.current=false;});
 },[id,route.view,accountId]);
 useEffect(()=>{if(route.view!=='readiness'||loading.current||id&&!session)return;try{sessionStorage.setItem(readinessDraftKey(accountId,id||'new'),JSON.stringify(draft));}catch{}},[draft,id,session?.id,accountId,route.view]);
 useEffect(()=>{if(id&&session)void call('/career-readiness/sessions/'+id+'/estimate?mode='+encodeURIComponent(mode)).then(setEstimate).catch((e:Error)=>setError(e.message));},[mode]);
 useEffect(()=>{
  if(!search.trim()){setMatches([]);return;}let live=true;
  const timeout=setTimeout(()=>{void call('/career-readiness/occupations?q='+encodeURIComponent(search)).then((rows:any[])=>{if(live)setMatches(rows);}).catch((e:Error)=>{if(live)setError(e.message);});},250);
  return()=>{live=false;clearTimeout(timeout);};
 },[search]);
 useEffect(()=>{
  let live=true;const codes=[...new Set<string>([...draft.occupation_codes,...(data?.turns||[]).flatMap((r:any)=>r.data.reply.directions.map((v:any)=>v.code)),...((data?.reports||[]).map((r:any)=>r.data.input_snapshot.inputs.selected_code))])].filter(Boolean);
  void Promise.all(codes.map(async code=>[code,await call('/career-explorer/occupations/'+code+'?salary_area='+encodeURIComponent(draft.salary_area))])).then(rows=>{if(live)setOccupations(Object.fromEntries(rows));}).catch((e:Error)=>{if(live)setError(e.message);});return()=>{live=false;};
 },[draft.occupation_codes.join(','),draft.salary_area,data?.turns.length,data?.reports.length]);
 useEffect(()=>{if(!id)return;try{setMessage(sessionStorage.getItem('readiness-message:'+accountId+':'+id)||'');}catch{}},[id]);
 useEffect(()=>{if(id)try{sessionStorage.setItem('readiness-message:'+accountId+':'+id,message);}catch{}},[message,id,accountId]);
 const change=(key:string,value:any)=>setDraft((d:any)=>({...d,[key]:value}));
 async function local(label:string,fn:()=>Promise<any>){if(busy)return;setBusy(label);setError('');try{await fn();}catch(e){setError((e as Error).message);}finally{setBusy('');}}
 async function save(){
  if(!draft.objective.trim())throw Error('Describe what you want to explore.');
  const saved=await call('/career-readiness/sessions'+(id?'/'+id:''),id?'PATCH':'POST',{...draft,...(id?{expected_revision:session.data.revision}:{})});
  sessionStorage.removeItem(readinessDraftKey(accountId,id||'new'));setDraft(saved.data.inputs);
  if(!id){idRef.current=saved.id;setRoute({view:'readiness',item:saved.id});}else{setData({...data,session:saved});setEstimate(await call('/career-readiness/sessions/'+id+'/estimate?mode='+encodeURIComponent(mode)));}
  await list();return saved;
 }
 async function act(operation:string){
  if(!id||!session)return;setReviewChanges(null);setBusy('Running readiness');setError('');setNotice('');setProgress(null);
  const selected=id;
  try{
   const current=dirty?await save():session;
   const sent=message;const completed=await readinessAction(accountId,selected,{operation,expected_revision:current.data.revision,message:sent,report_id:['follow_up','reassess'].includes(operation)?reportId:'',mode},call,setProgress);
   if(idRef.current===selected){setMessage((current:string)=>current===sent?'':current);if(['assess','reassess'].includes(operation))setReportId(completed.report_id);await load(selected);setNotice('Readiness findings saved. Review the sources and choose your next step.');}await list();window.dispatchEvent(new Event('career-context-updated'));
  }catch(e){setError((e as Error).message);if(idRef.current===selected)setRecover(!!pendingReadiness(accountId,selected));}
  finally{setBusy('');}
 }
 async function recoverAction(){
  await local('Checking saved readiness status',async()=>{const selected=id;await recoverReadiness(accountId,selected,call,setProgress);if(idRef.current===selected)await load(selected);await list();});
 }
 function addCode(code:string){if(draft.occupation_codes.includes(code))return;if(draft.occupation_codes.length>=3){setError('Compare up to three careers. Remove one before adding another.');return;}change('occupation_codes',[...draft.occupation_codes,code]);setSearch('');setMatches([]);}
 async function destination(target:string){
  const shared=await call('/career-readiness/sessions/'+id+'/handoff/'+reportId),context=[shared.occupation,{...shared,context_ref:shared.context_ref}];
  const actions=shared.actions,summary=actions.map((a:any)=>a.title+': '+a.purpose+'\n'+a.steps.join('\n')).join('\n\n');
  if(target==='plans'){window.dispatchEvent(new CustomEvent('open-career-plans',{detail:{prompt:'Build a practical plan toward '+shared.occupation.title+'. Use these readiness priorities as proposed guidance, not proof of qualifications.\n'+summary,context}}));}
  if(target==='skills'){if(await offerResourceHandoff('skills',accountId,shared.resource_topics.slice(0,5)))setRoute({view:'prep',readiness:reportId});}
  if(target==='interview'){
   const existing=sessionStorage.getItem('interview-draft:'+accountId+':setup');
   if(existing&&JSON.parse(existing).notes&&!await confirmAction({title:'Replace interview setup draft?',message:'Use this readiness direction and practice focus? Your saved interview sessions are kept.',confirmLabel:'Use readiness focus',cancelLabel:'Keep my draft'}))return;
   const key='readiness-interview-handoff:'+accountId;
   sessionStorage.setItem(key,JSON.stringify({role:shared.occupation.title,notes:'Generated readiness guidance, not qualification evidence.\n'+summary,report_id:reportId,session_id:id}));
   setRoute({view:'interviews',tab:'behavioral-setup'});window.dispatchEvent(new Event('readiness-interview-handoff'));
  }
  if(target==='coach')window.dispatchEvent(new CustomEvent('open-career-coach',{detail:{prompt:'Help me understand this career readiness assessment and the next actions I could take.',context,record_id:reportId}}));
  if(target==='goal')setGoal(shared.occupation);
  if(target==='save'){await call('/career-explorer/saved','POST',{code:shared.occupation.code,source:'search'});setNotice('Career saved to Explore Occupations.');}
  if(target==='explore')setRoute({view:'explorer',item:shared.occupation.code});
 }
 const turn=data?.turns.find((r:any)=>r.id===turnId),report=data?.reports.find((r:any)=>r.id===reportId),shown=turn?.data.reply.outcome==='assessment'?report||turn:turn||report,reply=shown?.data.reply,sources=shown?.data.source_snapshot||[];
 const blocked=!!busy||recover||!!data?.task_id;
 return <div className="career-readiness">
  <header className="job-search-heading"><span className="eyebrow">RESOURCES / FIND YOUR DIRECTION</span><h1 ref={heading} tabIndex={-1}>Career Readiness</h1><p>Explore directions, understand the experience you can demonstrate, and choose a useful next step.</p><p className="small muted">An AI agent investigates relevant sources and asks focused questions. You choose the direction and review every proposed action.</p></header>
  {error&&<div className="notice" role="alert">{error}</div>}{notice&&<p className="notice" role="status">{notice}</p>}
  <section className="panel readiness-history"><div className="section-header"><h2>{id?'Your assessment session':'Start an assessment'}</h2>{id&&<button className="button secondary" onClick={()=>setRoute({view:'readiness'})}>New assessment</button>}</div>
   <label>Saved assessments<select value={id} disabled={!!busy} onChange={e=>setRoute({view:'readiness',...(e.target.value?{item:e.target.value}:{})})}><option value="">New assessment</option>{sessions.map(r=><option key={r.id} value={r.id}>{r.data.inputs.title} · {stamp(r.updated_at)}</option>)}</select></label>
   {id&&session&&<div className="card-actions"><button className="text-button" disabled={blocked} onClick={()=>void local('Deleting readiness session',async()=>{if(!await confirmAction({title:'Delete readiness session?',message:'Delete this session, findings, reports and research? Your Profile and saved plans remain available.',confirmLabel:'Delete session',cancelLabel:'Cancel',danger:true}))return;await call('/career-readiness/sessions/'+id,'DELETE');clearReadiness(accountId,id);sessionStorage.removeItem(readinessDraftKey(accountId,id));sessionStorage.removeItem('readiness-message:'+accountId+':'+id);setRoute({view:'readiness'});await list();})}>Delete session</button><span className="small muted">Session usage: {money(data.session_cost.estimated_or_reserved_usd)}{data.session_cost.unreported_requests?' · Includes reserved amounts for unreported requests':''}</span></div>}
  </section>
  {(!id||session)&&<details className="panel readiness-inputs" open={!data?.turns.length||dirty}><summary>Your starting point</summary><form onSubmit={e=>{e.preventDefault();void local('Saving readiness inputs',save);}}><fieldset disabled={blocked}>
   <div className="form-grid"><label>Session name<input maxLength={100} required value={draft.title} onChange={e=>change('title',e.target.value)}/></label><label>Salary area<select value={draft.salary_area} onChange={e=>change('salary_area',e.target.value)}>{(options?.salary_areas||[{id:'US',title:'United States'}]).map((a:any)=><option key={a.id} value={a.id}>{a.title}</option>)}</select></label></div>
   <label>What would you like to figure out?<textarea required rows={3} maxLength={2000} value={draft.objective} onChange={e=>change('objective',e.target.value)} placeholder="I’m unsure which careers to explore after graduation."/></label>
   <div className="form-grid"><label>Interests (optional)<textarea rows={3} maxLength={2000} value={draft.interests} onChange={e=>change('interests',e.target.value)}/></label><label>Activities you enjoy (optional)<textarea rows={3} maxLength={2000} value={draft.activities} onChange={e=>change('activities',e.target.value)}/></label><label>Preparation time available (optional)<input maxLength={200} value={draft.time_available} onChange={e=>change('time_available',e.target.value)}/></label><label>Learning budget (optional)<input maxLength={200} value={draft.preparation_budget} onChange={e=>change('preparation_budget',e.target.value)} placeholder="For example: free resources"/></label></div>
   <details open={draft.occupation_codes.length>0}><summary>Review your shortlist · {draft.occupation_codes.length}/3</summary><p>Start undecided, choose saved careers, or search below. Only you select the direction to assess.</p>
    {(options?.saved_careers||[]).filter((c:any)=>!c.unavailable&&!draft.occupation_codes.includes(c.code)).slice(0,12).map((c:any)=><button type="button" className="button secondary" key={c.code} onClick={()=>addCode(c.code)}>Add {c.title}</button>)}
    <label>Find an occupation<input value={search} maxLength={150} onChange={e=>setSearch(e.target.value)} placeholder="Occupation or public career topic"/></label>
    <div className="readiness-search-results">{matches.map(c=><button type="button" className="text-button" key={c.code} onClick={()=>addCode(c.code)}>{c.title}</button>)}</div>
    <ul>{draft.occupation_codes.map((code:string)=><li key={code}><label className="check-line"><input type="radio" name="readiness-direction" checked={draft.selected_code===code} onChange={()=>change('selected_code',code)}/><span>{occupations[code]?.title||code}</span></label><button type="button" className="text-button" onClick={()=>setDraft((d:any)=>({...d,occupation_codes:d.occupation_codes.filter((c:string)=>c!==code),selected_code:d.selected_code===code?'':d.selected_code}))}>Remove</button></li>)}</ul>
    {draft.selected_code&&<button type="button" className="text-button" onClick={()=>change('selected_code','')}>Keep exploring without a selected direction</button>}
   </details>
   <details><summary>Context shared with the agent</summary><p>Reviewed professional evidence follows your personalization settings. Career Goals are aspirations; Work Styles summaries express preferences. Private application answers and raw assessment scores are excluded.</p>
    <ul>{options?.context.map((c:any,i:number)=><li key={i}>{c.label}</li>)}</ul>{!options?.context.length&&<p>No shared Profile evidence is currently available. General exploration still works.</p>}
    <fieldset><legend>Optional saved postings · {draft.job_ids.length}/3</legend>{options?.jobs.map((j:any)=><label className="check-line" key={j.id}><input type="checkbox" checked={draft.job_ids.includes(j.id)} disabled={!draft.job_ids.includes(j.id)&&draft.job_ids.length>=3} onChange={e=>change('job_ids',e.target.checked?[...draft.job_ids,j.id]:draft.job_ids.filter((v:string)=>v!==j.id))}/><span>{j.title} · {j.company}</span></label>)}{options&&draft.job_ids.filter((value:string)=>!options.jobs.some((j:any)=>j.id===value)).map((value:string)=><p key={value}>A selected posting is unavailable. <button className="text-button" type="button" onClick={()=>change('job_ids',draft.job_ids.filter((v:string)=>v!==value))}>Remove unavailable posting</button></p>)}</fieldset>
   </details>
   <label className="check-line"><input type="checkbox" checked={draft.research_enabled} disabled={!webAvailable} onChange={e=>change('research_enabled',e.target.checked)}/><span>Check current public sources · optional additional AI usage</span></label>
   <label>Estimated spending ceiling per AI action (USD)<input type="number" min="0.05" max="20" step="0.05" value={draft.action_budget_usd} onChange={e=>change('action_budget_usd',Number(e.target.value))}/></label>
   <p className="small muted">Your model setup is used for each action. Limits include up to five agent model calls and one research request. Unreported charges remain reserved. Reading and saving inputs are free.</p>
   <button className="button secondary" disabled={!draft.objective.trim()}>{id?'Save inputs · no AI':'Create session · no AI'}</button>{dirty&&<span className="small muted"> Unsaved input changes</span>}
  </fieldset></form></details>}
  {id&&session&&<section className="panel readiness-controls"><h2>Investigate your next step</h2>
   {!aiAvailable&&<p className="notice">Add your own AI key to run the agent. <button className="text-button" onClick={openSettings}>Open AI setup</button></p>}
   {estimate&&<p className="small muted">Saved setup: {estimate.model} · {estimate.reasoning} reasoning · {estimate.service_tier}. Final-response planning reserve: {money(estimate.minimum_reserved_usd)}. Your ceiling: {money(draft.action_budget_usd)}.</p>}
   <label>Answer the agent or add context (optional)<textarea rows={3} maxLength={5000} value={message} onChange={e=>setMessage(e.target.value)} placeholder="Answer the questions below, or write ‘skip’ to continue with the uncertainty noted."/></label>
   <div className="card-actions"><button className="button primary" disabled={blocked||!aiAvailable} onClick={()=>void act('discover')}>Explore directions · AI</button><button className="button secondary" disabled={blocked||!aiAvailable||!draft.occupation_codes.length} onClick={()=>void act('compare')}>Compare reviewed shortlist · AI</button><button className="button secondary" disabled={blocked||!aiAvailable||!draft.selected_code} onClick={()=>void act('assess')}>Assess selected direction · AI</button></div>
   {(busy||data.task_id)&&<div role="status" className="notice">{progress?.progress?.label||busy||'Readiness action is running'}{(progress?.task_id||data.task_id||pendingReadiness(accountId,id)?.id)&&<button className="text-button" onClick={()=>void call('/tasks/'+(progress?.task_id||data.task_id||pendingReadiness(accountId,id)?.id)+'/cancel','POST',{}).then(()=>setNotice('Stop requested. Checking the final task status…')).catch((e:Error)=>setError(e.message))}>Stop</button>}</div>}
   {(recover||data.task_id&&!busy)&&<div className="notice"><p>Check the saved status before starting another action. Checking never dispatches another model request.</p><button className="button secondary" disabled={!!busy} onClick={()=>{if(!pendingReadiness(accountId,id)&&data.task_id)localStorage.setItem('readiness-action:'+accountId+':'+id,JSON.stringify({id:data.task_id}));void recoverAction();}}>Check saved status</button>{recover&&!pendingReadiness(accountId,id)?.id&&<button className="text-button" onClick={()=>void local('Checking unconfirmed request',async()=>{const p=pendingReadiness(accountId,id);try{await call('/career-readiness/actions/'+p.token);throw Error('A saved action exists. Use Check saved status.');}catch(e){if((e as any).status!==404)throw e;clearReadiness(accountId,id);setRecover(false);setNotice('No saved action was found. You can explicitly start another.');}})}>Resolve unconfirmed start</button>}</div>}
  </section>}
  {data?.turns.length>0&&<section className="panel"><div className="form-grid"><label>Saved findings<select value={turnId} onChange={e=>setTurnId(e.target.value)}>{data.turns.map((r:any)=><option key={r.id} value={r.id}>{r.data.operation.replace('_',' ')} · {stamp(r.created_at)}</option>)}</select></label>{data.reports.length>0&&<label>Assessment version<select value={reportId} onChange={e=>{setReportId(e.target.value);const r=data.reports.find((v:any)=>v.id===e.target.value);const t=data.turns.find((v:any)=>v.data.operation===r?.data.operation&&v.created_at>=r.created_at);if(t)setTurnId(t.id);}}>{data.reports.map((r:any)=><option key={r.id} value={r.id}>Version {r.data.version} · {stamp(r.created_at)}</option>)}</select></label>}</div></section>}
  {reply&&<section className="panel readiness-results" aria-label="Readiness findings"><h2>{reply.outcome==='assessment'?'Your readiness assessment':reply.outcome==='comparison'?'Compare your directions':reply.outcome==='shortlist'?'Directions to consider':reply.outcome==='clarification'?'A few questions before continuing':'Your follow-up answer'}</h2><p className="preserve">{reply.summary}</p><Sources references={reply.summary_references} sources={sources}/>
   {reply.questions.length>0&&<div className="notice"><h3>What would help clarify your direction?</h3><ol>{reply.questions.map((q:string,i:number)=><li key={i}>{q}</li>)}</ol><p>Answer above and repeat the relevant action, or write “skip.” Experience described here remains a session self-report until separately reviewed in Profile.</p></div>}
   {reply.directions.length>0&&<><div className="readiness-direction-grid">{reply.directions.map((d:any)=><article className="readiness-direction" key={d.code}><h3>{occupations[d.code]?.title||d.code}{reply.recommended_code===d.code&&<span className="readiness-recommendation">Suggested leading direction</span>}</h3><p>{d.interest_connection.text}</p><Sources references={d.interest_connection.references} sources={sources}/><p>{d.work_and_preparation.text}</p><Sources references={d.work_and_preparation.references} sources={sources}/>{occupations[d.code]&&<details><summary>Published pay and outlook</summary><CareerPay salary={occupations[d.code].salary} detail/><p>Projected growth: {occupations[d.code].growth??'Not reported'}{occupations[d.code].growth!=null?'%':''} · {occupations[d.code].metadata?.growth_period}</p><p className="small muted">Published occupational statistics, not starting pay or a prediction of your employment.</p></details>}<Findings title="Demonstrated strengths" rows={d.strengths} sources={sources}/><Findings title="Transferable experience" rows={d.transferable_experience} sources={sources}/><Findings title="Tradeoffs" rows={d.tradeoffs} sources={sources}/>{d.uncertainties.length>0&&<><h4>Uncertainties</h4><ul>{d.uncertainties.map((v:string,i:number)=><li key={i}>{v}</li>)}</ul></>}<h4>Try this to explore</h4><p>{d.exploration_activity}</p><button className="button secondary" disabled={blocked||draft.occupation_codes.includes(d.code)} onClick={()=>addCode(d.code)}>Add to my shortlist</button></article>)}</div>{reply.outcome==='shortlist'&&<button className="button secondary" disabled={blocked} onClick={()=>setDraft((d:any)=>({...d,occupation_codes:reply.directions.map((v:any)=>v.code),selected_code:''}))}>Use these directions as my shortlist</button>}</>}
   {reply.recommendation_reason&&<Findings title="Why this recommendation" rows={[reply.recommendation_reason]} sources={sources}/>}
   <Findings title="Demonstrated strengths" rows={reply.demonstrated_strengths} sources={sources}/><Findings title="Transferable experience" rows={reply.transferable_experience} sources={sources}/><Findings title="Development priorities" rows={reply.development_priorities} sources={sources}/>
   {reply.needs_clarification.length>0&&<><h3>Needs clarification</h3><ul>{reply.needs_clarification.map((v:string,i:number)=><li key={i}>{v}</li>)}</ul></>}
   {reply.next_actions.length>0&&<section><h3>Your next actions</h3><ol className="readiness-next-actions">{reply.next_actions.map((a:any,i:number)=><li key={i}><h4>{a.title}</h4><p>{a.purpose}</p><p className="small muted">{a.effort}</p><ul>{a.steps.map((s:string,j:number)=><li key={j}>{s}</li>)}</ul><Sources references={a.references} sources={sources}/></li>)}</ol></section>}
   {reply.changes.length>0&&<><h3>What changed</h3><ul>{reply.changes.map((v:string,i:number)=><li key={i}>{v}</li>)}</ul></>}
   {(reply.limitations.length>0||shown.data.research_warnings.length>0)&&<details open><summary>Limits and source coverage</summary><ul>{[...reply.limitations,...shown.data.research_warnings].map((v:string,i:number)=><li key={i}>{v}</li>)}</ul></details>}
   <details><summary>Agent activity</summary><ol>{shown.data.activity.map((a:any,i:number)=><li key={i}>{a.tool.replaceAll('_',' ')} · {a.status} · {a.seconds}s</li>)}</ol><p className="small muted">Actions and outcomes, without hidden reasoning.</p></details>
  </section>}
  {report&&<section className="panel readiness-continue"><h2>Continue from assessment version {report.data.version}</h2><p>Choose the next step. These findings are generated guidance; your Profile and saved plans change only through their review and save workflows.</p><div className="card-actions">{[['explore','Explore occupation'],['plans','Build an action plan'],['skills','Find learning resources'],['interview','Prepare interview practice'],['goal','Add to Career Goals'],['save','Save career'],['coach','Discuss with Career Coach']].map(([key,label])=><button key={key} className="button secondary" disabled={blocked||!report.sharing_allowed} onClick={()=>void local('Preparing your next step',()=>destination(key))}>{label}</button>)}</div>
   {!report.sharing_allowed&&<p className="notice">Source sharing or availability changed. Reassess with current information before sharing this assessment.</p>}
   <div className="card-actions"><button className="button primary" disabled={blocked||!aiAvailable||!message.trim()||!report.sharing_allowed} onClick={()=>void act('follow_up')}>Ask about this assessment · AI</button><button className="button secondary" disabled={blocked||!aiAvailable||dirty} onClick={()=>void local('Checking changed information',async()=>setReviewChanges(await call('/career-readiness/sessions/'+id+'/changes?report_id='+reportId)))}>Reassess with current information</button></div>
   {dirty&&<p className="small muted">Save your input changes before reviewing a reassessment.</p>}
   {reviewChanges&&<div className="notice"><h3>Review before reassessing</h3>{reviewChanges.unchanged?<p>No saved source changes were detected. You can still reassess with the new context you enter above.</p>:<ul>{reviewChanges.changes.map((v:string,i:number)=><li key={i}>{v}</li>)}</ul>}<p>A new version will be created. Historical assessments remain available.</p><button className="button primary" disabled={blocked} onClick={()=>void act('reassess')}>Generate new assessment version · AI</button><button className="text-button" onClick={()=>setReviewChanges(null)}>Cancel</button></div>}
   {goal&&<CareerGoalReview career={goal} api={call} onClose={()=>setGoal(null)} onSaved={()=>{setGoal(null);setNotice('Career Goal saved.');}}/>}
  </section>}
 </div>;
}
