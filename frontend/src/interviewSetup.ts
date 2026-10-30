import {clearInterview,interviewAction,pendingInterview,recoverInterview,readInterviewDraft,saveInterviewDraft} from './interviewRecovery';
export type SetupLaunch={id:string;kind:string;fingerprint:string};
type Options={account:string;setup:any;focus:string;mode:string;call:any;onLaunch:(launch:SetupLaunch|null)=>void};
export const setupFingerprint=(setup:any,focus:string,mode:string)=>JSON.stringify({setup,focus,mode});
export async function generateSetupQuestion({account,setup,focus,mode,call,onLaunch}:Options,storage:Storage=sessionStorage,requests:Storage=localStorage){
 const fingerprint=setupFingerprint(setup,focus,mode),old=readInterviewDraft(account,'setup-launch',null,storage) as SetupLaunch|null;
 const remember=(value:SetupLaunch|null)=>{saveInterviewDraft(account,'setup-launch',value,storage);onLaunch(value);};
 let session:any;
 if(old?.fingerprint===fingerprint){
  let result:any;
  try{result=await call('/interview-practice/sessions/'+old.id);}catch(error){if((error as any).status===404)remember(null);throw error;}
  session=result.session;
  if(result.questions.length&&!pendingInterview(account,old.id,requests))return result;
 }else{
  session=await call('/interview-practice/sessions','POST',setup);
  remember({id:session.id,kind:setup.kind,fingerprint});
 }
 const pending=pendingInterview(account,session.id,requests);
 if(pending){
  // Resolve a prior submission before allowing another paid request. A failed
  // request is never retried by recovery or by opening/reloading setup.
  let taskId=pending.id;
  if(!taskId){try{taskId=(await call('/interview-practice/actions/'+pending.token)).task_id;}catch(error){if((error as any).status===404){clearInterview(account,session.id,requests);throw Error('The previous generation was not submitted. Choose Generate question again to start it explicitly.');}throw error;}}
  const task=await call('/tasks/'+taskId);
  if(['failed','cancelled'].includes(task.status)){clearInterview(account,session.id,requests);throw Error('The previous generation did not finish. Your session is saved. Choose Generate question again to retry explicitly, or open the saved session.');}
  return await recoverInterview(account,session.id,call,requests);
 }
 const result=await interviewAction(account,session.id,{operation:'question',expected_updated_at:session.updated_at,focus,mode},call,requests);
 return result;
}
