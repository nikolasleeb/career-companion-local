export type OverviewScope={kind:'project'|'stages'|'unassigned';stage_ids:string[]};
export type OverviewStatement={id:string;text:string;field?:string;scope?:OverviewScope};
export function overviewLines(text:string){
 const result:string[]=[];let active=false;
 for(const line of text.split(/\r?\n/)){
  const explicit=/^\s*[•*-](?:[ \t]+|$)/.test(line),content=(explicit?line.replace(/^\s*[•*-](?:[ \t]+|$)/,''):line).trim().replace(/^[ •-]+|[ •-]+$/g,'');
  if(!content){active=false;continue;}
  if(active&&!explicit&&/^(?: {2}|\t)/.test(line))result[result.length-1]+=' '+content;
  else{result.push(content);active=explicit;}
 }
 return result;
}
/** Reconcile against the editing-session baseline, never against a half-typed split. */
export function reconcileOverview(before:OverviewStatement[],text:string,defaultScope:OverviewScope,field='description',timelineEnabled=true){
 const lines=overviewLines(text),used=new Set<string>();
 const rows:(OverviewStatement|null)[]=lines.map(value=>{const old=before.find(v=>v.text===value&&!used.has(v.id));if(!old)return null;used.add(old.id);return {...old};});
 const remaining=before.filter(v=>!used.has(v.id)),missing=rows.map((v,i)=>v===null?i:-1).filter(i=>i>=0);
 if(remaining.length===1&&missing.length===1){const i=missing[0];rows[i]={...remaining[0],text:lines[i],...(!timelineEnabled&&remaining[0].scope?.kind==='unassigned'?{scope:defaultScope}:{})};}
 else for(const i of missing)rows[i]={id:crypto.randomUUID(),text:lines[i],field,scope:remaining.length&&timelineEnabled?{kind:'unassigned',stage_ids:[]}:defaultScope};
 return rows as OverviewStatement[];
}
