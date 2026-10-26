import {ApiError,pollTask} from './apiClient';
const key=(account:string,scope:string)=>'career-foreground:'+account+':'+scope;
export function pendingAction(account:string,scope:string){try{return JSON.parse(localStorage.getItem(key(account,scope))||'null');}catch{return null;}}
export async function foregroundAction(account:string,scope:string,path:string,body:any,call:any){
 let p=pendingAction(account,scope);const signature=JSON.stringify({path,body});
 if(p&&p.signature!==signature)throw Error('Check the saved status of the previous action before sending a different request.');
 if(!p){p={token:crypto.randomUUID(),signature};localStorage.setItem(key(account,scope),JSON.stringify(p));}
 try{
  if(!p.id){const result=await call(path,'POST',{...body,request_token:p.token});if(!result.task_id)throw new ApiError('The request start could not be confirmed. Check saved status.',502);p.id=result.task_id;localStorage.setItem(key(account,scope),JSON.stringify(p));}
  const result=await pollTask(p.id,call,undefined,1200);localStorage.removeItem(key(account,scope));return result;
 }catch(e){if(e instanceof ApiError&&[400,404,409,422,499].includes(e.status))localStorage.removeItem(key(account,scope));throw e;}
}
export async function recoverAction(account:string,scope:string,call:any){
 const p=pendingAction(account,scope);if(!p)throw Error('No pending action is saved.');
 if(!p.id){const r=await call('/ai-actions/'+p.token);p.id=r.task_id;localStorage.setItem(key(account,scope),JSON.stringify(p));}
 try{const result=await pollTask(p.id,call,undefined,1200);localStorage.removeItem(key(account,scope));return result;}
 catch(e){if(e instanceof ApiError&&[422,499].includes(e.status))localStorage.removeItem(key(account,scope));throw e;}
}
export function clearUnconfirmed(account:string,scope:string){localStorage.removeItem(key(account,scope));}
