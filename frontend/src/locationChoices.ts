export function locationChoices(history:string[],catalog:string[],text:string){
 const seen=new Set<string>(),q=text.trim().toLocaleLowerCase();
 return [...history,...catalog].map(v=>v.trim().replace(/\s+/g,' ')).filter(v=>{const k=v.toLocaleLowerCase();if(!v||seen.has(k))return false;seen.add(k);return !q||k.includes(q);});
}
