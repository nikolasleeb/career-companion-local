export type Certification={name:string;issuer:string;earned_date:string;valid_from:string;expiration_date:string;does_not_expire:boolean;credential_id:string;credential_url:string;document_id:string};
export const blankCertification=():Certification=>({name:'',issuer:'',earned_date:'',valid_from:'',expiration_date:'',does_not_expire:false,credential_id:'',credential_url:'',document_id:''});
export function isCertification(data:Record<string,any>){return data.category==='skills'&&(!!data.certification_items?.length||/certific|licen[cs]e/i.test(data.title||''));}
export function certificationRows(data:Record<string,any>):Certification[]{
 if(data.certification_items?.length)return data.certification_items.map((v:any)=>({...blankCertification(),...v}));
 const names=data.skill_items?.length?data.skill_items.map((v:any)=>v.name):(data.tools||data.description||'').split(/[,;\n]+/);
 return names.filter((v:string)=>v.trim()).map((name:string)=>({...blankCertification(),name:name.trim()}));
}
export function certificationDetails(row:Certification){return [row.issuer,row.earned_date&&'Earned '+row.earned_date,row.valid_from&&'Valid from '+row.valid_from,row.expiration_date&&'Expires '+row.expiration_date,row.does_not_expire&&'Does not expire',row.credential_id&&'Credential ID: '+row.credential_id].filter(Boolean).join(' · ');}
export function certificationPayload(data:Record<string,any>){return {...data,skill_items:[],tools:'',certification_items:certificationRows(data).filter(v=>v.name.trim()).map(v=>({...v,name:v.name.trim(),expiration_date:v.does_not_expire?'':v.expiration_date}))};}
export const certificateFieldLabels:Record<string,string>={name:'Certification name',issuer:'Issuing organization',earned_date:'Date earned',valid_from:'Valid from',expiration_date:'Expiration date',does_not_expire:'Does not expire',credential_id:'Credential ID',credential_url:'Credential link'};
export type CertificateExtraction={document_id:string;sha256:string;fields:Record<string,{value:string|boolean;excerpt:string;page:number;reason:string}>;warnings:string[]};
export function fillCertificate(row:Certification,result:CertificateExtraction){
 const next={...row},filled:string[]=[],conflicts:string[]=[];
 if(row.document_id!==result.document_id)return {row:next,filled,conflicts};
 for(const [key,field] of Object.entries(result.fields)){
  if(!(key in certificateFieldLabels))continue;
  const value=field.value,old=next[key as keyof Certification];
  if(old===value)continue;
  const invalidDate=(key==='earned_date'||key==='valid_from')&&!!next.expiration_date&&String(value)>next.expiration_date||key==='expiration_date'&&(next.does_not_expire||String(value)<[next.earned_date,next.valid_from].sort().at(-1)!);
  if(old||invalidDate||key==='does_not_expire'&&next.expiration_date){conflicts.push(key);continue;}
  (next as any)[key]=value;filled.push(key);
 }
 return {row:next,filled,conflicts};
}

export function certificateDraftPatch(data:Record<string,any>,change:Certification[]|((rows:Certification[])=>Certification[])){
 const before=certificationRows(data),next=typeof change==='function'?change(before):change;
 return {certification_items:next,confirmed:JSON.stringify(before)===JSON.stringify(next)?data.confirmed:false,skill_items:[],tools:''};
}
export function supportsCertificateExtraction(mime:string){return ['application/pdf','image/png','image/jpeg'].includes(mime);}
