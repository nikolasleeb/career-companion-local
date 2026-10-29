export type EducationPath='yes'|'no'|'skip';
export const statementFieldNames=['graduation','degree','completed_degree','future_education','field','focus','skills','certifications','timing','commitments','priorities','reason','other'] as const;
export type StatementFields=Record<typeof statementFieldNames[number],string>;
export type StatementEditor={version:1;mode:'guided'|'direct';education:EducationPath;fields:StatementFields};
export const emptyStatementEditor=():StatementEditor=>({version:1,mode:'guided',education:'skip',fields:Object.fromEntries(statementFieldNames.map(k=>[k,''])) as StatementFields});
export function omission(value:string){return value.trim()==='[blank]'?'':value.trim();}
export function statementText(value:string){return value.replace(/\[blank\]/g,'').replace(/[ \t]+/g,' ').replace(/ *\n */g,'\n').trim();}
export function meaningfulStatement(value:string){return /[\p{L}\p{N}]/u.test(statementText(value));}
export function buildStatement(editor:StatementEditor){
 const f=Object.fromEntries(statementFieldNames.map(k=>{const text=omission(editor.fields[k]).replace(/[.!?]+$/,'');return [k,meaningfulStatement(text)?text:''];})) as StatementFields;
 const sentences:string[]=[];const add=(s:string)=>{if(s)sentences.push(s.replace(/[.!?]+$/,'')+'.');};
 if(editor.education==='yes'){
  if(f.degree)add(`I aim to graduate${f.graduation?' in '+f.graduation:''} with a degree in ${f.degree}`);
  else if(f.graduation)add(`I aim to graduate in ${f.graduation}`);
 }else if(editor.education==='no'){
  if(f.completed_degree)add(`I have completed ${f.completed_degree}`);
  if(f.future_education)add(`My future education plans include ${f.future_education}`);
 }
 if(f.field)add(`I would like to work in ${f.field}${f.focus?', focusing on '+f.focus:''}`);
 else if(f.focus)add(`I would like my work to focus on ${f.focus}`);
 if(f.skills)add(`I want to develop ${f.skills}${/\bskills$/i.test(f.skills)?'':' skills'}`);
 if(f.certifications)add(`I want to earn ${f.certifications}${/\b(certifications?|credentials?)$/i.test(f.certifications)?'':' certifications'}`);
 if(f.timing)add(`My target timeframe is ${f.timing}`);
 if(f.commitments)add(`Alongside this, I am ${f.commitments}`);
 if(f.priorities)add(`What matters to me is ${f.priorities}${f.reason?' because '+f.reason:''}`);
 else if(f.reason)add(`I am motivated by ${f.reason}`);
 if(f.other)add(f.other);
 return sentences.join(' ');
}
export function cleanEditor(editor:StatementEditor):StatementEditor{
 return {...editor,fields:Object.fromEntries(statementFieldNames.map(k=>[k,omission(editor.fields[k])])) as StatementFields};
}
