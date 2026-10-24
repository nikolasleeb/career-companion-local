// Explicit arrays (including empty arrays) take precedence over legacy single subjects.
export function subjects(data:any,field:'major'|'minor'):string[]{
 const values=Array.isArray(data?.[field+'s'])?data[field+'s']:[data?.[field]||''];
 const seen=new Set<string>();return values.map((v:string)=>v.trim()).filter((v:string)=>{const key=v.toLocaleLowerCase();if(!v||seen.has(key))return false;seen.add(key);return true;});
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
