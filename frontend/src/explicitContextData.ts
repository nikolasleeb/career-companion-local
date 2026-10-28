export async function refreshExplicit(item:any,call:any){return item.context_ref.kind==='occupation'?call('/career-explorer/occupations/'+encodeURIComponent(item.context_ref.id)):call('/applications/'+encodeURIComponent(item.context_ref.id)+'/offer/preview');}

export function acceptHandoff(detail:any,current:string){return !current.trim()||current===detail.prompt||window.confirm('Replace the current unsent message with this career question? Choose Cancel to keep your draft.');}

export function contextFromSources(sources:any[]=[]){return sources.map(s=>({...s.snapshot,context_ref:{kind:s.kind==='explicit_offer'?'offer':'occupation',id:s.record_id,revision:s.revision}}));}

export function readContextDraft(account:string,scope:string){try{return JSON.parse(sessionStorage.getItem('career-explicit-draft:'+account+':'+scope)||'[]');}catch{return [];}}
export function saveContextDraft(account:string,scope:string,items:any[]){try{sessionStorage.setItem('career-explicit-draft:'+account+':'+scope,JSON.stringify(items));}catch{}}
