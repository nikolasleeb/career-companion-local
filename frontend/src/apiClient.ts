export class ApiError extends Error{
 constructor(message:string,public status=0,public recovery:''|'access'=''){super(message);this.name='ApiError';}
 get transient(){return this.status===0||this.status===429||this.status>=500;}
}

export async function requestJSON(path:string,method='GET',body?:unknown,csrf=''){
 const headers:Record<string,string>={'X-Requested-With':'XMLHttpRequest'};
 if(method!=='GET')headers['X-CSRF-Token']=csrf;
 if(body!==undefined&&!(body instanceof FormData))headers['Content-Type']='application/json';
 let response:Response;
 try{response=await fetch('/api'+path,{method,headers,credentials:'same-origin',body:body===undefined?undefined:body instanceof FormData?body:JSON.stringify(body)});}
 catch{throw new ApiError('The connection to the app was interrupted. Your saved inputs remain available. Check the connection and try again.');}
 const accessExpired=()=>new ApiError('Your secure access verification expired. Reload the sign-in page to verify your email, then sign in again.',response.status===403?403:401,'access');
 // Access may return its HTML login page instead of the app's JSON response.
 // Never replay a credential POST or follow an authentication URL from a response.
 if(response.redirected){try{const destination=new URL(response.url);if(destination.hostname.endsWith('.cloudflareaccess.com')||destination.pathname.startsWith('/cdn-cgi/access/'))throw accessExpired();}catch(error){if(error instanceof ApiError)throw error;}}
 if(response.status===401&&path!=='/auth/login')throw new ApiError('Your session expired. Sign in in a new tab, then check saved status here. Keep this tab open to preserve unsent changes.',401);
 if(response.status===204)return null;
 let data:any;
 try{data=await response.json();}catch{if(response.status===401||response.status===403)throw accessExpired();throw new ApiError('The app returned an unreadable response. Your saved inputs remain available. Try checking the status again.',response.ok?502:response.status);}
 if(response.status===401&&path==='/auth/login'&&typeof data?.detail!=='string')throw accessExpired();
 if(!response.ok){
  const fallback=response.status===401?'Your session expired. Sign in again to continue with your saved work.':response.status===403?'This action was not authorized. Sign in again before retrying.':response.status===409?'This information changed while you were working. Check the latest saved version before retrying.':response.status>=500?'The app could not complete the request. Your saved inputs remain available; try again shortly.':'The request could not finish. Check your inputs and try again.';
  throw new ApiError(typeof data?.detail==='string'?data.detail:fallback,response.status);
 }
 return data;
}

type Call=(path:string,method?:string,body?:any)=>Promise<any>;
const sleep=(ms:number)=>new Promise<void>(resolve=>setTimeout(resolve,ms));
export async function pollTask(id:string,call:Call,wait=sleep,limit=600,onUpdate?:(value:any)=>void){
 let connectionFailures=0;let lastStatus:any={id,status:'running'};
 for(let i=0;i<limit;i++){
  await wait(connectionFailures?Math.min(1000*2**connectionFailures,10000):1200);
  let status:any;
  try{status=await call('/tasks/'+encodeURIComponent(id));connectionFailures=0;}
  catch(error){
   if(error instanceof ApiError&&error.transient){onUpdate?.({...lastStatus,connection_lost:true});if(++connectionFailures<=5)continue;}
   if(error instanceof ApiError&&error.transient)throw new ApiError('The connection was lost while checking this task. It may still be running. Your inputs are saved; check its status before starting another request.');
   throw error;
  }
  lastStatus={...status,checked_at:new Date().toISOString(),connection_lost:false};onUpdate?.(lastStatus);
  if(status?.status==='completed'){
   if(status.result==null)throw new ApiError('This task finished without a readable result. Check its status before starting another request.',502);
   return status.result;
  }
  if(['failed','interrupted'].includes(status?.status))throw new ApiError(status.error||'This operation was interrupted. Your saved inputs remain available for retry.',422);
  if(!['queued','running'].includes(status?.status))throw new ApiError('The task status could not be read. Check its status before starting another request.',502);
 }
 onUpdate?.({...lastStatus,status:'unknown',connection_lost:true});
 throw new ApiError('This task is taking longer than expected. It may still be running. Check its status before starting another request.');
}

const pendingKey=(account:string,job:string)=>'next-step-comparison:'+account+':'+job;
export function pendingComparison(account:string,job:string,storage:Storage=localStorage){
 try{const record=JSON.parse(storage.getItem(pendingKey(account,job))||'null');return record&&typeof record.token==='string'?record:null;}catch{return null;}
}
export async function comparisonTask(account:string,body:any,call:Call,storage:Storage=localStorage,wait=sleep){
 const key=pendingKey(account,body.job_id);
 const pending=pendingComparison(account,body.job_id,storage)||{token:crypto.randomUUID(),mode:body.mode};
 // Record the token before POST: even a lost start response can be recovered.
 storage.setItem(key,JSON.stringify(pending));
 if(!pending.id){
  try{const initial=await call('/analyses','POST',{...body,mode:pending.mode,request_token:pending.token});if(typeof initial?.task_id!=='string'||!initial.task_id)throw new ApiError('The comparison start could not be confirmed. Check its status before starting another request.',502);pending.id=initial.task_id;storage.setItem(key,JSON.stringify(pending));}
  catch(error){if(error instanceof ApiError&&error.status>=400&&error.status<500&&error.status!==429)storage.removeItem(key);throw error;}
 }
 try{const result=await pollTask(pending.id,call,wait,1200);storage.removeItem(key);return result;}
 catch(error){if(error instanceof ApiError&&[401,403,404,422].includes(error.status))storage.removeItem(key);throw error;}
}

const projectKey=(account:string,snapshot:string)=>'next-step-project-task:'+account+':'+snapshot;
export async function projectTask(account:string,snapshot:string,body:any,call:Call,storage:Storage=localStorage,wait=sleep){
 const key=projectKey(account,snapshot);
 let pending:any=null;try{pending=JSON.parse(storage.getItem(key)||'null');}catch{}
 if(!pending||typeof pending.token!=='string')pending={token:body.request_token||crypto.randomUUID(),mode:body.mode};
 storage.setItem(key,JSON.stringify(pending));
 if(!pending.id){
  try{
   const initial=await call('/project-snapshots/'+encodeURIComponent(snapshot)+'/analyze','POST',{mode:pending.mode,request_token:pending.token});
   if(typeof initial?.task_id!=='string'||!initial.task_id)throw new ApiError('The project analysis start could not be confirmed. Check its status before starting another request.',502);
   pending.id=initial.task_id;storage.setItem(key,JSON.stringify(pending));
  }catch(error){if(error instanceof ApiError&&error.status>=400&&error.status<500&&error.status!==429)storage.removeItem(key);throw error;}
 }
 try{const result=await pollTask(pending.id,call,wait);storage.removeItem(key);return result;}
 catch(error){if(error instanceof ApiError&&[401,403,404,422].includes(error.status))storage.removeItem(key);throw error;}
}

export function clearProjectTask(account:string,snapshot:string,storage:Storage=localStorage){storage.removeItem(projectKey(account,snapshot));}

export function pendingDocumentComparison(account:string,storage:Storage=localStorage){
 return pendingComparison(account,'__document__',storage);
}

export async function documentComparisonTask(account:string,file:File|undefined,mode:string,call:Call,onUpdate?:(value:any)=>void,storage:Storage=localStorage,wait=sleep,postingOnly=false){
 const scope=postingOnly?'__posting__':'__document__',endpoint=postingOnly?'/jobs/from-document':'/analyses/from-document';
 const key=pendingKey(account,scope);
 let pending=pendingComparison(account,scope,storage);
 const recovering=!!pending;
 if(!pending){
  if(!file)throw new ApiError('Choose a job document first.',400);
  pending={token:crypto.randomUUID(),mode,filename:file.name,size:file.size,lastModified:file.lastModified};
  storage.setItem(key,JSON.stringify(pending));
 }
 if(!pending.id&&recovering){
  try{const initial=await call(endpoint+'/status?request_token='+encodeURIComponent(pending.token));if(typeof initial?.task_id!=='string'||!initial.task_id)throw new ApiError('The upload status could not be read. Check its status before starting another request.',502);pending.id=initial.task_id;storage.setItem(key,JSON.stringify(pending));}
  catch(error){if(!(error instanceof ApiError&&error.status===404))throw error;}
 }
 if(!pending.id){
  if(!file)throw new ApiError('Select the original document to recover this upload. Its comparison start has not yet been confirmed.',409);
  if(file.name!==pending.filename||file.size!==pending.size||file.lastModified!==pending.lastModified)throw new ApiError('Select the original document while its upload status is unresolved.',409);
  const form=new FormData();form.append('file',file);form.append('mode',pending.mode);form.append('request_token',pending.token);
  try{
   const initial=await call(endpoint,'POST',form);
   if(typeof initial?.task_id!=='string'||!initial.task_id)throw new ApiError('The comparison start could not be confirmed. Check its status before starting another request.',502);
   pending.id=initial.task_id;storage.setItem(key,JSON.stringify(pending));
  }catch(error){if(error instanceof ApiError&&error.status>=400&&error.status<500&&error.status!==429)storage.removeItem(key);throw error;}
 }
 try{const result=await pollTask(pending.id,call,wait,1200,onUpdate);storage.removeItem(key);return result;}
 catch(error){if(error instanceof ApiError&&[401,403,404,422].includes(error.status))storage.removeItem(key);throw error;}
}

export function pendingPostingImport(account:string,storage:Storage=localStorage){return pendingComparison(account,'__posting__',storage);}
export function postingImportTask(account:string,file:File|undefined,mode:string,call:Call,onUpdate?:(value:any)=>void,storage:Storage=localStorage,wait=sleep){return documentComparisonTask(account,file,mode,call,onUpdate,storage,wait,true);}
