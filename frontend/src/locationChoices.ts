export function locationChoices(history:string[],catalog:string[],text:string){
 const seen=new Set<string>(),q=text.trim().toLocaleLowerCase();
 return [...history,...catalog].map(v=>v.trim().replace(/\s+/g,' ')).filter(v=>{const k=v.toLocaleLowerCase();if(!v||seen.has(k))return false;seen.add(k);return !q||k.includes(q);});
}
export function groupLocationChoices(choices:string[],catalog:Record<string,string[]>){
 const remaining=new Map(choices.map(v=>[v.toLocaleLowerCase(),v])),groups:{name:string;values:string[]}[]=[];
 for(const [name,items] of Object.entries(catalog)){
  const keys=new Set(items.map(v=>v.toLocaleLowerCase())),values=choices.filter(v=>keys.has(v.toLocaleLowerCase()));
  for(const value of values)remaining.delete(value.toLocaleLowerCase());
  if(values.length)groups.push({name,values});
 }
 if(remaining.size)groups.push({name:'Your locations',values:[...remaining.values()]});
 return groups;
}
