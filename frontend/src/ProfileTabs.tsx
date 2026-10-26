import React,{useEffect,useRef,useState} from 'react';
import './profileTabs.css';
import {profileTabs,ProfileTab} from './profileTabState';
export {profileTabs,savedProfileTab} from './profileTabState';
export type {ProfileTab} from './profileTabState';
export function ProfileTabs({active,onSelect,panels}:{active:ProfileTab;onSelect:(id:ProfileTab)=>void;panels:Record<ProfileTab,React.ReactNode>}){
 const list=useRef<HTMLDivElement>(null),[visited,setVisited]=useState(()=>new Set<ProfileTab>([active]));
 useEffect(()=>setVisited(old=>old.has(active)?old:new Set([...old,active])),[active]);
 function select(id:ProfileTab){setVisited(old=>new Set([...old,id]));onSelect(id);}
 return <div className="profile-tabs"><div className="profile-tablist" ref={list} role="tablist" aria-label="Profile sections" onKeyDown={e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const tabs=Array.from(list.current!.querySelectorAll<HTMLButtonElement>('[role=tab]'));const at=tabs.indexOf(document.activeElement as HTMLButtonElement);const next=e.key==='Home'?0:e.key==='End'?tabs.length-1:(at+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[next].focus();select(profileTabs[next].id);}}>{profileTabs.map(p=><button type="button" role="tab" id={'profile-tab-'+p.id} key={p.id} aria-selected={active===p.id} aria-controls={'profile-panel-'+p.id} tabIndex={active===p.id?0:-1} onClick={()=>select(p.id)}>{p.label}</button>)}</div>{profileTabs.map(p=><section key={p.id} id={'profile-panel-'+p.id} role="tabpanel" aria-labelledby={'profile-tab-'+p.id} hidden={active!==p.id}>{visited.has(p.id)||active===p.id?panels[p.id]:null}</section>)}</div>;
}
