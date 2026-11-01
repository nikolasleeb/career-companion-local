import {reportDocumentRecovery} from './documentRecovery';
import React,{useEffect,useRef,useState} from 'react';
import {ApiError,comparisonTask,pendingComparison,pollTask} from './apiClient';
import {TaskStatus} from './taskProgress';
import './comparisonWorkflow.css';

type Props={account:string;job:string;mode:string;aiAvailable:boolean;hasEvidence:boolean;hasResult:boolean;preparation?:any;call:(path:string,method?:string,body?:any)=>Promise<any>;onResult:(value:any)=>void;refresh:()=>Promise<void>};
const active=(value:TaskStatus|null)=>!!value&&(value.connection_lost||['queued','running','cancelling','unknown'].includes(value.status));
export function ComparisonAction({account,job,mode,aiAvailable,hasEvidence,hasResult,preparation,call,onResult,refresh}:Props){
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[refreshError,setRefreshError]=useState('');
 const [status,setStatus]=useState<TaskStatus|null>(()=>{
  const id=pendingComparison(account,job)?.id||(preparation?.stage==='comparison'&&preparation?.state==='working'?preparation.task_id:'');
  return id?{id,status:'unknown',connection_lost:true,kind:'analysis'}:null;
 });
 useEffect(()=>{const scope='/analyses:'+job;reportDocumentRecovery(account,scope,status);return()=>reportDocumentRecovery(account,scope,null);},[account,job,status]);
 const latest=useRef(status);const running=useRef(false);
 const report=(value:TaskStatus)=>{latest.current=value;setStatus(value);};
 useEffect(()=>{
  if(!running.current&&preparation?.stage==='comparison'&&preparation?.state==='working'&&preparation.task_id&&latest.current?.id!==preparation.task_id)report({id:preparation.task_id,status:'unknown',connection_lost:true,kind:'analysis'});
 },[preparation?.stage,preparation?.state,preparation?.task_id]);
 const pending=pendingComparison(account,job),recover=!!pending||active(status);
 async function start(){
  if(running.current)return;running.current=true;setBusy(true);setError('');setRefreshError('');
  if(!pending&&!active(latest.current)){const stamp=new Date().toISOString();report({status:'running',kind:'analysis',created_at:stamp,progress:{code:'request',label:'Starting comparison',kind:'request',started_at:stamp,stage_started_at:stamp}});}
  let result:any;
  try{
   // Tasks recovered from another tab/device may have no local request token.
   // Read that exact owned task; never substitute a new provider request.
   if(!pending&&active(latest.current)&&latest.current?.id)result=await pollTask(latest.current.id,call,undefined,1200,report);
   else result=await comparisonTask(account,{job_id:job,mode},call,undefined,undefined,report);
  }catch(e){
   setError((e as Error).message);
   const saved=pendingComparison(account,job),known=latest.current;
   if(saved||!(e instanceof ApiError)||e.transient||[401,403].includes(e.status))report({...known,id:known?.id||saved?.id,status:'unknown',connection_lost:true,kind:'analysis'});
   else report({...known,status:'failed',connection_lost:false,kind:'analysis'});
  }finally{running.current=false;setBusy(false);}
  if(result){
   report({...latest.current,status:'completed',connection_lost:false});
   onResult(result);
   // The committed result is usable immediately. A later refresh is independent.
   void refresh().catch(()=>setRefreshError('Your comparison is saved and displayed. Other workspace information could not refresh.'));
  }
 }
 useEffect(()=>{const recover=()=>{if(active(latest.current)&&!running.current)void start();};window.addEventListener('document-status-recheck',recover);return()=>window.removeEventListener('document-status-recheck',recover);},[account,job,mode]);
 return <div className="comparison-action">
  <div className="comparison-action-controls"><button type="button" className="button primary" disabled={busy||(!recover&&(!aiAvailable||!hasEvidence))} onClick={()=>void start()}>{busy?'Checking comparison…':recover?'Check comparison status':hasResult?'Run comparison again':'Compare profile to job'}</button><p className="small muted">{recover?'Check the existing request without starting another comparison.':'Uses your confirmed Profile and reviewed Supporting Details. AI processing can take several minutes.'}</p></div>

  {error&&<p className="inline-error" role="alert">{error} {hasResult?'Your previous comparison remains below.':''}</p>}
  {refreshError&&<div className="notice" role="status">{refreshError} <button type="button" className="text-button" onClick={()=>{void refresh().then(()=>setRefreshError('')).catch(()=>{});}}>Refresh workspace · no AI</button></div>}
 </div>;
}
