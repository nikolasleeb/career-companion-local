import React,{useEffect,useId,useLayoutEffect,useMemo,useRef,useState} from 'react';
import {costTicks} from './costChartTicks';
import {costAmount,dollars} from './costHistoryData';
import {ChartMetric,UsageBucket,chartPeriods,chartValue,periodLabel,recordedTokens,tokenMissing,tokenText,tokenTotalText} from './usageChartData';
import './usageChart.css';
export function UsageChart({rows,bucket,start,end}:{rows:UsageBucket[];bucket:string;start:string;end:string}){
 const ref=useRef<HTMLElement>(null),svg=useRef<SVGSVGElement>(null),tip=useRef<HTMLDivElement>(null),regions=useRef(new Map<string,SVGGElement>()),id=useId();
 const [size,setSize]=useState(790),[metric,setMetric]=useState<ChartMetric>('cost'),[active,setActive]=useState<string|null>(null),[pinned,setPinned]=useState(false),[focusKey,setFocusKey]=useState(''),[tipPosition,setTipPosition]=useState({left:12,top:60});
 const periods=useMemo(()=>chartPeriods(rows,costTicks(rows,bucket,700,start,end).periods),[rows,bucket,start,end]);
 const width=Math.max(160,size-80),left=48,baseline=185,height=150;
 const scale=useMemo(()=>costTicks(periods,bucket,width,start,end),[periods,bucket,width,start,end]);
 const highest=Math.max(0,...rows.map(row=>chartValue(row,metric))),peak=highest||(metric==='cost'?.000001:1),barWidth=Math.min(24,Math.max(3,width/Math.max(1,periods.length)*.5));
 const current=periods.find(row=>row.key===active),focus=periods.some(p=>p.key===focusKey)?focusKey:periods[0]?.key;
 const title=bucket==='month'?'monthly':bucket==='week'?'weekly':'daily';
 useEffect(()=>{const node=ref.current;if(!node)return;const observer=new ResizeObserver(entries=>setSize(Math.max(260,entries[0].contentRect.width)));observer.observe(node);return()=>observer.disconnect();},[]);
 useEffect(()=>{setActive(null);setPinned(false);},[rows,bucket,start,end,metric]);
 useEffect(()=>{if(!active)return;const outside=(event:PointerEvent)=>{if(!ref.current?.contains(event.target as Node)){setActive(null);setPinned(false);}};const escape=(event:KeyboardEvent)=>{if(event.key==='Escape'){setActive(null);setPinned(false);}};document.addEventListener('pointerdown',outside);document.addEventListener('keydown',escape);return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',escape);};},[active]);
 useLayoutEffect(()=>{
  if(!current||!ref.current||!svg.current||!tip.current)return;
  const box=ref.current.getBoundingClientRect(),graph=svg.current.getBoundingClientRect(),tooltip=tip.current.getBoundingClientRect(),index=periods.findIndex(p=>p.key===current.key);
  const anchor=left+scale.position(index),x=Math.max(12,Math.min(box.width-tooltip.width-12,graph.left-box.left+anchor-tooltip.width/2));
  const point=baseline-chartValue(current,metric)/peak*height,y=Math.max(graph.top-box.top+8,Math.min(graph.bottom-box.top-tooltip.height-8,graph.top-box.top+point-tooltip.height-12));
  setTipPosition({left:x,top:y});
 },[active,metric,size,rows,periods]);
 function move(event:React.KeyboardEvent,index:number){
  const next=event.key==='Home'?0:event.key==='End'?periods.length-1:event.key==='ArrowRight'?Math.min(index+1,periods.length-1):event.key==='ArrowLeft'?Math.max(0,index-1):-1;
  if(next>=0){event.preventDefault();setPinned(false);const key=periods[next].key;setFocusKey(key);regions.current.get(key)?.focus();}
  if(event.key==='Enter'||event.key===' '){event.preventDefault();setPinned(!pinned);setActive(periods[index].key);}
 }
 function description(row:UsageBucket){
  const date=periodLabel(row.key,bucket,start,end);if(!row.requests)return date+': No recorded requests.';
  return date+': '+(metric==='cost'?costAmount(row):tokenTotalText(row))+' · '+row.requests+' requests.';
 }
 return <figure className="cost-chart usage-chart" ref={ref} aria-labelledby={id+'-title'}>
  <figcaption className="usage-chart-header"><span id={id+'-title'}>{metric==='cost'?'Estimated cost':'Recorded tokens'} over time · {title}</span><div className="usage-chart-switch" role="group" aria-label="Chart metric">{(['cost','tokens'] as const).map(value=><button type="button" key={value} aria-pressed={metric===value} onClick={()=>setMetric(value)}>{value==='cost'?'Cost':'Tokens'}</button>)}</div></figcaption>
  {metric==='tokens'&&<div className="usage-chart-legend"><span><i className="usage-input"/>Input</span><span><i className="usage-output"/>Output</span><small>Cached input is included in Input; reasoning is included in Output.</small></div>}
  {!rows.length&&<p>No activity in this range.</p>}
  <svg ref={svg} viewBox={'0 0 '+size+' 235'} role="group" aria-label={(metric==='cost'?'Estimated costs':'Recorded input and output tokens')+' by '+bucket}>
   <desc>Hover, focus or tap a period for details. Use Left/Right arrows, Home or End to move; Escape dismisses details.</desc>
   <line x1={left} y1={baseline} x2={left+width} y2={baseline} stroke="#cad5e5"/>
   <text x={left} y="20">{metric==='cost'?(rows.length&&rows.every(row=>row.estimated_cost_usd==null)?'Unpriced':dollars(highest)):!highest&&rows.some(row=>row.requests&&tokenMissing(row))?'Not reported':new Intl.NumberFormat(undefined,{notation:'compact',maximumFractionDigits:1}).format(highest)}</text>
   {periods.map((row,index)=>{
    const x=left+scale.position(index),value=chartValue(row,metric),barHeight=value/peak*height,inputHeight=(row.input_tokens||0)/peak*height,outputHeight=(row.output_tokens||0)/peak*height;
    const previous=index?left+scale.position(index-1):left,next=index<periods.length-1?left+scale.position(index+1):left+width;
    const hitLeft=index?(previous+x)/2:left,hitRight=index===periods.length-1?left+width:(next+x)/2;
    const unknown=metric==='cost'?row.requests>0&&row.estimated_cost_usd==null:row.requests>0&&tokenMissing(row)>0&&!value;
    return <g key={row.key} ref={node=>{if(node)regions.current.set(row.key,node);else regions.current.delete(row.key);}} role="button" data-usage-period={row.key} tabIndex={row.key===focus?0:-1} aria-label={description(row)} aria-describedby={active===row.key?id+'-tooltip':undefined} onFocus={()=>{setActive(row.key);setFocusKey(row.key);}} onBlur={()=>{if(!pinned)setActive(null);}} onKeyDown={event=>move(event,index)} onPointerEnter={event=>{if(event.pointerType!=='touch'&&!pinned)setActive(row.key);}} onPointerLeave={event=>{if(event.pointerType!=='touch'&&!pinned&&document.activeElement!==regions.current.get(row.key))setActive(null);}} onClick={()=>{setFocusKey(row.key);setActive(pinned&&active===row.key?null:row.key);setPinned(!(pinned&&active===row.key));}}>
     {active===row.key&&<rect x={hitLeft} y="25" width={Math.max(1,hitRight-hitLeft)} height={baseline-25} fill="#edf2f8"/>}
     {metric==='cost'&&row.requests>0&&value>0&&<rect x={x-barWidth/2} y={baseline-barHeight} width={barWidth} height={Math.max(1,barHeight)} rx="2" fill="#ad0028"/>}
     {metric==='tokens'&&<>{inputHeight>0&&<rect x={x-barWidth/2} y={baseline-inputHeight} width={barWidth} height={inputHeight} fill="#245a81"/>}{outputHeight>0&&<rect x={x-barWidth/2} y={baseline-inputHeight-outputHeight} width={barWidth} height={outputHeight} fill="#ad0028"/>}</>}
     {unknown&&<path d={'M '+(x-5)+' '+(baseline-3)+' L '+x+' '+(baseline-10)+' L '+(x+5)+' '+(baseline-3)} fill="none" stroke="#677386" strokeWidth="2"/>}
     <rect className="usage-hit-region" x={hitLeft} y="25" width={Math.max(1,hitRight-hitLeft)} height={baseline-20} fill="transparent"/>
    </g>;
   })}
   {scale.ticks.map((tick,index)=><text key={tick.key} x={left+tick.x} y="213" textAnchor={index===0?'start':index===scale.ticks.length-1?'end':'middle'}>{tick.label}</text>)}
  </svg>
  {current&&<div ref={tip} id={id+'-tooltip'} className="usage-tooltip" role="tooltip" style={tipPosition}><strong>{periodLabel(current.key,bucket,start,end)}</strong>{!current.requests?<p>No recorded requests</p>:<>{metric==='cost'?<><p className="usage-tooltip-total">{costAmount(current)}</p><p>{current.requests.toLocaleString()} provider request{current.requests===1?'':'s'}</p>{!!current.unpriced_requests&&<p>{current.unpriced_requests} partial / unpriced. Unknown charges are not zero.</p>}</>:<><p className="usage-tooltip-total">{tokenTotalText(current)}</p><dl><div><dt>Input</dt><dd>{tokenText(current.input_tokens||0,tokenMissing(current))}</dd></div><div><dt>Output</dt><dd>{tokenText(current.output_tokens||0,tokenMissing(current))}</dd></div><div><dt>Cached input · included</dt><dd>{tokenText(current.cached_input_tokens||0,current.cached_requests_missing??current.requests)}</dd></div><div><dt>Reasoning · included</dt><dd>{tokenText(current.reasoning_tokens||0,current.reasoning_requests_missing??current.requests)}</dd></div></dl><p>{current.requests.toLocaleString()} provider request{current.requests===1?'':'s'}</p>{!!tokenMissing(current)&&<p>Token counts not reported for {tokenMissing(current)} request{tokenMissing(current)===1?'':'s'}; totals include recorded counts only.</p>}</>}</>}</div>}
  <p className="small muted">Dates include periods with no recorded usage. Hover, focus or tap for details; arrow keys move between periods.</p>
  <details><summary>Chart dates and exact amounts</summary>{bucket==='week'&&<p className="small muted">Weeks start Monday. Totals include only activity within the selected date range.</p>}<div className="cost-table-scroll"><table><thead><tr><th scope="col">{bucket==='week'?'Week starting':bucket==='month'?'Month':'Date'}</th><th scope="col">Requests</th>{metric==='cost'?<><th scope="col">Estimate</th><th scope="col">Partial / unpriced</th></>:<><th scope="col">Input</th><th scope="col">Output</th><th scope="col">Total recorded</th><th scope="col">Coverage</th></>}</tr></thead><tbody>{rows.map(row=><tr key={row.key}><th scope="row">{row.key}</th><td>{row.requests}</td>{metric==='cost'?<><td>{costAmount(row)}</td><td>{row.unpriced_requests}</td></>:<><td>{tokenText(row.input_tokens||0,tokenMissing(row))}</td><td>{tokenText(row.output_tokens||0,tokenMissing(row))}</td><td>{tokenText(recordedTokens(row),tokenMissing(row))}</td><td>{tokenMissing(row)?tokenMissing(row)+' request'+(tokenMissing(row)===1?'':'s')+' without complete token counts':'Reported'}</td></>}</tr>)}</tbody></table></div></details>
 </figure>;
}
