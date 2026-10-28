const dateValue=(key:string)=>Date.parse((key.length===7?key+'-01':key)+'T00:00:00Z');
function bucketStart(value:number,bucket:string){const d=new Date(value);if(bucket==='week')d.setUTCDate(d.getUTCDate()-((d.getUTCDay()+6)%7));if(bucket==='month')d.setUTCDate(1);return d.getTime();}
export function costTicks(rows:{key:string}[],bucket:string,width:number,start='',end=''){
 const times=rows.map(r=>dateValue(r.key));
 const today=new Date(),fallback=Date.UTC(today.getFullYear(),today.getMonth(),today.getDate());
 const first=dateValue(start),last=dateValue(end);
 const min=bucketStart(Number.isFinite(first)?first:times[0]??fallback,bucket),max=bucketStart(Number.isFinite(last)?last:times.at(-1)??min,bucket),span=max-min||1;
 const position=(i:number)=>max===min?width/2:(times[i]-min)/span*width;
 // Calendar candidates include periods with no requests. Keep work bounded for
 // unusually long custom ranges; displayed labels still use the same time scale.
 const candidates:number[]=[];const stride=bucket==='month'?Math.max(1,Math.ceil((max-min)/(86400000*28*4000))):Math.max(1,Math.ceil((max-min)/(86400000*(bucket==='week'?7:1)*4000)));
 for(let value=min;value<=max;){candidates.push(value);const next=new Date(value);if(bucket==='month')next.setUTCMonth(next.getUTCMonth()+stride);else next.setUTCDate(next.getUTCDate()+stride*(bucket==='week'?7:1));value=next.getTime();}
 if(candidates.at(-1)!==max&&max>=min)candidates.push(max);
 const x=(time:number)=>max===min?width/2:(time-min)/span*width,selected:number[]=[];
 for(let i=0;i<candidates.length;i++)if(!i||i===candidates.length-1||x(candidates[i])-x(candidates[selected.at(-1)!])>=82){
  if(i===candidates.length-1&&selected.length>1&&x(candidates[i])-x(candidates[selected.at(-1)!])<82)selected.pop();selected.push(i);
 }
 const acrossYears=new Date(min).getUTCFullYear()!==new Date(max).getUTCFullYear();
 return {times,min,max,position,periods:candidates.map(value=>new Date(value).toISOString().slice(0,bucket==='month'?7:10)),ticks:selected.map(i=>({index:i,key:new Date(candidates[i]).toISOString().slice(0,bucket==='month'?7:10),x:x(candidates[i]),label:(bucket==='week'?'Wk ':'')+new Date(candidates[i]).toLocaleDateString(undefined,{timeZone:'UTC',month:'short',...(bucket==='month'?{year:'numeric' as const}:{day:'numeric' as const,...(acrossYears?{year:'2-digit' as const}:{})})})}))};
}
