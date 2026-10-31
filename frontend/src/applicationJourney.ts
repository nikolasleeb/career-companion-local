export type DocumentStage='posting'|'resume'|'letter'|'finish';
export const documentStages:DocumentStage[]=['posting','resume','letter','finish'];
export function stageFor(view:string,stage?:string):DocumentStage{return documentStages.includes(stage as DocumentStage)?stage as DocumentStage:view==='cover'?'letter':view==='agent'?'finish':'posting';}
export function selectedResume(workflow:any,remembered:string,submitted:string,resumes:any[]){return workflow?.resume_id||remembered||submitted||resumes[0]?.id||'';}
export function nextApplicationAction(data:any){
 if(data.archived)return {label:'Review archived application',stage:'activity'};
 if(data.status!=='preparing')return {label:data.status==='interviewing'?'Update interview activity':'Update application activity',stage:'activity'};
 const flow=data.workflow||{};
 if(!data.job_id)return {label:'Review application details',stage:'activity'};
 if(!flow.resume_id)return {label:'Prepare resume',stage:'posting'};
 if(!flow.cover_letter_id&&!flow.cover_skipped)return {label:'Prepare or skip letter',stage:'letter'};
 return {label:'Review finished documents',stage:'finish'};
}
