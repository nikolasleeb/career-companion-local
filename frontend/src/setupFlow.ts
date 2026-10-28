export const setupViews=['master','settings','explorer'];
export function setupView(view:string,completed:boolean){return completed||setupViews.includes(view)?view:'master';}
export function restoredSetup(previous:any,completed:boolean){return {view:setupView(previous?.view||(completed?'applications':'master'),completed),jobId:completed&&typeof previous?.jobId==='string'?previous.jobId:'',applicationId:completed&&typeof previous?.applicationId==='string'?previous.applicationId:''};}
