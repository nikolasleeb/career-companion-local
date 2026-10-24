export function localDate(value=new Date()){return [value.getFullYear(),String(value.getMonth()+1).padStart(2,'0'),String(value.getDate()).padStart(2,'0')].join('-');}
export function costRange(days:number,today=new Date()){const start=new Date(today.getFullYear(),today.getMonth(),today.getDate());start.setDate(start.getDate()-days+1);return {start:localDate(start),end:localDate(today)};}
export type CostFilter={start:string;end:string;model:string;process:string;tz:string;bucket:string};
export function costQuery(filter:CostFilter,offset?:number){const params=new URLSearchParams();for(const [key,value] of Object.entries(filter))if(value)params.set(key,value);if(offset!==undefined){params.set('offset',String(offset));params.set('limit','30');}return '?'+params.toString();}
export function dollars(value:number|null|undefined){return value==null?'Unpriced':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',minimumFractionDigits:4,maximumFractionDigits:6}).format(value);}
export function costAmount(row:{estimated_cost_usd?:number|null;estimated_cost_upper_usd?:number|null;partial?:boolean;unpriced_requests?:number}){
 if(row.estimated_cost_usd==null)return 'Unpriced';
 if(row.estimated_cost_upper_usd!=null&&row.estimated_cost_upper_usd>row.estimated_cost_usd)return dollars(row.estimated_cost_usd)+'–'+dollars(row.estimated_cost_upper_usd);
 return (row.partial||row.unpriced_requests?'At least ':'')+dollars(row.estimated_cost_usd);
}
