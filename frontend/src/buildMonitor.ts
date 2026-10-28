export const UPDATE_INTERVAL=3*60*60*1000;
export const validBuild=(value:unknown):value is string=>typeof value==='string'&&/^[a-f0-9]{32}$/.test(value);
type Events={addEventListener:(name:string,fn:()=>void)=>void;removeEventListener:(name:string,fn:()=>void)=>void};
type Environment={window:Events;document:Events&{visibilityState:string};online:()=>boolean;now:()=>number;setTimeout:typeof setTimeout;clearTimeout:typeof clearTimeout};
export function monitorBuild(probe:(signal:AbortSignal)=>Promise<unknown>,change:(id:string)=>void,env:Environment){
 let alive=true,busy=false,last:number|undefined,timer:ReturnType<typeof setTimeout>|undefined,controller:AbortController|undefined;
 const clear=()=>{if(timer!==undefined)env.clearTimeout(timer);timer=undefined;};
 function schedule(){clear();if(alive&&env.document.visibilityState==='visible')timer=env.setTimeout(()=>void check(),Math.max(0,UPDATE_INTERVAL-(env.now()-(last??env.now()))));}
 async function check(){
  if(!alive||busy||env.document.visibilityState!=='visible')return;
  clear();if(last!==undefined&&env.now()-last<UPDATE_INTERVAL){schedule();return;}
  if(!env.online())return;
  busy=true;last=env.now();controller=new AbortController();const active=controller;let timeout:ReturnType<typeof setTimeout>|undefined;
  try{
   const value=await Promise.race([probe(active.signal),new Promise((_,reject)=>{timeout=env.setTimeout(()=>{active.abort();reject(new Error('timeout'));},5000);})]);
   const id=(value as any)?.build_id;if(alive&&validBuild(id))change(id);
  }catch{/* Authentication and network failures are handled by the connection banner. */}
  finally{if(timeout!==undefined)env.clearTimeout(timeout);busy=false;controller=undefined;schedule();}
 }
 const wake=()=>{if(env.document.visibilityState==='visible')void check();else clear();};
 env.window.addEventListener('focus',wake);env.window.addEventListener('online',wake);env.document.addEventListener('visibilitychange',wake);void check();
 return()=>{alive=false;clear();controller?.abort();env.window.removeEventListener('focus',wake);env.window.removeEventListener('online',wake);env.document.removeEventListener('visibilitychange',wake);};
}
