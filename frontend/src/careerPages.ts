/** Keep nearby page buttons plus the first/last; the selector reaches every page. */
export function careerPages(total:number,current:number):(number|'gap')[]{
 const pages=Math.max(1,Math.floor(total)),at=Math.max(1,Math.min(pages,Math.floor(current)));
 if(pages<=9)return Array.from({length:pages},(_,i)=>i+1);
 const chosen=new Set([1,pages]);for(let page=Math.max(2,at-2);page<=Math.min(pages-1,at+2);page++)chosen.add(page);
 const result:(number|'gap')[]=[];for(const page of [...chosen].sort((a,b)=>a-b)){const previous=result.at(-1);if(typeof previous==='number'&&page-previous>1)result.push('gap');result.push(page);}return result;
}
