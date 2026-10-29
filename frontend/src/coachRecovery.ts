import {ApiError,pollTask} from './apiClient';
const key=(account:string,chat:string)=>'career-coach-action:'+account+':'+chat;
export function pendingCoach(account:string,chat:string,storage:Storage=localStorage){try{return JSON.parse(storage.getItem(key(account,chat))||'null');}catch{return null;}}
export function clearCoach(account:string,chat:string,storage:Storage=localStorage){storage.removeItem(key(account,chat));}
export async function coachAction(account:string,chat:string,body:any,call:any,onUpdate?:any,storage:Storage=localStorage){
 const path='/career-coach/chats/'+chat+'/actions';
 const signature=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(body))))).map(v=>v.toString(16).padStart(2,'0')).join('');
 let saved=pendingCoach(account,chat,storage);
 if(saved&&saved.signature!==signature)throw Error('Check the saved status of the previous coaching request before starting another in this chat.');
 saved=saved||{token:crypto.randomUUID(),signature};storage.setItem(key(account,chat),JSON.stringify(saved));
 try{
  if(!saved.id){const initial=await call(path,'POST',{...body,request_token:saved.token});if(!initial.task_id)throw new ApiError('The coaching request could not be confirmed. Check its saved status.',502);saved.id=initial.task_id;storage.setItem(key(account,chat),JSON.stringify(saved));}
  const result=await pollTask(saved.id,call,undefined,1200,onUpdate);clearCoach(account,chat,storage);return result;
 }catch(e){if(e instanceof ApiError&&[400,404,409,422,499].includes(e.status))clearCoach(account,chat,storage);throw e;}
}
export async function recoverCoach(account:string,chat:string,call:any,onUpdate?:any,storage:Storage=localStorage){
 const saved=pendingCoach(account,chat,storage);if(!saved)throw Error('No unconfirmed coaching request is saved.');
 if(!saved.id){const value=await call('/career-coach/actions/'+saved.token);saved.id=value.task_id;storage.setItem(key(account,chat),JSON.stringify(saved));}
 try{const result=await pollTask(saved.id,call,undefined,1200,onUpdate);clearCoach(account,chat,storage);return result;}
 catch(e){if(e instanceof ApiError&&[400,422,499].includes(e.status))clearCoach(account,chat,storage);throw e;}
}
export function initialCoachDraft(account:string,id:string,fallback:string,storage:Storage=sessionStorage){try{return storage.getItem('career-coach-draft:'+account+':'+id)??fallback;}catch{return fallback;}}

export function draftAfterSend(current:string,sent:string){return current===sent?'':current;}
export function clearCoachBrowser(account:string,local:Storage=localStorage,session:Storage=sessionStorage){
 for(const storage of [local,session])try{for(let i=storage.length-1;i>=0;i--){const k=storage.key(i)||'';if(k.startsWith('career-coach-action:'+account+':')||k.startsWith('career-explicit-draft:'+account+':')||k==='career-plan-input:'+account||k.startsWith('career-plan-input:'+account+':')||k.startsWith('career-coach-draft:'+account+':')||k==='career-coach-selected:'+account)storage.removeItem(k);}}catch{}
}
