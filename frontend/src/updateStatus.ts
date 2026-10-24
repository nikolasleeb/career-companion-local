export type UpdateInfo={installed:{version:string;revision:string;built_at:string;channel:string};latest:{version:string;url:string;published_at:string}|null;state:string;checked_at:number|null;stale:boolean;error:string;needs_check:boolean;can_check:boolean;next_check_at:number;releases_url:string};
export function updateLabel(info:UpdateInfo){
 if(info.error)return 'Unable to check';
 if(info.state==='custom')return 'Custom build';
 if(info.stale&&info.latest)return 'Check needed';
 return ({update_available:'Update available',up_to_date:'Up to date',ahead:'Newer than the published release',not_checked:'Not checked',unknown:'Version unknown'} as Record<string,string>)[info.state]||'Version unknown';
}
