export const months=['January','February','March','April','May','June','July','August','September','October','November','December'];
export type DatePolicy='past'|'end'|'future'|'employment-start'|'employment-end';
export function preserveSavedDate(policy:DatePolicy){return policy!=='employment-start'&&policy!=='employment-end';}
export function entryDatePolicy(category:string,field:string):DatePolicy{return category==='employment'&&field==='start_date'?'employment-start':category==='employment'&&field==='end_date'?'employment-end':category==='education'&&field==='start_date'?'past':field==='expected_graduation'?'future':'end';}
export type DateParts={y:string;m:string;d:string;legacy:boolean};
export const blankDate=():DateParts=>({y:'',m:'',d:'',legacy:false});
function localDate(y:number,m:number,d:number){return new Date(y,m-1,d);}
export function daysInMonth(y:string,m:string){return m?new Date(Number(y)||2000,Number(m),0).getDate():31;}
export function dateParts(value:string):DateParts{
 let y='',m='',d='';const iso=value.match(/^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$/);
 if(iso){y=iso[1];m=iso[2]?String(Number(iso[2])):'';d=iso[3]?String(Number(iso[3])):'';}
 else{const named=value.match(/^(?:([0-9]{1,2})\s+)?([A-Za-z]+)\s+(?:(\d{1,2}),?\s+)?(\d{4})$/);if(named){const i=months.findIndex(v=>v.toLowerCase().startsWith(named[2].toLowerCase()));if(i>=0){y=named[4];m=String(i+1);d=named[1]||named[3]||'';}}}
 const recognized=!!y&&Number(y)>=1000&&Number(y)<=9999&&(!m||Number(m)>=1&&Number(m)<=12)&&(!d||Number(d)>=1&&Number(d)<=daysInMonth(y,m));
 return recognized?{y,m,d,legacy:false}:{...blankDate(),legacy:!!value&&value!=='Present'};
}
export function updateDateParts(parts:DateParts,key:'y'|'m'|'d',value:string):DateParts{return {...parts,[key]:value,legacy:false};}
export function formatDate(parts:DateParts){return !parts.y||parts.d&&!parts.m?'':parts.m?months[Number(parts.m)-1]+' '+(parts.d?parts.d+', ':'')+parts.y:parts.y;}
export function interval(parts:DateParts):[Date,Date]|null{
 if(!parts.y||parts.d&&!parts.m||parts.d&&Number(parts.d)>daysInMonth(parts.y,parts.m))return null;
 const y=Number(parts.y),m=Number(parts.m);
 return [localDate(y,m||1,Number(parts.d)||1),localDate(y,m||12,Number(parts.d)||(m?daysInMonth(parts.y,parts.m):31))];
}
export function dateBounds(policy:DatePolicy,today=new Date()):[Date,Date]{
 const y=today.getFullYear(),m=today.getMonth(),d=today.getDate();
 const years=policy==='employment-end'?1:10;
 const anniversary=new Date(y+years,m,Math.min(d,new Date(y+years,m+1,0).getDate()));
 return policy==='past'||policy==='employment-start'?[new Date(1900,0,1),new Date(y,m,d-1)]:policy==='future'?[new Date(y,m,d+1),anniversary]:[new Date(1900,0,1),anniversary];
}
export function dateAllowed(parts:DateParts,policy:DatePolicy,today=new Date(),after=''){
 const range=interval(parts);if(!range)return false;
 const [minimum,maximum]=dateBounds(policy,today);const start=interval(dateParts(after));
 return range[1]>=minimum&&range[0]<=maximum&&(!start||range[1]>=start[0]);
}
export function sameDate(a:DateParts,b:DateParts){return !!a.y&&a.y===b.y&&a.m===b.m&&a.d===b.d;}
export function dateError(parts:DateParts,policy:DatePolicy,today=new Date(),after='',preserved=''){
 if(parts.legacy||!parts.y&&!parts.m&&!parts.d)return '';
 if(!parts.y)return 'Choose a year to finish this date.';
 if(parts.d&&!parts.m)return 'Choose a month for the selected day.';
 if(!interval(parts))return 'Choose a valid day for this month and year.';
 const range=interval(parts)!;const start=interval(dateParts(after));
 if(start&&range[1]<start[0])return 'The end date cannot be before the start date.';
 if(preserveSavedDate(policy)&&sameDate(parts,dateParts(preserved)))return '';
 return dateAllowed(parts,policy,today,after)?'':policy==='employment-start'?'Employment start must be before today.':policy==='past'?'Attendance start must be before today.':policy==='employment-end'?'Employment end must be no more than one year ahead. Past dates are allowed.':policy==='future'?'Expected graduation must be after today and within the next 10 years.':'Choose a date no more than 10 years ahead. Past dates are allowed.';
}
export function dateYears(policy:DatePolicy,today=new Date(),preserved=''){
 const y=today.getFullYear();const upcoming=Array.from({length:policy==='employment-end'?2:11},(_,i)=>y+i);const past=Array.from({length:Math.max(0,y-1900)},(_,i)=>y-i-1);
 const normal=policy==='past'||policy==='employment-start'?[y,...past]:policy==='future'?upcoming:[...upcoming,...past];
 const old=Number(dateParts(preserved).y);return {normal,saved:old&&!normal.includes(old)?old:null};
}
