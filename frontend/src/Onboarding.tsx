import React,{useEffect,useId,useState} from 'react';
export type SetupSection={id:string;title:string;status:string;confirmed_count:number;draft_count:number;can_mark_empty:boolean};
export type SetupState={welcome_pending?:boolean;welcome_dismissed_at?:string;version:number;profile_signature:string;completed:boolean;ready:boolean;sections:SetupSection[];completed_at:string};
export function ProfilePane({id,title,summary,status,open,onToggle,children}:{id:string;title:string;summary:string;status:string;open:boolean;onToggle:()=>void;children:React.ReactNode}){
 return <section className="panel profile-pane" id={'profile-'+id} aria-labelledby={'profile-'+id+'-title'}><h2 className="profile-pane-heading"><button id={'profile-'+id+'-title'} type="button" aria-expanded={open} aria-controls={'profile-'+id+'-content'} onClick={onToggle}><span><span className="profile-pane-name">{title}</span><span className="profile-pane-summary">{summary}</span></span><span className="profile-pane-status">{status}<span aria-hidden="true">{open?'−':'+'}</span></span></button></h2><div id={'profile-'+id+'-content'} className="profile-pane-content" hidden={!open}>{children}</div></section>;
}
export function EmptyDecision({section,busy,onEmpty}:{section:SetupSection;busy:boolean;onEmpty:(section:string,empty:boolean)=>Promise<void>}){
 return section.can_mark_empty?<button type="button" className="text-button" disabled={busy} onClick={()=>onEmpty(section.id,section.status!=='empty')}>{section.status==='empty'?'Undo empty section':'Nothing to add yet'}</button>:null;
}

export function ActionExplanation({reason,children}:{reason:string;children:React.ReactNode}){
 const id=useId(),[hovered,setHovered]=useState(false),[focused,setFocused]=useState(false),[dismissed,setDismissed]=useState(false);
 useEffect(()=>{if(!reason||!(hovered||focused)||dismissed)return;const dismiss=(event:KeyboardEvent)=>{if(event.key==='Escape')setDismissed(true);};window.addEventListener('keydown',dismiss);return()=>window.removeEventListener('keydown',dismiss);},[reason,hovered,focused,dismissed]);
 return <span className="action-explanation" role={reason?'group':undefined} tabIndex={reason?0:undefined} aria-label={reason?'Why Finish setup & open Applications is unavailable':undefined} aria-describedby={reason?id:undefined} onMouseEnter={()=>{setHovered(true);setDismissed(false);}} onMouseLeave={()=>setHovered(false)} onFocus={()=>{setFocused(true);setDismissed(false);}} onBlur={()=>setFocused(false)} onKeyDown={e=>{if(e.key==='Escape'){setDismissed(true);e.stopPropagation();}}}>
 {children}{reason&&<span id={id} role="tooltip" className="action-explanation-tooltip" hidden={!(hovered||focused)||dismissed}>{reason}</span>}
 </span>;
}
