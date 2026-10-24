import React,{useEffect,useState} from 'react';
import {progressView,TaskStatus} from './taskProgress';
export function TaskProgressBanner({task,compact=false}:{task:TaskStatus;compact?:boolean}){
 const [now,setNow]=useState(Date.now());
 useEffect(()=>{const timer=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(timer);},[]);
 const view=progressView(task,now);
 return <div className={'status-banner resume-task-progress '+(view.unknown?'status-unknown':'is-working')+(compact?' compact-progress':'')}>
  {!view.unknown&&<span className="status-spinner" aria-hidden="true"/>}
  <div className="status-copy" role={compact?undefined:'status'} aria-live={compact?'off':'polite'} aria-atomic="true"><strong>{view.label}</strong><span>{view.detail}</span></div>
  <div className="task-elapsed" aria-live="off"><span>Total elapsed <b>{view.total}</b></span>{view.stage&&<span>{view.unknown?'Last known stage':'This stage'} <b>{view.stage}</b></span>}</div>
 </div>;
}
