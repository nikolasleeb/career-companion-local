import React,{useState} from 'react';
/** Controlled wording selection. Selection never approves or sends a request. */
export function EvidenceWordingChoice({value,original,suggested,disabled,onChange}:{value:string;original:string;suggested?:string;disabled:boolean;onChange:(text:string)=>void}){
 const [last,setLast]=useState<'polished'|'original'>('polished');
 const polished=!!suggested&&value===suggested&&(value!==original||last==='polished');
 const raw=value===original&&(!polished||last==='original');
 return <div className="evidence-wording-choice"><div className="card-actions">{suggested&&<button type="button" className="button secondary" aria-pressed={polished} disabled={disabled} onClick={()=>{setLast('polished');onChange(suggested);}}>{polished?'Polished wording selected ✓':'Use polished suggestion'}</button>}<button type="button" className="button secondary" aria-pressed={raw} disabled={disabled} onClick={()=>{setLast('original');onChange(original);}}>{raw?'Original excerpt selected ✓':'Use original excerpt'}</button></div><p className="small muted" role="status">{polished?'Polished wording selected.':raw?'Original excerpt selected.':'Your edited wording is selected.'} Review the text above, then approve when ready.</p></div>;
}
