import type {TaskStatus} from './taskProgress';
const records=new Map<string,{account:string;scope:string;task:TaskStatus}>();
export function documentRecoveries(account:string){return [...records.values()].filter(v=>v.account===account);}
export function reportDocumentRecovery(account:string,scope:string,task:TaskStatus|null){
 const key=account+':'+scope;
 if(task?.status==='unknown')records.set(key,{account,scope,task});else records.delete(key);
 window.dispatchEvent(new Event('document-recovery-changed'));
}
