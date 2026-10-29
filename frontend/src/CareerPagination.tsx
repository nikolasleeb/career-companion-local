import React from 'react';
import {careerPages} from './careerPages';
export function CareerPagination({total,offset,limit=12,busy,onPage}:{total:number;offset:number;limit?:number;busy:boolean;onPage:(offset:number)=>void}){
 const pages=Math.ceil(total/limit),current=Math.floor(offset/limit)+1;
 if(pages<2)return null;
 const go=(page:number)=>{if(!busy&&page!==current)onPage((page-1)*limit);};
 return <nav className="career-pagination" aria-label="Career results pages" aria-busy={busy}><button type="button" className="button secondary" disabled={busy||current===1} onClick={()=>go(current-1)}>Previous</button>{careerPages(pages,current).map((page,index)=>page==='gap'?<span className="career-page-gap" key={'gap-'+index} aria-hidden="true">…</span>:<button type="button" className="button secondary career-page-number" aria-label={'Page '+page} aria-current={page===current?'page':undefined} disabled={busy} onClick={()=>go(page)} key={page}>{page}</button>)}<button type="button" className="button secondary" disabled={busy||current===pages} onClick={()=>go(current+1)}>Next</button>{pages>9&&<label className="career-page-select">Go to page<select value={current} disabled={busy} onChange={e=>go(Number(e.target.value))}>{Array.from({length:pages},(_,i)=><option key={i+1} value={i+1}>{i+1}</option>)}</select></label>}<span className="small muted">{offset+1}–{Math.min(offset+limit,total)} of {total}</span>{busy&&<span className="small muted" role="status">Loading careers…</span>}</nav>;
}
