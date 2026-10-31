export const setupViews=['home','master','settings','explorer','coach','interests','prep','interviews','guide'];
export function setupView(view:string,completed:boolean){return completed||setupViews.includes(view)?view:'master';}
export function restoredSetup(previous:any,completed:boolean){return {view:completed?setupView(previous?.view||'applications',true):'master',jobId:completed&&typeof previous?.jobId==='string'?previous.jobId:'',applicationId:completed&&typeof previous?.applicationId==='string'?previous.applicationId:''};}
