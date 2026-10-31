export async function refreshExplicit(item:any,call:any){if(item.context_ref.kind==='readiness')return call('/career-readiness/sessions/'+item.session_id+'/handoff/'+item.report_id);return item.context_ref.kind==='occupation'?call('/career-explorer/occupations/'+encodeURIComponent(item.context_ref.id)+(item.context_ref.salary_area?'?salary_area='+encodeURIComponent(item.context_ref.salary_area):'')):call('/applications/'+encodeURIComponent(item.context_ref.id)+'/offer/preview');}

export async function acceptHandoff(detail:any,current:string,confirm:()=>Promise<boolean>=async()=>false){return !current.trim()||current===detail.prompt||confirm();}

export function contextFromSources(sources:any[]=[]){return sources.map(s=>({...s.snapshot,context_ref:{kind:s.kind==='explicit_readiness'?'readiness':s.kind==='explicit_offer'?'offer':'occupation',id:s.record_id,revision:s.revision,...(s.snapshot?.salary_area?{salary_area:s.snapshot.salary_area}:{})}}));}

export function readContextDraft(account:string,scope:string){try{return JSON.parse(sessionStorage.getItem('career-explicit-draft:'+account+':'+scope)||'[]');}catch{return [];}}
export function saveContextDraft(account:string,scope:string,items:any[]){try{sessionStorage.setItem('career-explicit-draft:'+account+':'+scope,JSON.stringify(items));}catch{}}
