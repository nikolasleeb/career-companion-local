import React,{useId,useLayoutEffect,useRef,useState} from 'react';

type Props={title:string;onClose:()=>void;onDelete:()=>Promise<void>;fallbackFocus:React.RefObject<HTMLElement|null>};
export function InterviewDeleteDialog({title,onClose,onDelete,fallbackFocus}:Props){
 const dialog=useRef<HTMLDialogElement>(null),cancel=useRef<HTMLButtonElement>(null),locked=useRef(false),alive=useRef(false);
 const [pending,setPending]=useState(false),[error,setError]=useState('');const id=useId();
 useLayoutEffect(()=>{
  const element=dialog.current,origin=document.activeElement as HTMLElement|null;alive.current=true;
  element?.showModal();cancel.current?.focus();
  return()=>{alive.current=false;element?.close();queueMicrotask(()=>{const target=origin?.isConnected&&!origin.closest('[hidden]')?origin:fallbackFocus.current;if(target?.isConnected&&!target.closest('[hidden]'))target.focus();});};
 },[fallbackFocus]);
 useLayoutEffect(()=>{if(pending)dialog.current?.focus();},[pending]);
 function containFocus(event:React.KeyboardEvent<HTMLDialogElement>){
  if(event.key!=='Tab')return;
  const controls=Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'));
  const index=controls.indexOf(document.activeElement as HTMLButtonElement);
  if(!controls.length){event.preventDefault();event.currentTarget.focus();}
  else if(index<0||event.shiftKey&&index===0||!event.shiftKey&&index===controls.length-1){event.preventDefault();controls[event.shiftKey?controls.length-1:0].focus();}
 }
 async function remove(){
  if(locked.current)return;locked.current=true;setPending(true);setError('');
  try{await onDelete();}catch(e){if(alive.current)setError((e as Error).message||'The practice session could not be deleted. Please try again.');}
  finally{locked.current=false;if(alive.current)setPending(false);}
 }
 return <dialog ref={dialog} className="interview-delete-dialog" role="alertdialog" aria-modal="true" aria-labelledby={id+'-title'} aria-describedby={id+'-description'} aria-busy={pending} tabIndex={-1} onKeyDown={containFocus} onCancel={e=>{e.preventDefault();if(!locked.current)onClose();}}>
  <div className="modal-head"><h2 id={id+'-title'}>Delete “{title}”?</h2><button type="button" className="icon-button" aria-label="Close deletion confirmation" disabled={pending} onClick={()=>{if(!locked.current)onClose();}}>×</button></div>
  <p id={id+'-description'}>This deletes the practice session, its questions, saved attempts and research. Preparation PDFs, Profile and applications are kept.</p>
  {error&&<p role="alert" className="notice">{error}</p>}
  {pending&&<p role="status" className="small muted">Deleting practice session…</p>}
  <div className="card-actions"><button ref={cancel} type="button" className="button secondary" disabled={pending} onClick={()=>{if(!locked.current)onClose();}}>Cancel</button><button type="button" className="button primary destructive" disabled={pending} onClick={()=>void remove()}>{pending?'Deleting…':'Delete practice session'}</button></div>
 </dialog>;
}
