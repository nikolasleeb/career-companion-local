import {useUnsavedWarning} from './WorkspaceDialog';
import React,{useEffect,useState} from 'react';

export function ProfilePersonalization({api}:{api:any}){
 const [saved,setSaved]=useState<any>(null),[enabled,setEnabled]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('');
 async function load(preserve=false){try{const value=await api('/profile/personalization');setSaved(value);if(!preserve)setEnabled(value.enabled);setError('');}catch(e){setError((e as Error).message);}}
 useEffect(()=>{void load();},[]);
 useUnsavedWarning(!!saved&&enabled!==saved.enabled);
 async function save(e:React.FormEvent){e.preventDefault();setBusy(true);setError('');setMessage('');try{const value=await api('/profile/personalization','PUT',{enabled,expected_revision:saved.revision});setSaved(value);setMessage('Personalization saved. New requests use this setting; saved results are unchanged.');window.dispatchEvent(new Event('career-context-updated'));}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 return <section className="panel profile-personalization" id="profile-personalization" aria-labelledby="profile-personalization-title">
  <h2 id="profile-personalization-title">Personalization</h2>
  <form onSubmit={save}><label className="check-line"><input type="checkbox" checked={enabled} disabled={!saved||busy} onChange={e=>{setEnabled(e.target.checked);setMessage('');}}/>Personalize with my Profile</label>
   <p className="small muted">Use relevant confirmed experience and its project, job and education links, saved Career Goals, and your reviewed Work Styles summary. Each AI action selects the context it needs; it does not send your entire Profile.</p>
   {saved&&!saved.explicit&&<p className="notice">Your previous sharing choices are still in effect. Saving this setting replaces the separate sharing choices for new requests. Work Styles still requires a reviewed summary.</p>}
   <details><summary>What can be used?</summary><p>Resources and Career Coach can use relevant professional records, Goals as aspirations, and the reviewed Work Styles summary. Ordinary coding exercises omit Work Styles. No ordinary feature receives assessment scores or questionnaire answers.</p><p><strong>Resume:</strong> Confirmed professional evidence supports content. The reviewed Work Styles summary may guide wording; assessment scores and questionnaire answers are excluded. Career Goals are excluded from resume generation.</p><p><strong>Cover letter:</strong> Uses the selected saved resume and reviewed letter context. The reviewed Work Styles summary may guide wording. Career Goals may guide follow-up questions; personal motivation requires review before use.</p><p><strong>Eligibility:</strong> Citizenship, work authorization and sponsorship settings remain limited to eligibility checks during resume preparation.</p><p>Other private application answers stay limited to application filling. Assessment information stays within Work Styles summary creation and result explanation. Turning personalization off stops automatic Profile, Goals and Work Styles context; information you explicitly supply for a task remains part of that task.</p></details>
   <div className="form-actions"><button className="button secondary" type="submit" disabled={!saved||busy}>{busy?'Saving…':'Save personalization'}</button></div>
  </form>{message&&<p role="status">{message}</p>}{error&&<div role="alert"><p>{error}</p><button type="button" className="text-button" disabled={busy} onClick={()=>void load(true)}>Load latest setting; keep my choice</button></div>}
 </section>;
}
