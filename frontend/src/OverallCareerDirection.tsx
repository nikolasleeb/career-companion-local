import React,{useRef,useState} from 'react';
import {buildStatement,cleanEditor,emptyStatementEditor,meaningfulStatement,statementText,StatementEditor,StatementFields} from './goalStatement';

export function OverallCareerDirection({goal,disabled,onSave,onDelete}:{goal:any;disabled:boolean;onSave:(value:any)=>Promise<boolean>;onDelete:()=>void}){
 const [open,setOpen]=useState(false),[editor,setEditor]=useState<StatementEditor>(emptyStatementEditor),[direct,setDirect]=useState(''),[baseId,setBaseId]=useState(''),[error,setError]=useState('');
 const heading=useRef<HTMLHeadingElement>(null),text=useRef<HTMLTextAreaElement>(null);
 const generated=buildStatement(editor),value=editor.mode==='direct'?direct:generated;
 function start(){setEditor({...emptyStatementEditor(),...goal?.guided_editor,mode:goal?'direct':'guided'});setDirect(goal?.text||'');setBaseId(goal?.id||'');setError('');setOpen(true);requestAnimationFrame(()=>heading.current?.focus());}
 function field(name:keyof StatementFields,label:string,placeholder=''){
  return <label key={name}>{label}<input maxLength={name==='other'?3000:1000} value={editor.fields[name]} placeholder={placeholder} onChange={e=>setEditor(v=>({...v,fields:{...v.fields,[name]:e.target.value}}))}/></label>;
 }
 return <section className="overall-career-direction goal-section" aria-labelledby="overall-direction-title">
  <h3 id="overall-direction-title">Overall career direction <span className="goal-section-tag">One statement</span></h3>
  <p>Bring your plans together in one overall statement. You can save one and update it as your direction changes. Use specific goals below for individual milestones you want to track.</p>
  {goal?<div className="saved-profile-summary"><p className="preserve">{goal.text}</p>{goal.occupation&&<p className="small muted">Linked occupation: {goal.occupation.title}</p>}<div className="card-actions"><button type="button" className="button secondary" disabled={disabled||open} onClick={start}>Edit overall career direction</button><button type="button" className="button secondary" disabled={disabled||open} onClick={onDelete}>Delete overall career direction</button></div></div>:!open&&<><p className="small muted">No overall statement saved. It is optional; you can use specific goals on their own.</p><button type="button" className="button secondary" disabled={disabled} onClick={start}>Create overall career direction</button></>}
  {open&&<form className="single-goal-form direction-editor" onSubmit={async e=>{
   e.preventDefault();setError('');if(!meaningfulStatement(value))return;
   if((goal?.id||'')!==baseId){setError('Your saved statement changed in another window. Cancel and reopen this editor to review it. Your draft is preserved.');return;}
   if(await onSave({...goal,id:baseId||crypto.randomUUID(),category:'general_statement',text:statementText(value),target:'',priority:'medium',progress:'planned',guided_editor:cleanEditor(editor)}))setOpen(false);
  }}><fieldset disabled={disabled}><legend>{baseId?'Edit your overall statement':'Create your overall statement'}</legend>
   <h4 ref={heading} tabIndex={-1}>Your statement editor</h4>
   <p className="small muted">Every field is optional. Leave it empty or enter exactly [blank] to omit it. This changes your goals only, never verified Profile education. Previewing and saving use no AI.</p>
   {editor.mode==='guided'?<>
    <label>Are you currently pursuing a degree?<select value={editor.education} onChange={e=>setEditor(v=>({...v,education:e.target.value as StatementEditor['education']}))}><option value="skip">Skip education</option><option value="yes">Yes</option><option value="no">No</option></select></label>
    <div className="direction-fields">
     {editor.education==='yes'&&<>{field('graduation','Graduation year or date (optional)','May 2027')}{field('degree','Degree you are pursuing (optional)','Data Science (MS)')}</>}
     {editor.education==='no'&&<>{field('completed_degree','Completed degree (optional)','a BS in Computer Science')}{field('future_education','Future education plans (optional)','a part-time graduate degree')}</>}
     {field('field','Desired field or type of work (optional)','data engineering or cloud infrastructure')}
     {field('focus','Work you want to focus on (optional)','reliable data pipelines')}
     {field('skills','Skills you want to develop (optional)','Python, SQL and distributed systems')}
     {field('certifications','Certifications you want to earn (optional)','AWS Certified Data Engineer – Associate')}
     {field('timing',editor.education==='yes'?'Timing relative to graduation (optional)':'Target timeframe (optional)',editor.education==='yes'?'before graduation':'over the next year')}
     {field('commitments','Current commitments (optional)','working part-time while studying')}
     {field('priorities','What matters to you (optional)','useful work and continued learning')}
     {field('reason','Why it matters (optional)','I enjoy solving practical problems')}
    </div>
    <label>Other context (optional)<textarea rows={3} maxLength={3000} value={editor.fields.other} onChange={e=>setEditor(v=>({...v,fields:{...v.fields,other:e.target.value}}))}/></label>
    <h4>Live statement preview</h4><p className="direction-preview preserve" aria-live="polite" aria-atomic="true">{generated||'Complete any part above to preview your statement.'}</p>
    <button type="button" className="button secondary" onClick={()=>{setDirect(generated);setEditor(v=>({...v,mode:'direct'}));requestAnimationFrame(()=>text.current?.focus());}}>Edit statement directly</button>
   </>:<>
    <label>Overall career direction<textarea ref={text} rows={7} maxLength={36000} value={direct} onChange={e=>setDirect(e.target.value)}/></label>
    <p className="small muted">Your wording is used exactly as reviewed, with [blank] markers removed. Guided fields will not overwrite it.</p>
    <button type="button" className="button secondary" onClick={()=>{if(window.confirm('Replace your current draft wording with a statement rebuilt from guided fields? Your saved statement stays unchanged until you save.'))setEditor(v=>({...v,mode:'guided'}));}}>Rebuild from guided fields</button>
   </>}
   <div className="card-actions"><button className="button primary" disabled={!meaningfulStatement(value)||statementText(value).length>36000}>{disabled?'Saving…':'Save overall career direction'}</button><button type="button" className="button secondary" onClick={()=>{setOpen(false);setError('');}}>Cancel</button></div>
   <p className="small muted">Saving replaces your one overall statement. Your specific goals and AI guidance choice stay unchanged.</p>
   {error&&<p role="alert">{error}</p>}
  </fieldset></form>}
 </section>;
}
