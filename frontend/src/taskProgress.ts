export type TaskStatus={id?:string;can_cancel?:boolean;status:string;created_at?:string;updated_at?:string;checked_at?:string;connection_lost?:boolean;job_id?:string;operation?:string;label?:string;kind?:string;progress?:{code:string;label:string;kind:string;started_at:string;stage_started_at:string;finished_at?:string;loaded_bytes?:number;total_bytes?:number}|null};
export function elapsed(start:string|undefined,now:number){const stamp=Date.parse(start||'');return Number.isFinite(stamp)?Math.max(0,Math.floor((now-stamp)/1000)):0;}
export function duration(seconds:number){const m=Math.floor(seconds/60),s=seconds%60;return m+':'+String(s).padStart(2,'0');}
function uploadDetail(progress:NonNullable<TaskStatus['progress']>){
 const loaded=progress.loaded_bytes||0,total=progress.total_bytes||0;
 const amount=loaded?`${(loaded/1024/1024).toFixed(1)} MB${total?` of ${(total/1024/1024).toFixed(1)} MB (${Math.min(100,Math.floor(100*loaded/total))}%)`:''} uploaded. `:'';
 return amount+'Sending files to your workspace. No OpenAI request in this stage.';
}
export function progressView(task:TaskStatus,now:number){
 const unknown=task.connection_lost||task.status==='unknown';
 const running=['queued','running','cancelling'].includes(task.status)&&!unknown;
 const end=running?now:Date.parse(unknown?(task.checked_at||task.updated_at||task.created_at||''):(task.progress?.finished_at||task.updated_at||task.created_at||''))||0;
 return {running,unknown,label:unknown?'Status connection lost':task.progress?.label||task.label||(task.status==='queued'?'Waiting to start':task.kind==='resume_guided'||!task.kind?'Resume action running':'Processing '+task.kind.replaceAll('_',' ')),detail:unknown?'The task may still be running. Check saved status before starting another request. Timers show the last confirmed update.':task.progress?.kind==='upload'?uploadDetail(task.progress):task.progress?.kind==='upload_wait'?'Upload sent. Waiting for the workspace to read the files and prepare the preview. No OpenAI request in this stage.':task.progress?.kind==='source_preparation'?'Downloading and reading selected files. No OpenAI request in this stage.':task.progress?.kind==='request'?'Sending your request to the app. Waiting for confirmation.':task.progress?.kind==='provider'?'Waiting for AI response. This stage can take several minutes.':task.progress?.kind==='local'?'Processing locally; no AI request in this stage.':'Checking saved task status; no additional AI request.',total:duration(elapsed(task.progress?.started_at||task.created_at,end)),stage:task.progress?.stage_started_at?duration(elapsed(task.progress.stage_started_at,unknown?Date.parse(task.checked_at||task.updated_at||'')||end:end)):null};
}
