// Assistant links are one-time navigation requests, not persistent page routes.
export function assistantRunId(hash:string){return hash.match(/^#assistant-run=([a-f0-9]{32})$/)?.[1]||'';}
export function clearAssistantRoute(location:any,history:any,expected?:string){
 if(!assistantRunId(location.hash)||(expected!==undefined&&location.hash!==expected))return false;
 history.replaceState(history.state,'',location.pathname+location.search);
 return true;
}
export async function openAssistantRoute({location,history,load,applications,open,current=()=>true}:{location:any;history:any;load:(id:string)=>Promise<any>;applications:any[];open:(record:any)=>void;current?:()=>boolean}){
 const hash=location.hash,id=assistantRunId(hash);if(!id)return false;
 try{
  const run=await load(id);
  // A sidebar choice or a newer link takes precedence over this pending lookup.
  if(!current()||location.hash!==hash)return false;
  const record=applications.find(a=>a.id===run.application_id);if(!record)return false;
  clearAssistantRoute(location,history,hash);open(record);return true;
 }catch(error){
  if(!current()||location.hash!==hash)return false;
  clearAssistantRoute(location,history,hash);throw error;
 }
}
