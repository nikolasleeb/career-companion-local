import React,{useEffect,useState} from 'react';
import {requestJSON} from './apiClient';
import {monitorBuild,validBuild} from './buildMonitor';
import './serverUpdate.css';
declare const __APP_BUILD_ID__:string;
export const loadedBuild=typeof __APP_BUILD_ID__==='string'?__APP_BUILD_ID__:'';
export function ServerUpdateBanner({account}:{account:string}){
 const key='career-companion-update:'+account;
 const [latest,setLatest]=useState('');
 const [dismissed,setDismissed]=useState(()=>{try{return sessionStorage.getItem(key)||'';}catch{return '';}});
 useEffect(()=>{
  if(!validBuild(loadedBuild))return;
  return monitorBuild(signal=>requestJSON('/version','GET',undefined,'',signal),setLatest,{window,document,online:()=>navigator.onLine,now:()=>Date.now(),setTimeout:(fn,ms)=>window.setTimeout(fn,ms),clearTimeout:id=>window.clearTimeout(id)});
 },[account]);
 if(!latest||latest===loadedBuild||latest===dismissed)return null;
 function dismiss(){setDismissed(latest);try{sessionStorage.setItem(key,latest);}catch{}}
 return <aside className="server-update-banner" role="status" aria-label="Workspace update available"><div><strong>Update available</strong><p>A new version of Career Companion is ready. Save any edits, then reload to get the latest changes.</p></div><div className="server-update-actions"><button type="button" className="button primary" onClick={()=>window.location.reload()}>Reload now</button><button type="button" className="button secondary" onClick={dismiss} aria-label="Dismiss update notification">Dismiss</button></div></aside>;
}
