export function costTicks(rows:{key:string}[],bucket:string,width:number){
 const times=rows.map(r=>Date.parse(r.key+(bucket==='month'?'-01':'')+'T00:00:00Z'));
 const min=Math.min(...times),max=Math.max(...times),span=max-min||1;
 const position=(i:number)=>max===min?width/2:(times[i]-min)/span*width;
 const selected:number[]=[];
 for(let i=0;i<rows.length;i++)if(!i||i===rows.length-1||position(i)-position(selected.at(-1)!)>=82){
  if(i===rows.length-1&&selected.length>1&&position(i)-position(selected.at(-1)!)<82)selected.pop();
  selected.push(i);
 }
 const years=new Set(times.map(t=>new Date(t).getUTCFullYear()));
 return {times,min,max,position,ticks:selected.map(i=>({index:i,x:position(i),label:(bucket==='week'?'Wk ': '')+new Date(times[i]).toLocaleDateString(undefined,{timeZone:'UTC',month:'short',...(bucket==='month'?{year:'numeric' as const}:{day:'numeric' as const,...(years.size>1?{year:'2-digit' as const}:{})})})}))};
}
