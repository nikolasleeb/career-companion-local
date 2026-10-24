import React from 'react';
import {TaskProgressBanner} from './TaskProgressBanner';
import {TaskStatus} from './taskProgress';

export function StatusBanner({busy='',error='',message='',onDismiss,task}:{busy?:string;error?:string;message?:string;onDismiss?:()=>void;task?:TaskStatus|null}){
 if(task&&['queued','running','unknown'].includes(task.status)&&!error)return <TaskProgressBanner task={task}/>;
 if(!busy&&!error&&!message)return null;
 const working=!!busy&&!error;
 const comparing=working&&busy==='Comparing your profile';
 return <div className={`status-banner ${error?'error':working?'is-working':''}`} role={error?'alert':'status'} aria-live={error?'assertive':'polite'} aria-atomic="true">
  {working&&<span className="status-spinner" aria-hidden="true"/>}
  <div className="status-copy">{working?<><strong>{busy}…</strong><span>{comparing?'Checking your experience against the job requirements. Your results will appear here when ready.':'Please wait while this finishes.'}</span></>:<span>{error||message}</span>}</div>
  {working?<span className="status-progress-label" aria-hidden="true">In progress</span>:onDismiss&&<button aria-label="Dismiss message" onClick={onDismiss}>×</button>}
 </div>;
}
