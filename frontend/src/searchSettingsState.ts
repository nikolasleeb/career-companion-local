export function selectedSourceCount(query:any,caps:any){return (query.sources||[]).filter((id:string)=>!['adzuna','usajobs'].includes(id)||!!caps[id]).length;}
export function selectedEmployerCount(query:any,rows:any[]=[]){
 const mode=query.employer_selection_mode||(query.employer_boards!=null?'custom':'all');
 const selected=rows.filter(b=>{
  if(b.coverage_status==='external')return false;
  if(mode==='all')return true;
  if(mode==='industries')return (b.industries||[]).some((id:string)=>(query.employer_industries||[]).includes(id));
  return (query.employer_boards||[]).includes(b.key);
 });
 return new Set(selected.map(b=>b.employer_id||b.key)).size;
}
