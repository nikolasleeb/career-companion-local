import React,{useEffect,useState} from 'react';
import {foregroundAction,pendingAction,recoverAction,clearUnconfirmed} from './foregroundAction';
import './profileSummaries.css';
export function WorkPreferences({api,onAssessment}:{api:any;onAssessment?:()=>void}){
 const [saved,setSaved]=useState<any>(null),[draft,setDraft]=useState(''),[notes,setNotes]=useState(''),[enabled,setEnabled]=useState(false),[reviewed,setReviewed]=useState(false),[busy,setBusy]=useState(false),[pending,setPending]=useState(false),[recover,setRecover]=useState(false),[proposal,setProposal]=useState<any>(null),[generation,setGeneration]=useState(''),[estimate,setEstimate]=useState<any>(null),[estimateError,setEstimateError]=useState(''),[message,setMessage]=useState(''),[error,setError]=useState('');
 const scope='work-style-summary',activeText=proposal?.summary||draft,operation=activeText.trim()&&notes.trim()?'revise':'generate';
 const canGenerate=!!activeText.trim()||!!saved?.assessment.suggested_preferences?.length||!!saved?.preferences?.length;
 function load(v:any){setSaved(v);setDraft(v.summary||'');setEnabled(v.use_for_ai);setReviewed(!!v.summary&&v.reviewed&&(!v.use_for_ai||v.coach_report_access));setRecover(!!pendingAction(v.account_id,scope));}
 useEffect(()=>{api('/profile/work-preferences').then(load).catch((e:Error)=>setError(e.message));},[]);
 useEffect(()=>{
  if(!saved)return;if(!canGenerate){setEstimate(null);setEstimateError('Complete the optional work comparisons in the full assessment before generating a summary.');return;}let live=true;
  const timer=setTimeout(()=>{api('/profile/work-preferences/summary/estimate','POST',{operation,notes,draft:activeText,expected_revision:saved.revision,mode:saved.mode,request_token:'estimate-only'}).then((v:any)=>{if(live){setEstimate(v);setEstimateError('');}}).catch((e:Error)=>{if(live){setEstimate(null);setEstimateError(e.message);}});},250);
  return()=>{live=false;clearTimeout(timer);};
 },[saved?.revision,activeText,notes,operation,canGenerate]);
 function change(text:string){setDraft(text);setReviewed(false);setEnabled(false);setMessage('');}
 async function aiAction(kind:'generate'|'revise'='generate',recovery=false){
  if(!saved||pending)return;setPending(true);setError('');
  try{const value=recovery?await recoverAction(saved.account_id,scope,api):await foregroundAction(saved.account_id,scope,'/profile/work-preferences/summary/actions',{operation:kind,notes,draft:activeText,expected_revision:saved.revision,mode:saved.mode},api);setProposal(value);setMessage('Summary draft ready above. Review it, then choose Use this draft before saving.');}
  catch(e){setError((e as Error).message);}finally{setPending(false);setRecover(!!pendingAction(saved.account_id,scope));}
 }
 async function save(e:React.FormEvent){
  e.preventDefault();if(count>250||proposal)return;setBusy(true);setError('');
  try{const r=await api('/profile/work-preferences','PUT',{expected_revision:saved.revision,summary:draft,use_for_ai:enabled,coach_report_access:enabled,reviewed,assessment_id:saved.assessment.assessment_id||'',generation_task_id:generation});load(r);setGeneration('');setProposal(null);setMessage('Work Styles summary saved. '+(r.use_for_ai?'AI guidance is on.':'AI guidance is off.'));window.dispatchEvent(new Event('career-context-updated'));}
  catch(e){setError((e as Error).message);}finally{setBusy(false);}
 }
 function acceptProposal(){if(draft!==saved.summary&&draft&&!window.confirm('Replace the unsaved paragraph with this AI draft?'))return;change(proposal.summary);setGeneration(proposal.task_id);setProposal(null);}
 const count=draft.trim()?draft.trim().split(/\s+/).length:0,locked=busy||pending||recover;
 return <section className="panel work-preference-profile"><div className="section-header"><h2>Work Styles</h2><span className="tag">{saved?.use_for_ai?saved.coach_report_access?'AI guidance on':'Summary-only guidance on':'AI guidance off'}</span></div>
 {!saved&&!error&&<p role="status">Loading your summary…</p>}
 {saved&&<>
  {onAssessment&&!!saved.assessment.summary?.length&&<div className="assessment-at-a-glance"><h3>Your assessment at a glance</h3><p className="small muted">Private self-reflection from your completed assessment. Career Coach can access the report only after you enable and save AI guidance below.</p><ul>{saved.assessment.summary.map((d:any)=><li key={d.name}><strong>{d.name}:</strong> {d.pattern}</li>)}</ul></div>}
  <p className="small muted">{saved.assessment.completed?'Assessment completed '+new Date(saved.assessment.completed_at).toLocaleDateString():'No completed assessment yet. Complete the work comparisons to provide context for your summary.'}</p>
  {onAssessment&&<button type="button" className="button secondary" onClick={onAssessment}>Open full Work Styles assessment ↗</button>}
  <section className="saved-profile-summary work-summary-workspace" aria-label="Your Work Styles summary">
   <div className="section-header"><h3>Your Work Styles summary</h3>{activeText&&<span className="tag">{proposal?'AI draft · not saved':draft!==saved.summary?'Unsaved changes':'Saved summary'}</span>}</div>
   {activeText?<p className="work-summary-paragraph">{activeText}</p>:<p>Generate a short summary from your saved work-style choices. Once it appears, you can ask AI for changes.</p>}
   {!saved.summary&&!!saved.preferences?.length&&<details><summary>Previously approved work-style statements</summary><p>{saved.preferences.join(' ')}</p><p className="small muted">Preserved until you save a replacement summary.</p></details>}
   {proposal&&<div className="card-actions"><button type="button" className="button secondary" disabled={locked} onClick={acceptProposal}>Use this draft</button><button type="button" className="text-button" disabled={locked} onClick={()=>setProposal(null)}>Keep my current summary</button><p className="small muted">Review this draft before replacing your paragraph. Nothing has been saved or enabled.</p></div>}
   <>{activeText&&<div className="work-summary-chat"><label>Ask for changes to this summary<textarea rows={3} maxLength={2000} value={notes} disabled={locked} onChange={e=>setNotes(e.target.value)} placeholder="For example: Emphasize that I like collaboration after time to prepare on my own."/></label><p className="small muted">Ask AI to adjust the wording, correct something or change the emphasis. It proposes a new draft for your review.</p><button type="button" className="button secondary" disabled={locked||!notes.trim()||!saved.ai_available||!estimate} onClick={()=>void aiAction('revise')}>Ask AI to revise</button></div>}</>
  </section>
  <div className="work-summary-generate">
   <button type="button" className="button primary" disabled={locked||!saved.ai_available||!estimate} onClick={()=>void aiAction('generate')}>{activeText?'Generate a new summary · AI':'Generate summary · AI'}</button>
   {pending&&<button type="button" className="button secondary" onClick={()=>{const p=pendingAction(saved.account_id,scope);if(p?.id)void api('/tasks/'+p.id+'/cancel','POST',{}).catch((e:Error)=>setError(e.message));}}>Stop</button>}
   {estimate?<p className="small muted">Estimated AI request: {estimate.usd!=null?'about $'+Number(estimate.usd).toFixed(4):'price unavailable'} · {estimate.model} · {estimate.reasoning} reasoning. Actual usage may differ.</p>:<p className="small muted">{estimateError||'Calculating a local cost estimate…'}</p>}
   <details><summary>What is used to generate a summary?</summary><p className="small muted">Your explicit work-comparison choices, previously saved work-style statements, current paragraph and notes go to your account’s AI provider. One model request, no web search. Raw questionnaire answers, scores and assessment descriptions are excluded from summary generation.</p>{[...(saved.assessment.suggested_preferences||[]),...(saved.preferences||[])].length?<ul>{[...(saved.assessment.suggested_preferences||[]),...(saved.preferences||[])].map((v:string,i:number)=><li key={i}>{v}</li>)}</ul>:<p>Complete the optional work comparisons in the full assessment to provide context for generation.</p>}</details>
   {!saved.ai_available&&<p className="small muted">{saved.setup_required?'Review an education entry in Resume content to unlock AI tools.':'Add your own OpenAI key in Settings to request a draft.'} Existing saved summaries are preserved.</p>}
   {recover&&<div className="card-actions"><button type="button" className="button secondary" disabled={pending} onClick={()=>void aiAction('generate',true)}>Check saved summary request</button><button type="button" className="text-button" disabled={pending} onClick={async()=>{const p=pendingAction(saved.account_id,scope);try{await api('/ai-actions/'+p.token);setError('A saved request exists. Check its status.');}catch(e){if((e as any).status===404){clearUnconfirmed(saved.account_id,scope);setRecover(false);}else setError((e as Error).message);}}}>Resolve unconfirmed request</button></div>}
  </div>
  <form className="work-summary-sharing" onSubmit={save}><fieldset disabled={locked||!!proposal}><legend>Save &amp; AI guidance</legend>
   {saved.use_for_ai&&!saved.coach_report_access&&<p className="small muted">Your existing summary-only sharing remains unchanged. Review the expanded Career Coach access below before saving.</p>}
   <label className="check-line"><input type="checkbox" checked={reviewed} disabled={!draft.trim()} onChange={e=>{setReviewed(e.target.checked);if(!e.target.checked)setEnabled(false);}}/>I reviewed this summary and the AI access described below.</label>
   <label className="check-line"><input type="checkbox" checked={enabled} disabled={!enabled&&(!reviewed||!draft.trim())} onChange={e=>setEnabled(e.target.checked)}/>Use Work Styles for AI guidance</label>
   <p className="small muted"><strong>Career Coach:</strong> can retrieve your saved summary, full assessment report, dimension/facet scores and work-comparison choices. <strong>Resume guidance:</strong> receives only your reviewed summary as optional wording context, never the report or scores. It cannot use Work Styles to establish qualifications.</p>
   <p className="small muted">Raw questionnaire answers are excluded. Other career guidance uses only the reviewed summary. Off by default; turn this off and save to stop sharing in new requests. Earlier saved conversations remain unchanged.</p>
   <button type="submit" className="button primary" disabled={count>250||enabled&&!reviewed||!draft.trim()&&(enabled||!saved.summary&&!saved.use_for_ai)}>{busy?'Saving…':'Save summary & AI guidance'}</button>
  </fieldset>{proposal&&<p className="small muted">Choose Use this draft or Keep my current summary above before saving.</p>}</form>
 </>}
 {message&&<p role="status">{message}</p>}{error&&<div role="alert"><p>{error}</p>{saved&&<button type="button" className="text-button" disabled={pending||busy} onClick={async()=>{try{const v=await api('/profile/work-preferences');setSaved(v);setGeneration('');setError('');setMessage('Latest saved revision loaded. Your draft and notes are preserved; review before saving.');}catch(e){setError((e as Error).message);}}}>Load latest saved revision</button>}</div>}
 </section>;
}
