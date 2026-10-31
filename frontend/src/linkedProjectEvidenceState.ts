export function linkedProjectUses(catalog:any[],form:any,projectId:string){
 return catalog.filter(row=>row.category==='employment'&&form?.experience_ids.includes(row.id)).flatMap(row=>row.items.filter((item:any,n:number)=>form.content[row.id]?.includes(n)&&item.project_source?.project_id===projectId).map((item:any)=>({title:row.title,item})));
}

