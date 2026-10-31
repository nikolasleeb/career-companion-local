import {confirmAction} from './WorkspaceDialog';
type Handoff={account:string;values:string[];handled:boolean;resolve:(accepted:boolean)=>void};
export function offerResourceHandoff(target:'jobs'|'skills',account:string,values:string[]){
 return new Promise<boolean>(resolve=>{const detail:Handoff={account,values,handled:false,resolve};window.dispatchEvent(new CustomEvent('career-resource-'+target,{detail}));if(!detail.handled){try{sessionStorage.setItem((target==='jobs'?'career-explorer-search:':'career-explorer-skills:')+account,target==='jobs'?values[0]:JSON.stringify(values));resolve(true);}catch{resolve(false);}}});
}
export function listenResourceHandoff(target:'jobs'|'skills',account:string,current:()=>string[],apply:(values:string[])=>void){
 const handler=(event:Event)=>{const detail=(event as CustomEvent<Handoff>).detail;if(detail.account!==account)return;detail.handled=true;void(async()=>{const before=current();if(before.length&&JSON.stringify(before)!==JSON.stringify(detail.values)&&!await confirmAction({title:'Replace selected '+(target==='jobs'?'roles':'topics')+'?',message:'Use the occupation selection here? Your other filters are kept. No search or AI request starts.',confirmLabel:'Use selection',cancelLabel:'Keep my selection'})){detail.resolve(false);return;}apply(detail.values);detail.resolve(true);})();};window.addEventListener('career-resource-'+target,handler);return()=>window.removeEventListener('career-resource-'+target,handler);
}
