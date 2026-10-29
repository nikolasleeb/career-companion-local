// Explicit arrays (including empty arrays) take precedence over legacy single subjects.
export function subjects(data:any,field:'major'|'minor'):string[]{
 const values=Array.isArray(data?.[field+'s'])?data[field+'s']:[data?.[field]||''];
 const seen=new Set<string>();return values.map((v:string)=>v.trim()).filter((v:string)=>{const key=v.toLocaleLowerCase();if(!v||seen.has(key))return false;seen.add(key);return true;});
}
// Keep input drafts verbatim: trailing spaces and new blank rows are editable.
// Only subjects()/educationPayload() trim and deduplicate the saved values.
export function subjectDrafts(data:any,field:'major'|'minor'):string[]{
 return Array.isArray(data?.[field+'s'])?[...data[field+'s']]:data?.[field]?[data[field]]:[];
}
export function educationPayload(data:any){const majors=subjects(data,'major'),minors=subjects(data,'minor');return {majors,minors,major:majors[0]||'',minor:minors[0]||''};}
export function educationTitle(data:any){const majors=subjects(data,'major').join(' & ');return data.category==='education'&&data.degree?[data.degree,majors?'in '+majors:''].filter(Boolean).join(' '):data.title;}
export function replacementCourses(courses:any[],selected:string[]){
 const seen=new Set<string>();const titles=courses.filter(c=>selected.includes(c.id)).map(c=>String(c.title||'').trim()).filter(title=>{const key=title.toLocaleLowerCase();if(!title||seen.has(key))return false;seen.add(key);return true;});
 if(!titles.length)return {error:'Select at least one course before replacing relevant classes.'};
 const value=titles.join('; ');
 return value.length>4000?{error:'The selection exceeds the 4,000-character class limit. Select fewer courses.'}:{value};
}
const roleWarning='Role and employer were not separately identified; review this heading.';
export function activeImportWarnings(item:any):string[]{
 const normal=(value:any)=>String(value||'').trim().replace(/\s+/g,' ').toLocaleLowerCase();
 const role=normal(item.data.title),employer=normal(item.data.organization);
 return (item.warnings||[]).filter((warning:string)=>!(warning===roleWarning&&item.data.category==='employment'&&role&&employer&&role!==employer));
}

// Editing a visible import field reconciles its legacy compatibility values as
// well. Only direct user edits call this; preparing a review chooses no winner.
export function editImportFields(data:Record<string,any>,patch:Record<string,any>){
 const next={...data,...patch};const touched=new Set(Object.keys(patch));
 for(const field of ['major','minor'] as const){
  if(field+'s' in patch){next[field]=subjects(next,field)[0]||'';touched.add(field);}
  else if(field in patch){next[field+'s']=patch[field]?[patch[field]]:[];touched.add(field+'s');}
 }
 if(data.category==='education'&&['degree','major','majors'].some(k=>k in patch)){
  next.title=educationTitle(next)||next.organization||'Education';touched.add('title');
 }
 if(['start_date','end_date','expected_graduation'].some(k=>k in patch)){
  next.dates=[[next.start_date,next.end_date].filter(Boolean).join(' – '),next.category==='education'&&next.expected_graduation?'Expected graduation '+next.expected_graduation:''].filter(Boolean).join('; ');touched.add('dates');
 }
 if('project_urls' in patch){next.project_url=patch.project_urls.find((v:string)=>v.trim())||'';touched.add('project_url');}
 if('project_url' in patch){next.project_urls=patch.project_url?[patch.project_url]:[];touched.add('project_urls');}
 return {data:next,touched:[...touched]};
}
