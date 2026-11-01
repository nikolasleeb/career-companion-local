import React,{useState} from 'react';
import {ApplicationDocuments} from './ApplicationDocuments';
import {finishedResume,finishedResumeWorkflow} from './finishedResumeState';
import './finishedResume.css';
type RecordValue={id:string;data:any;created_at:string;updated_at:string};
type Call=(path:string,method?:string,body?:any)=>Promise<any>;
export function FinishedResume({application,documents,resumes,analyses,call,refresh,onContinue,onPrepare,disabled,onBusy}: {
 application?:RecordValue;documents:RecordValue[];resumes:RecordValue[];analyses:RecordValue[];call:Call;refresh:()=>Promise<void>;onContinue:()=>void;onPrepare:()=>void;disabled:boolean;onBusy:(busy:boolean)=>void;
}){
 const [filesBusy,setFilesBusy]=useState(false),[editing,setEditing]=useState(false),[saving,setSaving]=useState(false),[error,setError]=useState(''),[retry,setRetry]=useState<{resume:string;continue:boolean}|null>(null);
 const selected=finishedResume(application,resumes),blocked=disabled||filesBusy||editing||saving;
 function uploadBusy(value:boolean){setFilesBusy(value);onBusy(value);}
 async function select(resume:string,continueToLetter:boolean){
  if(!application||blocked)return;
  const action={resume,continue:continueToLetter};setRetry(action);setSaving(true);onBusy(true);setError('');
  try{
   const latest=await call('/applications/'+application.id);
   const workflow=finishedResumeWorkflow(latest,resumes,resume,continueToLetter);
   await call('/applications/'+application.id+'/workflow','PUT',{expected_updated_at:latest.updated_at,workflow});
   await refresh();setRetry(null);if(continueToLetter)onContinue();
  }catch(e){setError((e as Error).message);}finally{setSaving(false);onBusy(false);}
 }
 return <>
 <p>Upload your finished resume and continue to the cover-letter step. No AI request.</p>
 {application?<ApplicationDocuments key={application.id} resumeOnly uploadedOnly uploadLabel="Upload my resume" application={application} documents={documents} resumes={resumes} analyses={analyses} call={call} onChange={refresh} onBusy={uploadBusy} onFileEdit={setEditing} disabled={disabled||saving} onSelectResume={r=>void select(r.id,false)}/>:<button type="button" className="button secondary" disabled={disabled} onClick={onPrepare}>Upload my resume</button>}
 {disabled&&<p className="small muted" role="status">Wait for the resume action to finish or its saved status to load. Use Stop to cancel a running action.</p>}
 {error&&<p className="details-inline-error" role="alert">{error} {retry&&<button type="button" className="text-button" disabled={blocked} onClick={()=>void select(retry.resume,retry.continue)}>Retry</button>}</p>}
 <div className="finished-resume-actions"><button type="button" className="button primary" disabled={blocked||!selected} onClick={()=>selected&&void select(selected.id,true)}>{saving?'Saving…':'Continue to cover letter →'}</button></div>
 </>;
}
