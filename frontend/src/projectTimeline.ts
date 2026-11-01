// Match backend project_structure.parents/timeline_enabled. Course links are
// grouped by their education owner, not counted as separate timeline stages.
export const projectParents=(data:any):string[]=>[...new Set<string>([
 ...(data.linked_employment_ids||[]),...(data.linked_education_ids||[]),
 ...(data.linked_courses||[]).map((value:any)=>value.education_id),
])];
export const hasProjectTimeline=(data:any)=>data.category==='project'&&projectParents(data).length>=2;
export function projectDisplayDates(data:any,parentId:string){
 const whole=[data.start_date,data.end_date].filter(Boolean).join(' – ')||data.dates||'';
 if(!hasProjectTimeline(data))return whole;
 const stage=data.project_stages?.find((value:any)=>value.parent_id===parentId);
 return [stage?.start_date,stage?.end_date].filter(Boolean).join(' – ')||(whole?'Whole project dates: '+whole:'');
}
