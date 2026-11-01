type RecordValue={id:string;data:any};
export function finishedResume(application:RecordValue|undefined,resumes:RecordValue[]){
 const id=application?.data.workflow?.resume_id;
 return resumes.find(r=>r.id===id&&r.data.origin==='uploaded'&&r.data.job_id===application?.data.job_id&&application?.data.resume_ids?.includes(r.id));
}
export function finishedResumeWorkflow(application:RecordValue,resumes:RecordValue[],id:string,continueToLetter:boolean){
 if(!finishedResume({...application,data:{...application.data,workflow:{resume_id:id}}},resumes))throw Error('Choose an uploaded resume attached to this application.');
 const old=application.data.workflow||{},same=old.resume_id===id;
 return {step:continueToLetter?'cover':'resume',resume_id:id,cover_letter_id:same?old.cover_letter_id||'':'',cover_skipped:same?!!old.cover_skipped:false};
}
