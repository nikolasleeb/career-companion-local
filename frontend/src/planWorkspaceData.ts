export const planningDraftKey=(account:string,chat='new')=>'career-plan-input:'+account+(chat==='new'?'':':'+chat);
export function readPlanningDraft(account:string,chat='new',fallback:any={},storage:Storage=sessionStorage){
 let stored:any;try{stored=JSON.parse(storage.getItem(planningDraftKey(account,chat))||'null');}catch{}
 const value=stored&&typeof stored==='object'?stored:fallback||{},purposes=['explore','internships','graduation','career_change','certification','custom'];
 return {purpose:purposes.includes(value.purpose)?value.purpose:'explore',objective:typeof value.objective==='string'?value.objective:'',target:typeof value.target==='string'?value.target:'',time_available:typeof value.time_available==='string'?value.time_available:'',budget:typeof value.budget==='string'?value.budget:'',goal_ids:Array.isArray(value.goal_ids)?[...new Set(value.goal_ids.filter((v:any)=>typeof v==='string'))].slice(0,5):[]};
}
