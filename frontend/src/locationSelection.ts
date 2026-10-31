type LocationQuery={location?:string;locations?:string[]};
const nationwide=new Set(['united states','us','usa','nationwide','anywhere','remote','anywhere in the us']);
export function selectedLocations(query:LocationQuery):string[]{
 const values=query.locations?.length?query.locations:[query.location||''];
 return [...new Map(values.map(v=>v.trim().replace(/\s+/g,' ')).filter(Boolean).map(v=>[v.toLocaleLowerCase(),v])).values()];
}
export function locationQuery(values:string[]){
 const locations=selectedLocations({locations:values});
 return {location:locations[0]||'',locations:locations.length>1?locations:[]};
}
export function addLocation(values:string[],value:string){
 const text=value.trim().replace(/\s+/g,' '),key=text.toLocaleLowerCase();
 if(text.length<2||text.length>120)throw Error('Use 2 to 120 characters for a location.');
 if(values.some(v=>v.toLocaleLowerCase()===key))return values;
 // Nationwide is an alternative to narrower locations, rather than an OR that swallows them.
 const next=nationwide.has(key)?[]:values.filter(v=>!nationwide.has(v.toLocaleLowerCase()));
 if(next.length>=10)throw Error('Choose up to ten locations. Remove one before adding another.');
 return [...next,text];
}
