export type EditChoice={action:string;text:string};
export function editChosen(choice:EditChoice|undefined,candidate:string,proposed:string){
 return !!choice&&choice.action!=='reject'&&(choice.action==='accept'?proposed:choice.text)===candidate;
}
export function emptyPreparation(value:any){
 return !value?.current&&!!value?.data?.workspace_request&&!value.data.workspace_request.experience_ids?.length&&!Object.values(value.data.workspace_request.content||{}).some((v:any)=>v.length);
}
export function canAutoRender(current:any,form:any){
 return !!current||!!form?.experience_ids?.length;
}
export function wordingChanges(form:any,decisions:Record<string,EditChoice>,suggestions:any[],catalog:any[]){
 const overrides={...form.overrides},content={...form.content};
 for(const [index,decision] of Object.entries(decisions)){
  const suggestion=suggestions[Number(index)];if(!suggestion)continue;
  const normalize=(v:string)=>v.toLowerCase().replace(/^relevant class: /,'').replace(/\s+/g,' ').trim();
  for(const row of catalog){
   if(row.id!==suggestion.record_id)continue;
   const matches=row.items.map((item:any,i:number)=>({item,i})).filter(({item}:any)=>item.original.includes(suggestion.original)||normalize(suggestion.original).includes(normalize(item.original)));
   matches.forEach(({item,i}:any,n:number)=>{
    const text=decision.action==='accept'?suggestion.proposed:decision.text;
    if(decision.action==='reject')overrides[item.item_id]=item.original;
    else if(item.original.includes(suggestion.original))overrides[item.item_id]=item.original.replace(suggestion.original,text);
    else if(n===0)overrides[item.item_id]=text;
    else content[row.id]=(content[row.id]||[]).filter((j:number)=>j!==i);
   });
  }
 }
 return {overrides,content,decisions:Object.entries(decisions).map(([index,value])=>({index:Number(index),...value}))};
}

export function resumeNeedsClarification(session:any){
 const questions=session?.data?.asked_questions||session?.data?.questions||[];
 return questions.some((q:any)=>!!q.text?.trim()&&!['reviewed','answered','skipped','superseded'].includes(q.status));
}
