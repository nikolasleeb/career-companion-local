export const profileTabs=[{id:'upload',label:'Upload / import'},{id:'personal',label:'Personal details'},{id:'resume',label:'Resume content'},{id:'goals',label:'Career Goals'},{id:'private',label:'Private application answers'}] as const;
export type ProfileTab=typeof profileTabs[number]['id'];
export function savedProfileTab(account:string,storage:Pick<Storage,'getItem'>=sessionStorage):ProfileTab{
 try{const value=storage.getItem('career-profile-tab:'+account);return profileTabs.find(p=>p.id===value)?.id||'resume';}catch{return 'resume';}
}
