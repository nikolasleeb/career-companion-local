// Preserve staged edits when a file operation updates the saved application.
const equal=(a:any,b:any)=>JSON.stringify(a)===JSON.stringify(b);
const itemKey=(value:any)=>typeof value==='string'?value:value.kind+':'+value.record_id;
function mergeLinks(base:any[]=[],draft:any[]=[],remote:any[]=[]){
 const baseKeys=new Set(base.map(itemKey)),draftKeys=new Set(draft.map(itemKey));
 const removed=new Set([...baseKeys].filter(id=>!draftKeys.has(id)));
 const result=remote.filter(value=>!removed.has(itemKey(value))),seen=new Set(result.map(itemKey));
 for(const value of draft)if(!baseKeys.has(itemKey(value))&&!seen.has(itemKey(value))){result.push(value);seen.add(itemKey(value));}
 return result;
}
export function mergeApplicationDraft(base:any,draft:any,remote:any){
 const result={...remote};
 for(const key of Object.keys(draft))if(!equal(base[key],draft[key]))result[key]=key==='resume_ids'||key==='attachments'?mergeLinks(base[key],draft[key],remote[key]):draft[key];
 return result;
}
export function applicationDirty(base:any,draft:any){return !equal(base,draft);}
export function applicationSavePayload(base:any,draft:any,eventDate:string){
 const result=structuredClone(draft);
 if(draft.status!==(base.status||'preparing'))result.history=[...(draft.history||[]),{status:draft.status,date:eventDate,note:''}];
 return result;
}
export function applicationDocumentCounts(data:any,documents:any[]=[]){
 const attachments=data.attachments||[];
 const fileType=(id:string)=>documents.find(d=>d.id===id)?.data.category;
 return {resumes:(data.resume_ids||[]).length,letters:attachments.filter((a:any)=>a.kind==='cover_letter'||(a.kind==='document'&&fileType(a.record_id)==='cover_letter')).length,files:attachments.filter((a:any)=>a.kind==='document'&&!['resume','cover_letter'].includes(fileType(a.record_id))).length};
}
export function relevantResumes(resumes:any[],data:any,analyses:any[]=[]){
 return resumes.filter(r=>(data.resume_ids||[]).includes(r.id)||(!!data.job_id&&(r.data.job_id||analyses.find(a=>a.id===r.data.analysis_id)?.data.job_id)===data.job_id));
}
export function applicationConflicts(base:any,draft:any,remote:any){
 const serverLinks=new Set(['resume_ids','attachments','workflow']);
 return Object.keys(draft).filter(key=>!serverLinks.has(key)&&!equal(base[key],draft[key])&&!equal(base[key],remote[key])&&!equal(draft[key],remote[key]));
}
