import React,{useEffect,useId,useMemo,useRef,useState} from 'react';
import {costTicks} from './costChartTicks';
import {costAmount,dollars} from './costHistoryData';
import {ChartMetric,UsageBucket,chartPeriods,chartValue,periodLabel,recordedTokens,tokenMissing,tokenText,tokenTotalText} from './usageChartData';
import './usageChart.css';
export function UsageChart({rows,bucket,start,end}:{rows:UsageBucket[];bucket:string;start:string;end:string}){
 const ref=useRef<HTMLElement>(null),regions=useRef(new Map<string,SVGGElement>()),id=useId();
 const [size,setSize]=useState(790),[metric,setMetric]=useState<ChartMetric>('cost'),[active,setActive]=useState<string|null>(null),[pinned,setPinned]=useState(false),[focusKey,setFocusKey]=useState('');
 const periods=useMemo(()=>chartPeriods(rows,costTicks(rows,bucket,700,start,end).periods),[rows,bucket,start,end]);
 const width=Math.max(160,size-80),left=48,baseline=185,height=150;
 const scale=useMemo(()=>costTicks(periods,bucket,width,start,end),[periods,bucket,width,start,end]);
 const highest=Math.max(0,...rows.map(row=>chartValue(row,metric))),peak=highest||(metric==='cost'?.000001:1),barWidth=Math.min(24,Math.max(3,width/Math.max(1,periods.length)*.5));
 const current=periods.find(row=>row.key===active),focus=periods.some(p=>p.key===focusKey)?focusKey:periods[0]?.key;
 // A hidden, conservative sizing sample reserves the largest details layout
 // across both metrics. It contains no extra data requests or accessible content.
 const sizingRow=useMemo(()=>{
  const max=(key:keyof UsageBucket)=>Math.max(1,...rows.map(row=>typeof row[key]==='number'?row[key] as number:0));
  return {key:'',requests:max('requests'),estimated_cost_usd:max('estimated_cost_usd'),estimated_cost_upper_usd:max('estimated_cost_upper_usd')+max('estimated_cost_usd'),unpriced_requests:max('unpriced_requests'),input_tokens:max('input_tokens'),output_tokens:max('output_tokens'),cached_input_tokens:max('cached_input_tokens'),reasoning_tokens:max('reasoning_tokens'),token_requests_missing:max('token_requests_missing'),cached_requests_missing:1,reasoning_requests_missing:1};
 },[rows]);
 const title=bucket==='month'?'monthly':bucket==='week'?'weekly':'daily';
 useEffect(()=>{const node=ref.current;if(!node)return;const observer=new ResizeObserver(entries=>setSize(Math.max(260,entries[0].contentRect.width)));observer.observe(node);return()=>observer.disconnect();},[]);
 useEffect(()=>{setActive(null);setPinned(false);},[rows,bucket,start,end,metric]);
 useEffect(()=>{if(!active)return;const outside=(event:PointerEvent)=>{if(!ref.current?.contains(event.target as Node)){setActive(null);setPinned(false);}};const escape=(event:KeyboardEvent)=>{if(event.key==='Escape'){setActive(null);setPinned(false);}};document.addEventListener('pointerdown',outside);document.addEventListener('keydown',escape);return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',escape);};},[active]);
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
  <svg viewBox={'0 0 '+size+' 235'} role="group" aria-label={(metric==='cost'?'Estimated costs':'Recorded input and output tokens')+' by '+bucket}>
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
  <div className="usage-details-slot">
   <div className="usage-details-measure" aria-hidden="true" inert>{(['cost','tokens'] as const).map(value=><PeriodDetails key={value} row={sizingRow} metric={value} date="September 28, 2026 – September 30, 2026"/>)}<PeriodDetails row={{...sizingRow,input_tokens:0,output_tokens:0}} metric="tokens" date="September 28, 2026 – September 30, 2026"/></div>
   {current?<div id={id+'-tooltip'} role="tooltip"><PeriodDetails row={current} metric={metric} date={periodLabel(current.key,bucket,start,end)}/></div>:<div className="usage-details-placeholder">Hover, focus or tap a period to see details.</div>}
  </div>
  <p className="small muted">Dates include periods with no recorded usage. Hover, focus or tap for details; arrow keys move between periods.</p>
  <details><summary>Chart dates and exact amounts</summary>{bucket==='week'&&<p className="small muted">Weeks start Monday. Totals include only activity within the selected date range.</p>}<div className="cost-table-scroll"><table><thead><tr><th scope="col">{bucket==='week'?'Week starting':bucket==='month'?'Month':'Date'}</th><th scope="col">Requests</th>{metric==='cost'?<><th scope="col">Estimate</th><th scope="col">Partial / unpriced</th></>:<><th scope="col">Input</th><th scope="col">Output</th><th scope="col">Total recorded</th><th scope="col">Coverage</th></>}</tr></thead><tbody>{rows.map(row=><tr key={row.key}><th scope="row">{row.key}</th><td>{row.requests}</td>{metric==='cost'?<><td>{costAmount(row)}</td><td>{row.unpriced_requests}</td></>:<><td>{tokenText(row.input_tokens||0,tokenMissing(row))}</td><td>{tokenText(row.output_tokens||0,tokenMissing(row))}</td><td>{tokenText(recordedTokens(row),tokenMissing(row))}</td><td>{tokenMissing(row)?tokenMissing(row)+' request'+(tokenMissing(row)===1?'':'s')+' without complete token counts':'Reported'}</td></>}</tr>)}</tbody></table></div></details>
 </figure>;
}

function PeriodDetails({row,metric,date}:{row:UsageBucket;metric:ChartMetric;date:string}){
 return <div className="usage-period-details">
  <div><strong>{date}</strong>{!row.requests?<p>No recorded requests</p>:<p className="usage-details-total">{metric==='cost'?costAmount(row):tokenTotalText(row)}</p>}</div>
  <div>{!!row.requests&&metric==='tokens'&&<dl><div><dt>Input</dt><dd>{tokenText(row.input_tokens||0,tokenMissing(row))}</dd></div><div><dt>Output</dt><dd>{tokenText(row.output_tokens||0,tokenMissing(row))}</dd></div><div><dt>Cached input · included</dt><dd>{tokenText(row.cached_input_tokens||0,row.cached_requests_missing??row.requests)}</dd></div><div><dt>Reasoning · included</dt><dd>{tokenText(row.reasoning_tokens||0,row.reasoning_requests_missing??row.requests)}</dd></div></dl>}</div>
  <div>{!!row.requests&&<><p>{row.requests.toLocaleString()} provider request{row.requests===1?'':'s'}</p>{metric==='cost'?!!row.unpriced_requests&&<p>{row.unpriced_requests} partial / unpriced. Unknown charges are not zero.</p>:!!tokenMissing(row)&&<p>Token counts not reported for {tokenMissing(row)} request{tokenMissing(row)===1?'':'s'}; totals include recorded counts only.</p>}</>}</div>
 </div>;
}
