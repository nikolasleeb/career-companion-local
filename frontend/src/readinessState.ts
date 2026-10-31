import {ApiError,pollTask} from './apiClient';
export const readinessDraftKey=(account:string,id='new')=>'readiness-draft:'+account+':'+id;
const actionKey=(account:string,id:string)=>'readiness-action:'+account+':'+id;
export function pendingReadiness(account:string,id:string){try{return JSON.parse(localStorage.getItem(actionKey(account,id))||'null');}catch{return null;}}
export function clearReadiness(account:string,id:string){localStorage.removeItem(actionKey(account,id));}
export async function readinessAction(account:string,id:string,body:any,call:any,onUpdate:any){
 const prior=pendingReadiness(account,id);if(prior)throw Error('Check the saved status before starting another action.');
 const saved:any={token:crypto.randomUUID()};localStorage.setItem(actionKey(account,id),JSON.stringify(saved));
 try{
  const result=await call('/career-readiness/sessions/'+id+'/actions','POST',{...body,request_token:saved.token});
  saved.id=result.task_id;localStorage.setItem(actionKey(account,id),JSON.stringify(saved));
  const value=await pollTask(saved.id,call,undefined,1200,onUpdate);clearReadiness(account,id);return value;
 }catch(e){if(e instanceof ApiError&&[400,404,409,422,499].includes(e.status))clearReadiness(account,id);throw e;}
}
export async function recoverReadiness(account:string,id:string,call:any,onUpdate:any){
 const saved=pendingReadiness(account,id);if(!saved)throw Error('No unconfirmed readiness action is saved.');
 if(!saved.id){const result=await call('/career-readiness/actions/'+saved.token);saved.id=result.task_id;localStorage.setItem(actionKey(account,id),JSON.stringify(saved));}
 try{const value=await pollTask(saved.id,call,undefined,1200,onUpdate);clearReadiness(account,id);return value;}
 catch(e){if(e instanceof ApiError&&[400,404,422,499].includes(e.status))clearReadiness(account,id);throw e;}
}
export function readReadinessDraft(account:string,id:string,fallback:any){try{return JSON.parse(sessionStorage.getItem(readinessDraftKey(account,id))||'null')||fallback;}catch{return fallback;}}
