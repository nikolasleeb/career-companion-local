import {ApiError,pollTask} from './apiClient';
const key=(account:string,session:string)=>'interview-action:'+account+':'+session;
export function pendingInterview(account:string,session:string,storage:Storage=localStorage){try{return JSON.parse(storage.getItem(key(account,session))||'null');}catch{return null;}}
export function clearInterview(account:string,session:string,storage:Storage=localStorage){storage.removeItem(key(account,session));}
export async function interviewAction(account:string,session:string,body:any,call:any,storage:Storage=localStorage){
 const signature=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(body))))).map(v=>v.toString(16).padStart(2,'0')).join('');
 let saved=pendingInterview(account,session,storage);
 if(saved&&saved.signature!==signature)throw Error('Check the saved status of the previous interview request first.');
 saved=saved||{token:crypto.randomUUID(),signature};storage.setItem(key(account,session),JSON.stringify(saved));
 try{
  if(!saved.id){const initial=await call('/interview-practice/sessions/'+session+'/actions','POST',{...body,request_token:saved.token});if(typeof initial.task_id!=='string'||!initial.task_id)throw new ApiError('The interview start could not be confirmed. Check its saved status.',502);saved.id=initial.task_id;storage.setItem(key(account,session),JSON.stringify(saved));}
  const result=await pollTask(saved.id,call,undefined,1200);clearInterview(account,session,storage);return result;
 }catch(e){if(e instanceof ApiError&&[400,404,409,422,499].includes(e.status))clearInterview(account,session,storage);throw e;}
}
export async function recoverInterview(account:string,session:string,call:any,storage:Storage=localStorage){
 const saved=pendingInterview(account,session,storage);if(!saved)throw Error('No pending interview request is saved.');
 if(!saved.id){const result=await call('/interview-practice/actions/'+saved.token);saved.id=result.task_id;storage.setItem(key(account,session),JSON.stringify(saved));}
 try{const result=await pollTask(saved.id,call,undefined,1200);clearInterview(account,session,storage);return result;}
 catch(e){if(e instanceof ApiError&&[400,422,499].includes(e.status))clearInterview(account,session,storage);throw e;}
}
export function readInterviewDraft(account:string,id:string,fallback:any,storage:Storage=sessionStorage){try{return JSON.parse(storage.getItem('interview-draft:'+account+':'+id)||'null')||fallback;}catch{return fallback;}}
export function saveInterviewDraft(account:string,id:string,value:any,storage:Storage=sessionStorage){try{storage.setItem('interview-draft:'+account+':'+id,JSON.stringify(value));}catch{}}
