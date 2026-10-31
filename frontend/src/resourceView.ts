export function nextUnfinishedMilestone(actions:any[],checklist:any){
 return actions.find(action=>(checklist.step_ids[action.id]||[]).some((id:string)=>!checklist.steps[id]?.completed));
}
export function occupationFilterLabels(draft:any,options:any){
 const labels:string[]=[];
 if(draft.mode==='studies'&&draft.major)labels.push('Studies: '+draft.major);
 if(draft.courses)labels.push('Additional subjects: '+draft.courses);
 for(const id of draft.profile_course_ids||[])labels.push('Course: '+(options?.profile?.course_options?.find((v:any)=>v.id===id)?.title||id));
 for(const id of draft.profile_skill_ids||[])labels.push('Skill: '+(options?.profile?.skill_options?.find((v:any)=>v.id===id)?.title||id));
 for(const id of draft.industries||[])labels.push('Industry: '+(options?.industries?.find((v:any)=>v.naics===id)?.title||id));
 labels.push('Pay area: '+(options?.salary_areas?.find((v:any)=>v.id===draft.salary_area)?.title||draft.salary_area));
 if(draft.preparation!=='all')labels.push('College / graduate level');
 return labels;
}
