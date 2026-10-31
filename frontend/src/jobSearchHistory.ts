type Search={id:string;created_at?:string;data:Record<string,any>};
const key=(accountId:string)=>'career-selected-job-search:'+accountId;
export function readSelectedSearch(accountId:string,storage?:Pick<Storage,'getItem'>){try{return (storage??localStorage).getItem(key(accountId))||'';}catch{return '';}}
export function rememberSelectedSearch(accountId:string,id:string,storage?:Pick<Storage,'setItem'>){try{(storage??localStorage).setItem(key(accountId),id);}catch{/* Browser storage is optional; saved searches remain on the server. */}}
export function orderedSearches<T extends Search>(rows:T[]):T[]{return rows.filter(r=>r.data.discovery_kind!=='for_you').slice().sort((a,b)=>(Date.parse(b.created_at||'')||0)-(Date.parse(a.created_at||'')||0));}
export function chooseSearch<T extends Search>(rows:T[],id:string):T|undefined{return rows.find(r=>r.id===id)||rows[0];}
export function searchHistoryLabel(row:Search){
 const q=row.data.query||{},roles=(Array.isArray(q.interests)?q.interests:[]).filter((v:unknown):v is string=>typeof v==='string'&&!!v.trim());
 const short=(text:string,max:number)=>text.length>max?text.slice(0,max-1)+'…':text;
 const subject=roles.length?roles.slice(0,2).join(', ')+(roles.length>2?' +'+(roles.length-2):''):q.title||row.data.ai_brief?.summary||'All roles';
 const date=Date.parse(row.created_at||'');
 const places=(Array.isArray(q.locations)&&q.locations.length?q.locations:[q.location]).filter((v:unknown):v is string=>typeof v==='string'&&!!v.trim());
 const location=places.length?short(places.slice(0,2).join('; '),50)+(places.length>2?' +'+(places.length-2):''):'Location not recorded';
 return [row.data.ai_brief||row.data.ai_prompt||row.data.discovery_kind==='ai'?'AI search':'Search',Number.isNaN(date)?'Date unavailable':new Date(date).toLocaleString(),short(String(subject),70),location].join(' · ');
}
