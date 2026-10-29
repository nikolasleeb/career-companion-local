import React,{useEffect,useState} from 'react';

export function ResponseTokenSettings({value=0,disabled=false,onSave}:{value?:number;disabled?:boolean;onSave:(value:number)=>void}){
 const [automatic,setAutomatic]=useState(value===0),[draft,setDraft]=useState(String(value||64000));
 useEffect(()=>{setAutomatic(value===0);setDraft(String(value||64000));},[value]);
 const parsed=Number(draft),valid=automatic||/^\d+$/.test(draft)&&Number.isSafeInteger(parsed)&&parsed>=1&&parsed<=128000,next=automatic?0:parsed;
 return <section className="panel settings-ai-panel top-space"><h2>Response token limit</h2><p className="small muted">Set the maximum response tokens per text AI call. This includes reasoning and the final answer. Applies across AI modes, including project and document analysis.</p>
 <form onSubmit={e=>{e.preventDefault();if(valid)onSave(next);}}><label className="check-line"><input type="checkbox" checked={automatic} disabled={disabled} onChange={e=>setAutomatic(e.target.checked)}/>Use automatic response limits</label>
 {automatic?<p className="small muted">The app chooses a limit for each action. Project analysis allows 32,000 tokens, or 64,000 for larger projects or higher reasoning.</p>:<label>Maximum response tokens per AI call<input type="text" inputMode="numeric" pattern="[0-9]+" maxLength={6} value={draft} disabled={disabled} onChange={e=>setDraft(e.target.value.replace(/[^0-9]/g,''))} aria-describedby="response-token-help"/></label>}
 <p id="response-token-help" className="small muted">Choose 1–128,000 tokens. Small limits can stop a response before it finishes. Input tokens are billed separately, so this is not a dollar spending cap. Audio and image generation use separate limits; connection tests and Application Assistant keep their small budgets.</p>
 {!valid&&<p role="alert">Enter a whole number from 1 to 128,000.</p>}<button type="submit" className="button primary" disabled={disabled||!valid||next===value}>Save response limit</button><p className="small muted">Saving changes only this account’s future calls. It makes no AI request.</p></form></section>;
}
