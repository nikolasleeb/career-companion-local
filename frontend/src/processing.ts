import type {TaskStatus} from './taskProgress';
export type ProcessingEntry=TaskStatus&{id:string;request?:boolean;settled?:boolean;serial:number;label?:string};
const active=(s:string)=>['queued','running','cancelling','unknown'].includes(s);
export function actionLabel(path:string){
 if(/^\/cover-workspaces\/[^/]+\/(?:message|answers\/review)$/.test(path))return 'Reviewing cover-letter answers or changes';
 if(/^\/cover-workspaces\/[^/]+\/questions$/.test(path))return 'Preparing cover-letter questions';
 if(/^\/cover-workspaces\/[^/]+\/generate$/.test(path))return 'Building cover letter';
 if(/^\/cover-workspaces\/[^/]+\/context\/review$/.test(path))return 'Applying reviewed cover-letter details';
 if(/^\/resume-conversations\/[^/]+\/answers\/review$/.test(path))return 'Reviewing resume answers';
 if(/\/render$/.test(path))return 'Updating the PDF preview locally';
 if(/\/answers$|\/progress$/.test(path))return 'Saving responses locally';
 if(path==='/analyses/from-document')return 'Reading job posting';
 if(path==='/analyses')return 'Comparing your Profile to the posting';
 if(/\/analyze$/.test(path))return 'Analyzing project materials';
 if(/\/build$/.test(path))return 'Building the resume draft';
 if(/\/messages$/.test(path))return 'Reviewing resume changes';
 if(path==='/preparation')return 'Preparing interview practice';
 if(path==='/interviews')return 'Reviewing your interview answer';
 if(path==='/jobs/search')return 'Searching job sources';
 return 'Processing your request';
}
export function processingGroups(entries:ProcessingEntry[]){
 return {confirmed:entries.filter(v=>!v.connection_lost&&v.status!=='unknown'),uncertain:entries.filter(v=>v.connection_lost||v.status==='unknown')};
}
export class ProcessingStore{
 owner='';epoch=0;serial=0;records=new Map<string,ProcessingEntry>();listeners=new Set<()=>void>();failure='';
 subscribe=(fn:()=>void)=>{this.listeners.add(fn);return()=>{this.listeners.delete(fn);};};
 emit(){for(const fn of this.listeners)fn();}
 snapshot(){return [...this.records.values()];}
 setOwner(owner:string){if(owner===this.owner)return;this.owner=owner;this.epoch++;this.records.clear();this.failure='';this.emit();}
 clearFailure(){this.failure='';this.emit();}
 update(value:any){
  if(!value?.id)return;
  const previous=this.records.get(value.id);
  if(!active(value.status)){this.records.delete(value.id);if(['failed','interrupted'].includes(value.status)&&previous&&value.error)this.failure=value.error;this.emit();return;}
  this.records.set(value.id,{...previous,...value,serial:++this.serial,checked_at:new Date().toISOString(),connection_lost:false});this.emit();
 }
 reconcile(values:any[],before:number){
  const ids=new Set(values.map(v=>v.id));
  for(const [id,entry] of this.records)if(entry.serial<=before&&(!entry.request||entry.settled)&&!ids.has(id))this.records.delete(id);
  for(const value of values)this.records.set(value.id,{...this.records.get(value.id),...value,serial:++this.serial,checked_at:new Date().toISOString(),connection_lost:false});
  this.emit();
 }
 disconnected(){for(const [id,value] of this.records)if(!value.request||value.settled)this.records.set(id,{...value,connection_lost:true,status:'unknown',checked_at:value.checked_at||new Date().toISOString()});this.emit();}
 async request(path:string,method:string,call:()=>Promise<any>){
  const epoch=this.epoch,write=method!=='GET'&&method!=='HEAD',id='request:'+String(++this.serial),stamp=new Date().toISOString();
  if(write&&!path.endsWith('/cancel')){this.records.set(id,{id,request:true,status:'running',created_at:stamp,serial:this.serial,progress:{code:'request',label:actionLabel(path),kind:'request',started_at:stamp,stage_started_at:stamp}});this.emit();}
  try{
   const value=await call();if(epoch!==this.epoch)return value;
   if(write)this.records.delete(id);
   if(value?.task_id)this.update({id:value.task_id,status:value.status||'queued',created_at:stamp,label:actionLabel(path)});
   else if(/^\/tasks\/[^/]+$/.test(path)&&!path.endsWith('/active'))this.update(value);
   else if(value?.pending_task)this.update({id:value.pending_task,status:'running',label:'Reconnecting to your saved action'});
   this.emit();return value;
  }catch(error){
   if(epoch===this.epoch){
    if(write){
     const status=(error as any)?.status||0;
     if(!status||status>=500){const old=this.records.get(id);if(old)this.records.set(id,{...old,status:'unknown',connection_lost:true,checked_at:new Date().toISOString(),settled:true,serial:++this.serial});}
     else this.records.delete(id);
     this.emit();
    }
   }
   throw error;
  }
 }
}
export const processing=new ProcessingStore();
