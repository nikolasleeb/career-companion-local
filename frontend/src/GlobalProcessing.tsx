import React,{useEffect,useState} from 'react';
import {processing} from './processing';
import {TaskProgressBanner} from './TaskProgressBanner';
import {StatusBanner} from './StatusBanner';
import type {TaskStatus} from './taskProgress';

export function GlobalProcessing({account,api,busy,error,message,fallback,onDismiss}:{account:string;api:(path:string)=>Promise<any>;busy:string;error:string;message:string;fallback?:TaskStatus|null;onDismiss:()=>void}){
 const [entries,setEntries]=useState(processing.snapshot()),[failure,setFailure]=useState(processing.failure),[retry,setRetry]=useState(0);
 useEffect(()=>{
  processing.setOwner(account);let live=true,checking=false,timer:ReturnType<typeof setTimeout>|undefined,failures=0;
  function wake(){setEntries(processing.snapshot());setFailure(processing.failure);if(!checking&&!timer&&processing.snapshot().some(v=>!v.request||v.settled))void check();}
  async function check(){
   if(!live||checking)return;checking=true;const before=processing.serial;
   try{const values=await api('/tasks/active');if(live){failures=0;processing.reconcile(values,before);}}
   catch{if(live){failures++;processing.disconnected();}}
   finally{checking=false;if(live&&processing.snapshot().some(v=>!v.request||v.settled))timer=setTimeout(()=>{timer=undefined;void check();},Math.min(2000*2**failures,10000));}
  }
  const off=processing.subscribe(wake);const focus=()=>{if(timer){clearTimeout(timer);timer=undefined;}void check();};window.addEventListener('focus',focus);wake();void check();
  return()=>{live=false;off();if(timer)clearTimeout(timer);window.removeEventListener('focus',focus);};
 },[account,retry]);
 const shown=entries.length?entries:fallback&&['queued','running','unknown'].includes(fallback.status)?[fallback]:[];
 return <div className={shown.length||busy?'global-processing active':'global-processing'}>
  {shown.length>1&&<p className="small processing-count">{shown.length} actions in progress</p>}
  {shown.map((value:any)=><TaskProgressBanner key={value.id||'recovering'} task={value}/>)}
  {shown.some((v:any)=>v.connection_lost||v.status==='unknown')&&<button className="button secondary processing-reconnect" onClick={()=>setRetry(v=>v+1)}>Check saved status · no new AI request</button>}
  <StatusBanner busy={shown.length?'':busy} error={error||failure} message={message} onDismiss={()=>{processing.clearFailure();onDismiss();}}/>
 </div>;
}
