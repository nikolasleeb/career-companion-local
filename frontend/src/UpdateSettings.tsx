import React,{useEffect,useState} from 'react';
import {UpdateInfo,updateLabel} from './updateStatus';

export function UpdateSettings({api}:{api:(path:string,method?:string,body?:any)=>Promise<any>}){
 const [info,setInfo]=useState<UpdateInfo|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[now,setNow]=useState(Date.now()/1000);
 const canCheck=!!info&&info.next_check_at<=now;
 useEffect(()=>{if(!info||info.next_check_at<=now)return;const timer=setTimeout(()=>setNow(Date.now()/1000),Math.max(1000,(info.next_check_at-now)*1000+100));return()=>clearTimeout(timer);},[info,now]);
 useEffect(()=>{let active=true;(async()=>{setBusy(true);try{let result=await api('/updates');if(result.needs_check)result=await api('/updates/check','POST',{force:false});if(active){setInfo(result);setNow(Date.now()/1000);}}catch{if(active)setError('Version information is unavailable. Try again.');}finally{if(active)setBusy(false);}})();return()=>{active=false;};},[api]);
 async function check(){setBusy(true);setError('');try{setInfo(await api('/updates/check','POST',{force:true}));setNow(Date.now()/1000);}catch{setError('Unable to check for updates. Your installed app is unchanged.');}finally{setBusy(false);}}
 return <section className="panel update-panel" aria-labelledby="updates-title">
  <div className="section-header"><h2 id="updates-title">App version &amp; updates</h2><span className="tag" role="status">{busy?'Checking…':info?updateLabel(info):'Not checked'}</span></div>
  <p>This localhost edition runs on this computer. Updates are checked when you open Settings, at most once a day.</p>
  {info&&<><dl className="update-versions"><div><dt>Installed version</dt><dd>{info.installed.version}{info.installed.channel!=='release'?' · custom build':''}</dd></div><div><dt>Latest published version</dt><dd>{info.latest?.version||'Not available'}</dd></div><div><dt>Last successful check</dt><dd>{info.checked_at?new Date(info.checked_at*1000).toLocaleString():'Never'}{info.stale&&info.checked_at?' · stale':''}</dd></div></dl>
   {info.state==='custom'&&<p className="small muted">This source build cannot be compared reliably with a published image. Review the release before updating.</p>}
   {info.error&&<p role="status">{info.error}</p>}
   <div className="card-actions"><button type="button" className="button secondary" disabled={busy||!canCheck} onClick={check}>Check now</button><a className="button secondary" href={info.latest?.url||info.releases_url} target="_blank" rel="noreferrer">View releases ↗</a></div>
   {!canCheck&&!busy&&<p className="small muted">Please wait before checking again.</p>}
  </>}
  {!info&&<button type="button" className="button secondary" disabled={busy} onClick={check}>Check now</button>}
  {error&&<p role="alert">{error}</p>}
  <details className="top-space"><summary>How to update</summary><p>Finish or save your work, then follow the release’s localhost update instructions. Use the same Compose project and preserve both account-data and encryption-key volumes. Checking does not install anything or restart the app.</p><p className="small muted">A check contacts GitHub for public release information. No profile information, answers, documents, or OpenAI key are sent.</p></details>
 </section>;
}
