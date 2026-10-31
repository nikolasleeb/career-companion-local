import React,{useEffect,useLayoutEffect,useRef,useState,useSyncExternalStore} from 'react';
import './workspaceControls.css';

type Options={title?:string;message:string;confirmLabel?:string;cancelLabel?:string;value?:string;label?:string;maxLength?:number;danger?:boolean};
type Request=Options&{kind:'confirm'|'text';origin:HTMLElement|null;resolve:(value:any)=>void};
let queue:Request[]=[];const listeners=new Set<()=>void>();const emit=()=>listeners.forEach(fn=>fn());
function request(kind:Request['kind'],options:Options|string):Promise<any>{return new Promise(resolve=>{queue.push({...(typeof options==='string'?{message:options}:options),kind,origin:document.activeElement as HTMLElement,resolve});emit();});}
export const confirmAction=(options:Options|string):Promise<boolean>=>request('confirm',options);
export const requestText=(options:Options):Promise<string|null>=>request('text',options);
function settle(value:any){const current=queue.shift();current?.resolve(value);emit();queueMicrotask(()=>{if(!queue.length&&current?.origin?.isConnected&&!current.origin.closest('[hidden], [inert]'))current.origin.focus({preventScroll:true});});}
export function WorkspaceDialogHost({account}:{account:string}){
 const current=useSyncExternalStore(fn=>{listeners.add(fn);return()=>{listeners.delete(fn);};},()=>queue[0]||null,()=>null);
 const ref=useRef<HTMLDialogElement>(null),cancel=useRef<HTMLButtonElement>(null),input=useRef<HTMLInputElement>(null),[value,setValue]=useState('');
 useEffect(()=>()=>{const pending=queue;queue=[];pending.forEach(r=>r.resolve(r.kind==='text'?null:false));emit();},[account]);
 useLayoutEffect(()=>{if(current){setValue(current.value||'');ref.current?.showModal();cancel.current?.focus();}else ref.current?.close();},[current]);
 return <dialog ref={ref} className="workspace-dialog" aria-labelledby="workspace-dialog-title" aria-describedby="workspace-dialog-message" onCancel={e=>{e.preventDefault();settle(current?.kind==='text'?null:false);}}>
  {current&&<form onSubmit={e=>{e.preventDefault();settle(current.kind==='text'?value.trim():true);}}>
   <h2 id="workspace-dialog-title">{current.title||(current.kind==='text'?'Edit text':'Confirm action')}</h2><p id="workspace-dialog-message">{current.message}</p>
   {current.kind==='text'&&<label>{current.label||'Text'}<input ref={input} value={value} maxLength={current.maxLength||200} onChange={e=>setValue(e.target.value)}/></label>}
   <div className="card-actions"><button ref={cancel} type="button" className="button secondary" onClick={()=>settle(current.kind==='text'?null:false)}>{current.cancelLabel||'Cancel'}</button><button type="submit" className={'button '+(current.danger?'danger':'primary')} disabled={current.kind==='text'&&!value.trim()}>{current.confirmLabel||(current.kind==='text'?'Save text':'Confirm')}</button></div>
  </form>}
 </dialog>;
}
export function useModalActive(){const [active,setActive]=useState(false);useEffect(()=>{const update=()=>setActive(!!document.querySelector('dialog[open]'));update();const observer=new MutationObserver(update);observer.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['open']});return()=>observer.disconnect();},[]);return active;}

export function useUnsavedWarning(dirty:boolean){useEffect(()=>{const warn=(event:BeforeUnloadEvent)=>{if(dirty){event.preventDefault();event.returnValue='';}};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);},[dirty]);}
