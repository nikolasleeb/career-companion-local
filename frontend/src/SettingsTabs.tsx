import {useRouteTab} from './appRoute';
import React,{useEffect,useRef,useState} from 'react';
import './settingsTabs.css';
type Panel={id:string;label:string;content:React.ReactNode};
export function SettingsTabs({accountId,panels,localPanel}:{accountId:string;panels:Panel[];localPanel?:React.ReactNode}){
 const choices=localPanel?[...panels,{id:'app',label:'App & storage',content:localPanel}]:panels;
 const key='career-settings-tab:'+accountId;
 const initial=()=>{try{const id=sessionStorage.getItem(key)||'ai';return choices.some(p=>p.id===id)?id:'ai';}catch{return 'ai';}};
 const [requested,setRequested]=useRouteTab('settings',initial()),active=choices.some(p=>p.id===requested)?requested:'connections',[visited,setVisited]=useState(()=>new Set([active]));const list=useRef<HTMLDivElement>(null);
 useEffect(()=>setVisited(v=>new Set([...v,active])),[active]);
 function select(id:string){if(!choices.some(p=>p.id===id))return;setRequested(id);setVisited(v=>new Set([...v,id]));try{sessionStorage.setItem(key,id);}catch{}}
 useEffect(()=>{const handler=(e:Event)=>select((e as CustomEvent).detail);window.addEventListener('career-settings-tab',handler);return()=>window.removeEventListener('career-settings-tab',handler);},[accountId]);
 return <div className="settings-layout"><div className="settings-tablist" ref={list} role="tablist" aria-label="Settings sections" onKeyDown={e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const tabs=Array.from(list.current!.querySelectorAll<HTMLButtonElement>('[role=tab]'));const at=tabs.indexOf(document.activeElement as HTMLButtonElement);const next=e.key==='Home'?0:e.key==='End'?tabs.length-1:(at+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[next].focus();}}>{choices.map(p=><button type="button" id={'settings-tab-'+p.id} key={p.id} role="tab" aria-selected={active===p.id} aria-controls={'settings-panel-'+p.id} tabIndex={active===p.id?0:-1} onClick={()=>select(p.id)}>{p.label}</button>)}</div>{choices.map(p=><section className="settings-panel" key={p.id} id={'settings-panel-'+p.id} role="tabpanel" aria-labelledby={'settings-tab-'+p.id} hidden={active!==p.id}>{visited.has(p.id)?p.content:null}</section>)}</div>;
}
