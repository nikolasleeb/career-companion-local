export type ChartMetric='cost'|'tokens';
export type UsageBucket={key:string;requests:number;estimated_cost_usd?:number|null;estimated_cost_upper_usd?:number|null;unpriced_requests?:number;input_tokens?:number;output_tokens?:number;cached_input_tokens?:number;reasoning_tokens?:number;token_requests_reported?:number;token_requests_missing?:number;cached_requests_missing?:number;reasoning_requests_missing?:number};
export function chartPeriods(rows:UsageBucket[],keys:string[]){
 const index=new Map(rows.map(row=>[row.key,row]));
 return [...new Set([...keys,...rows.map(r=>r.key)])].sort().map(key=>index.get(key)||{key,requests:0,estimated_cost_usd:0,unpriced_requests:0,input_tokens:0,output_tokens:0,cached_input_tokens:0,reasoning_tokens:0,token_requests_reported:0,token_requests_missing:0,cached_requests_missing:0,reasoning_requests_missing:0});
}
export const recordedTokens=(row:UsageBucket)=>(row.input_tokens||0)+(row.output_tokens||0);
export function tokenMissing(row:UsageBucket){return row.token_requests_missing??(row.requests?row.requests:0);}
export function tokenText(value:number,missing:number){return missing?(value?'At least '+value.toLocaleString():'Not reported'):value.toLocaleString();}
export function chartValue(row:UsageBucket,metric:ChartMetric){return metric==='tokens'?recordedTokens(row):row.estimated_cost_usd||0;}
const stamp=(key:string)=>new Date((key.length===7?key+'-01':key)+'T00:00:00Z');
const iso=(date:Date)=>date.toISOString().slice(0,10);
export function periodLabel(key:string,bucket:string,start='',end=''){
 const first=stamp(key),last=new Date(first);
 if(bucket==='week')last.setUTCDate(last.getUTCDate()+6);
 if(bucket==='month'){last.setUTCMonth(last.getUTCMonth()+1);last.setUTCDate(0);}
 const lower=start&&start>iso(first)?start:iso(first),upper=end&&end<iso(last)?end:iso(last);
 const format=(value:string)=>stamp(value).toLocaleDateString(undefined,{timeZone:'UTC',month:'short',day:'numeric',year:'numeric'});
 return lower===upper?format(lower):format(lower)+' – '+format(upper);
}

export function tokenTotalText(row:UsageBucket){return tokenMissing(row)&&!recordedTokens(row)?'Token counts not reported':tokenText(recordedTokens(row),tokenMissing(row))+' recorded tokens';}
