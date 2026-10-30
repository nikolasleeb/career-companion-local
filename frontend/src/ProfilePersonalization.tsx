import React,{useEffect,useState} from 'react';

export function ProfilePersonalization({api}:{api:any}){
 const [saved,setSaved]=useState<any>(null),[enabled,setEnabled]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('');
 async function load(preserve=false){try{const value=await api('/profile/personalization');setSaved(value);if(!preserve)setEnabled(value.enabled);setError('');}catch(e){setError((e as Error).message);}}
 useEffect(()=>{void load();},[]);
 async function save(e:React.FormEvent){e.preventDefault();setBusy(true);setError('');setMessage('');try{const value=await api('/profile/personalization','PUT',{enabled,expected_revision:saved.revision});setSaved(value);setMessage('Personalization saved. New requests use this setting; saved results are unchanged.');window.dispatchEvent(new Event('career-context-updated'));}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 return <section className="panel profile-personalization" id="profile-personalization" aria-labelledby="profile-personalization-title">
  <h2 id="profile-personalization-title">Personalization</h2>
  <form onSubmit={save}><label className="check-line"><input type="checkbox" checked={enabled} disabled={!saved||busy} onChange={e=>{setEnabled(e.target.checked);setMessage('');}}/>Personalize with my Profile</label>
   <p className="small muted">Use relevant confirmed experience and its project, job and education links, saved Career Goals, and your reviewed Work Styles summary. Each AI action selects the context it needs; it does not send your entire Profile.</p>
   {saved&&!saved.explicit&&<p className="notice">Your previous sharing choices are still in effect. Saving this setting replaces the separate sharing choices for new requests. Work Styles still requires a reviewed summary.</p>}
   <details><summary>What can be used?</summary><p>Resources and Career Coach can use relevant professional records, Goals as aspirations, and the reviewed Work Styles summary. Ordinary coding exercises omit Work Styles. No ordinary feature receives assessment scores or questionnaire answers.</p><p>Resume and cover-letter tools use the evidence you choose for the document. Citizenship, work authorization and sponsorship settings may support eligibility checks in resume preparation; they do not become resume accomplishments.</p><p>Other private application answers stay limited to application filling. Assessment information stays within Work Styles summary creation and result explanation. Turning personalization off stops automatic Profile, Goals and Work Styles context; information you explicitly supply for a task remains part of that task.</p></details>
   <div className="form-actions"><button className="button secondary" type="submit" disabled={!saved||busy}>{busy?'Saving…':'Save personalization'}</button></div>
  </form>{message&&<p role="status">{message}</p>}{error&&<div role="alert"><p>{error}</p><button type="button" className="text-button" disabled={busy} onClick={()=>void load(true)}>Load latest setting; keep my choice</button></div>}
 </section>;
}
