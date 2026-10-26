export type ForYouIntent={scope:'broad'|'targeted';roles:string[]};
export function forYouIntent(value:unknown):ForYouIntent|null{
 if(value==='yes')return {scope:'broad',roles:[]};
 try{const v=typeof value==='string'?JSON.parse(value):value;if(v?.scope==='broad')return {scope:'broad',roles:[]};if(v?.scope==='targeted'&&Array.isArray(v.roles)){const roles=[...new Set<string>(v.roles.filter((x:unknown)=>typeof x==='string').map((x:string)=>x.trim()).filter((x:string)=>x&&x.length<=80))].slice(0,4);if(roles.length)return {scope:'targeted',roles};}}catch{}return null;
}
export function takeForYouIntent(storage:Pick<Storage,'getItem'|'removeItem'>,account:string){const key='career-start-for-you:'+account;const raw=storage.getItem(key);storage.removeItem(key);return forYouIntent(raw);}
