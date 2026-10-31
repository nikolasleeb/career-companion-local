import React,{useEffect,useState} from 'react';
import {createPortal} from 'react-dom';
import {processing,processingGroups,isCoachProcessing} from './processing';
import {TaskProgressBanner} from './TaskProgressBanner';
import {StatusBanner} from './StatusBanner';

export function GlobalProcessing({account,api,busy,error,message,onReconnect,onDismiss}:{account:string;api:(path:string,method?:string,body?:any)=>Promise<any>;busy:string;error:string;message:string;onReconnect:()=>Promise<void>;onDismiss:()=>void}){
 const [host,setHost]=useState<HTMLElement|null>(null),[coachHost,setCoachHost]=useState<HTMLElement|null>(null);
 useEffect(()=>{const update=()=>{const hosts=Array.from(document.querySelectorAll<HTMLElement>('dialog[open] [data-progress-host]'));setHost(hosts.at(-1)||null);setCoachHost(document.querySelector<HTMLElement>('[data-coach-progress-host]'));};const observer=new MutationObserver(update);observer.observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['open']});update();return()=>observer.disconnect();},[]);
 const [entries,setEntries]=useState(processing.snapshot()),[failure,setFailure]=useState(processing.failure),[retry,setRetry]=useState(0),[signIn,setSignIn]=useState(false),[checkingStatus,setCheckingStatus]=useState(false),[recoveryError,setRecoveryError]=useState('');
 useEffect(()=>{
  processing.setOwner(account);let live=true,checking=false,authBlocked=false,timer:ReturnType<typeof setTimeout>|undefined,failures=0;
  function wake(){setEntries(processing.snapshot());setFailure(processing.failure);if(!authBlocked&&!checking&&!timer&&processing.snapshot().some(v=>!v.request||v.settled))void check();}
  async function check(){
   if(!live||checking||authBlocked)return;checking=true;const before=processing.serial;
   try{const values=await api('/tasks/active');if(live){failures=0;setSignIn(false);processing.reconcile(values,before);}}
   catch(e){if(live){failures++;authBlocked=[401,403].includes((e as any)?.status);setSignIn(authBlocked);processing.disconnected();}}
   finally{checking=false;if(live&&!authBlocked&&processing.snapshot().some(v=>!v.request||v.settled))timer=setTimeout(()=>{timer=undefined;void check();},Math.min(2000*2**failures,10000));}
  }
  const off=processing.subscribe(wake);const focus=()=>{if(timer){clearTimeout(timer);timer=undefined;}authBlocked=false;void check();};window.addEventListener('focus',focus);wake();void check();
  return()=>{live=false;off();if(timer)clearTimeout(timer);window.removeEventListener('focus',focus);};
 },[account,retry]);
 const docked=coachHost&&!host?entries.filter(isCoachProcessing):[],pageEntries=docked.length?entries.filter(v=>!isCoachProcessing(v)):entries;
 const {confirmed,uncertain}=processingGroups(pageEntries),recover=!!uncertain.length||signIn;
 async function reconnect(){setCheckingStatus(true);setRecoveryError('');try{await onReconnect();setSignIn(false);setRetry(v=>v+1);}catch(e){setSignIn([401,403].includes((e as any)?.status));setRecoveryError((e as Error).message);}finally{setCheckingStatus(false);}}
 const recoveryPanel=<div className="processing-recovery" role="status"><strong>{signIn?'Sign in to reconnect':'Status connection lost'}</strong><p>{signIn?'Your sign-in needs renewing. Open sign-in in a separate tab, then return here.':'Recent requests could not be confirmed. They may have finished or may still be running.'} Keep this tab open to preserve unsent changes. Check saved status before sending another request.</p><div className="card-actions"><a href="/" target="_blank" rel="noopener noreferrer">Sign in in a new tab ↗</a><button type="button" className="button secondary" disabled={checkingStatus} onClick={reconnect}>{checkingStatus?'Checking saved status…':'Check saved status · no new AI request'}</button></div>{recoveryError&&<p>{recoveryError}</p>}</div>;
 const panel=<div className={entries.length||busy||signIn?'global-processing active':'global-processing'}>
  {confirmed.length>1&&<p className="small processing-count">{confirmed.length} actions in progress</p>}
  {confirmed.map(value=><TaskProgressBanner key={value.id} task={value} onStop={async()=>{const result=await api('/tasks/'+encodeURIComponent(value.id)+'/cancel','POST',{});processing.update(result);if(result.already_finished)await onReconnect();}}/>)}
  {recover&&recoveryPanel}

  <StatusBanner busy={entries.length||signIn?'':busy} error={error||failure} message={message} onDismiss={()=>{processing.clearFailure();onDismiss();}}/>
 </div>;
 return <>{host?createPortal(panel,host):panel}{coachHost&&!host&&createPortal(<>{docked.map(value=><TaskProgressBanner key={value.id} task={value} onStop={async()=>{const result=await api('/tasks/'+encodeURIComponent(value.id)+'/cancel','POST',{});processing.update(result);if(result.already_finished)await onReconnect();}}/>)}{docked.some(v=>v.connection_lost||v.status==='unknown')&&recoveryPanel}</>,coachHost)}</>;
}
