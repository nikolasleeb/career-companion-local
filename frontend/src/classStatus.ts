// A save invalidates all outstanding reads; only the latest read may publish.
export function classReadGuard(){let generation=0;return {start:()=>++generation,current:(token:number)=>token===generation,invalidate:()=>{generation++;}};}
