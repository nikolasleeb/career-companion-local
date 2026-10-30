import React,{useEffect,useState} from 'react';
import {setRoute} from './appRoute';
export function WorkStyleContextLink({api,onOpen}:{api:any;onOpen?:()=>void}){
 const [status,setStatus]=useState<any>(null);
 useEffect(()=>{let live=true;const load=()=>api('/profile/work-preferences').then((r:any)=>{if(live)setStatus(r);}).catch(()=>{});void load();window.addEventListener('career-context-updated',load);return()=>{live=false;window.removeEventListener('career-context-updated',load);};},[api]);
 return <div className="work-style-context-link"><span className="small muted">Work Styles{status?' · '+(status.assessment.completed?'assessment completed':'assessment not completed')+' · '+(status.sharing_enabled?'reviewed summary sharing on':'summary sharing off'):''}</span> <button className="text-button" type="button" onClick={()=>{onOpen?.();setRoute({view:'master',tab:'workstyles'});}}>View/manage Work Styles</button></div>;
}
