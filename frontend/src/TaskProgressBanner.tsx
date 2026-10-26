import React,{useEffect,useState} from 'react';
import {progressView,TaskStatus} from './taskProgress';
export function TaskProgressBanner({task,compact=false,onStop}:{task:TaskStatus;compact?:boolean;onStop?:()=>Promise<void>}){
 const [now,setNow]=useState(Date.now()),[stopping,setStopping]=useState(false),[error,setError]=useState('');
 useEffect(()=>{if(task.connection_lost||!['queued','running','cancelling'].includes(task.status))return;setNow(Date.now());const timer=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(timer);},[task.status,task.connection_lost]);
 const view=progressView(task,now);
 return <div className={'status-banner resume-task-progress '+(view.unknown?'status-unknown':'is-working')+(compact?' compact-progress':'')}>
  {!view.unknown&&<span className="status-spinner" aria-hidden="true"/>}
  <div className="status-copy" role={compact?undefined:'status'} aria-live={compact?'off':'polite'} aria-atomic="true"><strong>{task.status==='cancelling'?'Stopping…':view.label}</strong><span>{view.detail}</span></div>
  {onStop&&task.can_cancel&&!task.connection_lost&&<button className="button secondary" disabled={stopping||task.status==='cancelling'} onClick={async()=>{setStopping(true);setError('');try{await onStop();}catch(e){setError((e as Error).message);}finally{setStopping(false);}}}>{stopping||task.status==='cancelling'?'Stopping…':'Stop'}</button>}{error&&<span role="alert">{error} Check saved status before retrying.</span>}
  <div className="task-elapsed" aria-live="off"><span>{view.unknown?'Elapsed at last update':'Total elapsed'} <b>{view.total}</b></span>{view.stage&&<span>{view.unknown?'Last known stage':'This stage'} <b>{view.stage}</b></span>}</div>
 </div>;
}
