export function uniqueRoles(values:string[],limit=50){const seen=new Set<string>();return values.map(v=>v.trim().replace(/\s+/g,' ')).filter(v=>{const k=v.toLocaleLowerCase();if(!v||seen.has(k))return false;seen.add(k);return true;}).slice(0,limit);}
export function addRole(selected:string[],term:string){const value=term.trim().replace(/\s+/g,' ');if(value.length<2||value.length>80)throw new Error('Use 2–80 characters for each role.');const next=uniqueRoles([...selected,value]);if(next.length>12)throw new Error('Choose up to 12 roles. Remove one before adding another.');return next;}
export function recentRoles(history:string[],added:string[]){return uniqueRoles([...added,...history],50);}
export function roleChoices(selected:string[],history:string[],text:string,catalog:string[]=[]){const all=uniqueRoles([...history,...selected,...catalog]);const q=text.trim().toLocaleLowerCase();return all.filter(v=>!q||v.toLocaleLowerCase().includes(q));}
// Serialize writes so a slow earlier response cannot overwrite a later selection.
export function preferenceSaver(save:(value:any)=>Promise<unknown>,report:(state:string)=>void,delay=350){
 let latest:any=null,ack='',queued='',timer:ReturnType<typeof setTimeout>|undefined,chain=Promise.resolve(),active=true;
 const emit=(value:string)=>{if(active)report(value);};
 function flush(){if(timer)clearTimeout(timer);timer=undefined;if(!latest)return chain;const value=latest,key=JSON.stringify(value);if(key===queued)return chain;if(key===ack&&!queued)return chain.catch(()=>{});queued=key;emit('saving');chain=chain.catch(()=>{}).then(async()=>{try{await save(value);ack=key;if(queued===key)queued='';if(JSON.stringify(latest)===key)emit('saved');}catch(e){if(queued===key)queued='';if(JSON.stringify(latest)===key)emit('error');throw e;}});return chain;}
 return {prime(value:any){ack=JSON.stringify(value);latest=value;},update(value:any){latest=value;if(timer)clearTimeout(timer);if(JSON.stringify(value)===ack&&!queued){emit('saved');return;}emit('pending');timer=setTimeout(()=>{void flush().catch(()=>{});},delay);},flush,dispose(){active=false;void flush().catch(()=>{});}};
}

export function addBundle(selected:string[],bundle:string[]){const next=uniqueRoles([...selected,...bundle]);if(next.length>12)throw new Error('This field would exceed the 12-role limit. Remove some selected roles first; no roles were added.');return next;}
