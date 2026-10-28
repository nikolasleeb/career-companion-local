import React,{useEffect,useState} from 'react';
import {requestJSON} from './apiClient';
import {monitorConnection,connectionLabels,ConnectionState} from './connectionMonitor';
import './workspaceConnection.css';
export function WorkspaceConnection({account,hosted,aiSaved,aiTest}:{account:string;hosted:boolean;aiSaved:boolean;aiTest?:any}){
 const [state,setState]=useState<ConnectionState>('checking');
 useEffect(()=>{setState('checking');return monitorConnection(async signal=>{const me=await requestJSON('/me','GET',undefined,'',signal);if(me?.id!==account)throw {status:401};},setState,{window,document,online:()=>navigator.onLine,setTimeout:(fn,ms)=>window.setTimeout(fn,ms),clearTimeout:id=>window.clearTimeout(id)});},[account]);
 return <span className={'local-status workspace-connection '+state} role="status" title={aiTest?.status==='tested_successfully'?'Workspace connected. Text generation tested successfully with '+aiTest.tested_model+' at '+new Date(aiTest.tested_at).toLocaleString()+'. Voice and other features were not tested.':'Connection to your Career Companion workspace. Saved credentials are separate from a successful provider test.'}><span className="workspace-connection-state"><i aria-hidden="true"/>{connectionLabels[state]}</span><span>{hosted?'Private hosted workspace':'Local workspace'} · {aiSaved?(aiTest?.status==='tested_successfully'?'AI key tested':'AI key saved'):'AI key not configured'}</span></span>;
}
