import React,{useEffect,useState} from 'react';
import {requestJSON} from './apiClient';
import {monitorConnection,connectionLabels,ConnectionState} from './connectionMonitor';
import './workspaceConnection.css';
export function WorkspaceConnection({account,hosted,aiSaved}:{account:string;hosted:boolean;aiSaved:boolean}){
 const [state,setState]=useState<ConnectionState>('checking');
 useEffect(()=>{setState('checking');return monitorConnection(async signal=>{const me=await requestJSON('/me','GET',undefined,'',signal);if(me?.id!==account)throw {status:401};},setState,{window,document,online:()=>navigator.onLine,setTimeout:(fn,ms)=>window.setTimeout(fn,ms),clearTimeout:id=>window.clearTimeout(id)});},[account]);
 return <span className={'local-status workspace-connection '+state} role="status" title="Connection to your Career Companion workspace. A saved AI key has not been tested against its provider."><span className="workspace-connection-state"><i aria-hidden="true"/>{connectionLabels[state]}</span><span>{hosted?'Private hosted workspace':'Local workspace'} · {aiSaved?'AI key saved':'AI key not configured'}</span></span>;
}
