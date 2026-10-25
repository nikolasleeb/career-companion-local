export type UpdateInfo={source?:{state:string;revision:string|null;installed_revision?:string;url:string;error:string;checked_at?:number};release_state?:string;installed:{version:string;revision:string;built_at:string;channel:string};latest:{version:string;url:string;published_at:string}|null;state:string;checked_at:number|null;stale:boolean;error:string;needs_check:boolean;can_check:boolean;next_check_at:number;releases_url:string};
export function updateLabel(info:UpdateInfo){
 if(info.error)return 'Unable to check';
 if(info.release_state==='no_published_release')return 'No published release';
 if(info.state==='custom')return 'Custom build';
 if(info.stale&&info.latest)return 'Check needed';
 return ({update_available:'Update available',up_to_date:'Up to date',ahead:'Newer than the published release',not_checked:'Not checked',unknown:'Version unknown'} as Record<string,string>)[info.state]||'Version unknown';
}

export function sourceLabel(state:string){return ({source_available:'Newer source code available',up_to_date:'Source is current',ahead:'Build is ahead of public main',diverged:'Build has diverged',unknown_build:'Build revision unknown',unable_to_check:'Unable to compare source',not_checked:'Source not checked'} as Record<string,string>)[state]||'Source revision unknown';}
