import {ApiError,pollTask} from './apiClient';
type Call=(path:string,method?:string,body?:any)=>Promise<any>;
export async function documentTask(account:string,path:string,body:any,call:Call,onProgress?:(value:any)=>void,storage:Storage=localStorage){
 const key='next-step-document-task:'+account+':'+path;
 let pending:any;try{pending=JSON.parse(storage.getItem(key)||'null');}catch{}
 const recovering=!!pending;
 if(!pending){pending={token:crypto.randomUUID(),body:{...body},created_at:new Date().toISOString()};pending.body.request_token=pending.token;storage.setItem(key,JSON.stringify(pending));}
 let terminal=false;
 const report=(value:any)=>{if(['completed','failed','cancelled','interrupted'].includes(value.status))terminal=true;onProgress?.(value);};
 try{
  if(!pending.id){
   let initial:any;
   if(recovering){
    try{initial=await call('/document-models/tasks/status?request_token='+encodeURIComponent(pending.token));}
    catch(e){if(!(e instanceof ApiError&&e.status===404))throw e;}
   }
   // Reusing the original payload and token is server-idempotent even when a
   // start response was lost. Never dispatch a newly generated token on recovery.
   if(!initial)initial=await call(path,'POST',pending.body);
   if(initial.cached){storage.removeItem(key);return initial.result;}
   pending.id=initial.task_id;storage.setItem(key,JSON.stringify(pending));
  }
  const result=await pollTask(pending.id,call,undefined,600,report);
  storage.removeItem(key);return result;
 }catch(error){
  if(terminal||error instanceof ApiError&&!error.transient&&![401,403].includes(error.status))storage.removeItem(key);
  else {
   // A free owned-token lookup can identify an accepted start even when its
   // response was lost. Never create or repeat a paid action in this branch.
   if(!pending.id){try{const known=await call('/document-models/tasks/status?request_token='+encodeURIComponent(pending.token));if(known?.task_id){pending.id=known.task_id;storage.setItem(key,JSON.stringify(pending));}}catch{}}
   report({id:pending.id,status:'unknown',connection_lost:true,created_at:pending.created_at});
  }
  throw error;
 }
}
export function clearRecoveredDocumentTask(account:string,workspace:string,task:string,storage:Storage=localStorage){
 const prefix='next-step-document-task:'+account+':';
 for(const key of Object.keys(storage)){
  if(!key.startsWith(prefix)||!key.includes('/'+workspace+'/'))continue;
  try{const pending=JSON.parse(storage.getItem(key)||'null');if(!pending?.id||pending.id===task)storage.removeItem(key);}catch{}
 }
}
