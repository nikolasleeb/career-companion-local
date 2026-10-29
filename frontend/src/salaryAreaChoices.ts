export const areaText=(v:string)=>v.normalize('NFKC').toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu,' ').trim().replace(/\s+/g,' ');
export function salaryAreaChoices(areas:any[],query:string){
 const q=areaText(query),states=new Set(areas.filter(a=>a.type==='state'&&[areaText(a.title),areaText(a.state)].includes(q)).map(a=>a.state));
 const alias=(a:any)=>q&&(a.aliases||[]).some((s:string)=>areaText(s)===q);
 return areas.filter(a=>!q||alias(a)||(states.size?(a.state_codes||[]).some((s:string)=>states.has(s)):(a.search_text||areaText(a.title)).includes(q))).sort((a,b)=>Number(areaText(a.title)!==q)-Number(areaText(b.title)!==q)||Number(!alias(a))-Number(!alias(b))||({national:0,state:1,metro:2,nonmetro:3}[a.type as 'national']??4)-({national:0,state:1,metro:2,nonmetro:3}[b.type as 'national']??4)||a.title.localeCompare(b.title));
}
