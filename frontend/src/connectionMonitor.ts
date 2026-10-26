export type ConnectionState='checking'|'connected'|'signin'|'lost';
export const connectionLabels:Record<ConnectionState,string>={checking:'Checking connection',connected:'Connected',signin:'Sign-in required',lost:'Connection lost'};
type Events={addEventListener:(type:string,fn:()=>void)=>void;removeEventListener:(type:string,fn:()=>void)=>void};
type Environment={window:Events;document:Events&{visibilityState:string};online:()=>boolean;setTimeout:typeof setTimeout;clearTimeout:typeof clearTimeout};
export function monitorConnection(probe:(signal:AbortSignal)=>Promise<unknown>,change:(state:ConnectionState)=>void,env:Environment){
 let alive=true,busy=false,timer:ReturnType<typeof setTimeout>|undefined,controller:AbortController|undefined;
 const clear=()=>{if(timer!==undefined)env.clearTimeout(timer);timer=undefined;};
 const schedule=()=>{clear();if(alive&&env.document.visibilityState==='visible')timer=env.setTimeout(()=>void check(),60000);};
 async function check(){
  if(!alive||busy||env.document.visibilityState!=='visible')return;
  clear();if(!env.online()){change('lost');schedule();return;}
  busy=true;controller=new AbortController();const request=controller;change('checking');let timeout:ReturnType<typeof setTimeout>|undefined;
  try{
   await Promise.race([probe(request.signal),new Promise((_,reject)=>{timeout=env.setTimeout(()=>{request.abort();reject(new Error('timeout'));},5000);})]);
   if(alive)change(env.online()?'connected':'lost');
  }catch(error){if(alive)change([401,403].includes((error as any)?.status)?'signin':'lost');}
  finally{if(timeout!==undefined)env.clearTimeout(timeout);busy=false;controller=undefined;schedule();}
 }
 const wake=()=>{if(env.document.visibilityState==='visible'){clear();void check();}else clear();};
 const offline=()=>{if(alive)change('lost');controller?.abort();};
 env.window.addEventListener('focus',wake);env.window.addEventListener('online',wake);env.window.addEventListener('offline',offline);env.document.addEventListener('visibilitychange',wake);void check();
 return()=>{alive=false;clear();controller?.abort();env.window.removeEventListener('focus',wake);env.window.removeEventListener('online',wake);env.window.removeEventListener('offline',offline);env.document.removeEventListener('visibilitychange',wake);};
}
