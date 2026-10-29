import React from 'react';
import './explicitContext.css';


function contextMedian(item:any){
 const pay=item.salary,values=pay?.values,median=values?.median,format=(v:number)=>new Intl.NumberFormat(undefined,{style:'currency',currency:'USD',maximumFractionDigits:0}).format(v);
 if(pay){const unit=values?.unit||'year';if(typeof median==='number')return format(median)+' / '+unit;if(median==='#'&&pay.reporting_threshold?.[unit])return format(pay.reporting_threshold[unit])+' or more / '+unit;return 'not reported for this area';}
 return typeof item.median_wage==='number'?format(item.median_wage)+' / year':'not reported';
}

export function ExplicitContext({items,onRemove,onRefresh,disabled=false}:{items:any[];onRemove?:(index:number)=>void;onRefresh?:(index:number)=>void;disabled?:boolean}){
 if(!items.length)return null;
 return <section className="explicit-context" aria-label="Explicitly selected conversation context"><h3>Selected context for this conversation</h3><p className="small muted">Shared when you send, even if automatic Career Goals guidance is off. Other goals and bookmarks are not included by this selection. This does not change your Profile or resume.</p>{items.map((item,i)=><article key={item.context_ref.kind+':'+item.context_ref.id}><strong>{item.title||item.label}</strong>{item.context_ref.kind==='occupation'?<><p>{item.description}</p><p className="small">Skills: {(item.skills||[]).slice(0,8).map((v:any)=>v.name).join(' · ')||'Not reported'}</p><p className="small muted">O*NET {item.code} · {item.dataset_version} · Pay year: {item.wage_year||'not reported'} · Growth: {item.metadata?.growth_period||'not reported'}. These describe an occupation, not your qualifications.</p><details><summary>Outlook and source</summary><p>{item.salary?.area?.title||'United States'} median pay: {contextMedian(item)}. Projected growth: {item.growth==null?'not reported':item.growth+'%'}. Annual openings: {item.openings??'not reported'}. Published medians are not starting pay; projections are not live vacancies.</p><a href={item.onet_url} target="_blank" rel="noreferrer">O*NET source ↗</a></details></>:<><p className="small">Only the offer details shown here will be explicitly shared.</p><dl>{Object.entries(item.details||{}).filter(([,v])=>v!==''&&v!=null).map(([key,value])=><div key={key}><dt>{key.replaceAll('_',' ')}</dt><dd>{String(value)}</dd></div>)}</dl></>}
 <div className="card-actions">{onRefresh&&<button type="button" className="text-button" disabled={disabled} onClick={()=>onRefresh(i)}>Refresh context preview</button>}{onRemove&&<button type="button" className="text-button" disabled={disabled} onClick={()=>onRemove(i)}>Remove selected context</button>}</div></article>)}</section>;
}

export {refreshExplicit,acceptHandoff,contextFromSources,readContextDraft,saveContextDraft} from './explicitContextData';
