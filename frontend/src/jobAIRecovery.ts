import {ApiError,pollTask} from './apiClient';
const key=(account:string)=>'next-step-job-ai:'+account;
export function pendingJobAI(account:string,storage:Storage=localStorage){try{return JSON.parse(storage.getItem(key(account))||'null');}catch{return null;}}
export function forgetJobAI(account:string,storage:Storage=localStorage){storage.removeItem(key(account));}
export async function paidJobAction(account:string,path:string,body:any,call:any,onUpdate?:any,storage:Storage=localStorage){
 const signature=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify({path,body}))))).map(v=>v.toString(16).padStart(2,'0')).join('');
 let pending=pendingJobAI(account,storage);
 if(pending&&pending.signature!==signature)throw Error('A previous AI action has an unconfirmed outcome. Check its saved status before starting another action.');
 pending=pending||{signature,token:crypto.randomUUID(),path};storage.setItem(key(account),JSON.stringify(pending));
 try{
  if(!pending.id){const first=await call(path,'POST',{...body,request_token:pending.token});if(first.cached){forgetJobAI(account,storage);return first.result;}pending.id=first.task_id;if(!pending.id)throw new ApiError('The start response could not be confirmed. Check saved status.',502);storage.setItem(key(account),JSON.stringify(pending));}
  onUpdate?.({id:pending.id,status:'queued'});
  const result=await pollTask(pending.id,call,undefined,path.includes('/match')?3600:600,onUpdate);forgetJobAI(account,storage);return result;
 }catch(e){if(e instanceof ApiError&&[400,404,409,422].includes(e.status))forgetJobAI(account,storage);throw e;}
}
export async function recoverJobAction(account:string,call:any,storage:Storage=localStorage){
 const pending=pendingJobAI(account,storage);if(!pending)throw Error('There is no unconfirmed AI action.');
 if(!pending.id){const saved=await call('/job-search/ai/actions/'+pending.token);pending.id=saved.task_id;storage.setItem(key(account),JSON.stringify(pending));}
 try{const result=await pollTask(pending.id,call,undefined,pending.path.includes('/match')?3600:600);forgetJobAI(account,storage);return result;}
 catch(e){if(e instanceof ApiError&&[404,422].includes(e.status))forgetJobAI(account,storage);throw e;}
}
