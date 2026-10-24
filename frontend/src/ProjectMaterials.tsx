import React,{useLayoutEffect,useRef} from 'react';
import {ProjectSources,Services} from './EvidenceTools';
import {ProfileProjectRequest} from './projectFlow';
import {StatusBanner} from './StatusBanner';

// Closing hides the native dialog; it never unmounts its file picker, preparation or review.
export function ProjectMaterialsDialog({services,request,open,onClose,onLibraryChange}:{services:Services&{error?:string;message?:string};request?:ProfileProjectRequest;open:boolean;onClose:()=>void;onLibraryChange:(library:any)=>void}){
 const ref=useRef<HTMLDialogElement>(null),heading=useRef<HTMLHeadingElement>(null);
 useLayoutEffect(()=>{const dialog=ref.current;if(!dialog)return;if(open&&!dialog.open){dialog.showModal();heading.current?.focus();}else if(!open&&dialog.open)dialog.close();},[open]);
 useLayoutEffect(()=>()=>{ref.current?.close();},[]);
 return <dialog ref={ref} className="wide-dialog project-materials-dialog" aria-labelledby={'materials-title-'+(request?.experienceId||'other')} onCancel={e=>{e.preventDefault();onClose();}}><div className="modal-head"><h2 ref={heading} tabIndex={-1} id={'materials-title-'+(request?.experienceId||'other')}>Project materials — {request?.title||'Other projects'}</h2><button type="button" className="icon-button" aria-label="Close project materials" onClick={onClose}>×</button></div><p className="small muted">Closing keeps your work and any running analysis. Opening materials never starts an OpenAI request.</p><StatusBanner busy={services.busy} error={services.error||''} message={services.message||''}/><ProjectSources services={services} embedded profileRequest={request} scopeExperienceId={request?.experienceId||''} active={open} onLibraryChange={onLibraryChange}/></dialog>;
}
