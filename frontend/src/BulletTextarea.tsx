import React,{useEffect,useId,useRef,useState} from 'react';
import {BulletEdit,bulletDefault,bulletFormat,bulletSelection,bulletEnter,bulletBackspace,bulletInsert,editValue} from './bulletEditing';
import './bulletTextarea.css';
export function BulletTextarea({label,noun,value,onChange,maxLength,rows=3,placeholder=''}:{label:string;noun:'responsibility'|'accomplishment';value:string;onChange:(value:string)=>void;maxLength:number;rows?:number;placeholder?:string}){
 const uid=useId(),input=useRef<HTMLTextAreaElement>(null),[enabled,setEnabled]=useState(()=>bulletDefault(value)),[error,setError]=useState(''),composing=useRef(false),changing=useRef(false),last=useRef(value),mode=useRef(enabled),compositionStart=useRef<number|null>(null);
 mode.current=enabled;
 useEffect(()=>{if(value!==last.current){last.current=value;setEnabled(bulletDefault(value));setError('');}},[value]);
 const emit=(text:string)=>{last.current=text;onChange(text);setError('');};
 function apply(edit:BulletEdit){
  const el=input.current;if(!el)return false;const next=editValue(el.value,edit);
  if(next.length>maxLength){setError('This edit would exceed the '+maxLength.toLocaleString()+' character limit. Your text is unchanged.');return false;}
  if(next===el.value){if(edit.exit)setEnabled(false);return true;}
  el.focus();const scroll=el.scrollTop;el.setSelectionRange(edit.start,edit.end);changing.current=true;
  // Native text transactions preserve the browser's undo history, including list operations.
  const ok=document.execCommand(edit.text?'insertText':'delete',false,edit.text);
  if(!ok||el.value!==next){el.setRangeText(edit.text,edit.start,edit.end,'end');emit(el.value);}
  changing.current=false;el.setSelectionRange(edit.start+edit.text.length,edit.start+edit.text.length);el.scrollTop=scroll;
  if(edit.exit)setEnabled(false);
  return true;
 }
 useEffect(()=>{
  const el=input.current;if(!el)return;
  const before=(e:InputEvent)=>{
   if(changing.current||composing.current||e.isComposing||!mode.current||!e.cancelable||e.inputType!=='insertText'||!e.data)return;
   const edit=bulletInsert(el.value,el.selectionStart,el.selectionEnd,e.data);
   if(edit.text!==e.data||editValue(el.value,edit).length>maxLength){e.preventDefault();apply(edit);}
  };
  el.addEventListener('beforeinput',before);return()=>el.removeEventListener('beforeinput',before);
 });
 return <div className="bullet-editor"><div className="bullet-editor-heading"><label id={uid+'-label'} htmlFor={uid}>{label}</label><span id={uid+'-hint'} className="small muted">Bullet points preferred—one {noun} per bullet</span><button type="button" className="text-button bullet-toggle" aria-label={'Bullets for '+label} aria-pressed={enabled} onMouseDown={e=>e.preventDefault()} onClick={()=>{const el=input.current;if(!el)return;const next=!enabled,selection=bulletSelection(el.value,next,el.selectionStart,el.selectionEnd),direction=el.selectionDirection;if(apply({start:0,end:el.value.length,text:bulletFormat(el.value,next)})){setEnabled(next);el.setSelectionRange(selection.start,selection.end,direction);}}}>Bullets</button></div>
 <textarea ref={input} id={uid} aria-labelledby={uid+'-label'} aria-describedby={uid+'-hint '+uid+'-keys'+(error?' '+uid+'-error':'')} rows={rows} maxLength={maxLength} value={value} placeholder={placeholder} onChange={e=>{emit(e.target.value);if(['historyUndo','historyRedo'].includes((e.nativeEvent as InputEvent).inputType))setEnabled(bulletDefault(e.target.value));}} onKeyDown={e=>{
  if(!enabled||composing.current||e.nativeEvent.isComposing||e.keyCode===229||e.ctrlKey||e.metaKey||e.altKey)return;
  const el=e.currentTarget;if(e.key==='Enter'){e.preventDefault();apply(bulletEnter(el.value,el.selectionStart,el.selectionEnd,e.shiftKey));}
  else if(e.key==='Backspace'){const edit=bulletBackspace(el.value,el.selectionStart,el.selectionEnd);if(edit){e.preventDefault();apply(edit);}}
 }} onPaste={e=>{if(!enabled||composing.current)return;const text=e.clipboardData.getData('text/plain');if(!text)return;const el=e.currentTarget;e.preventDefault();apply(bulletInsert(el.value,el.selectionStart,el.selectionEnd,text));}} onCompositionStart={e=>{composing.current=true;const el=e.currentTarget;compositionStart.current=!el.value.slice(el.value.lastIndexOf('\n',el.selectionStart-1)+1).trim()?el.selectionStart:null;}} onCompositionEnd={()=>{
  composing.current=false;const start=compositionStart.current;compositionStart.current=null;
  queueMicrotask(()=>{const el=input.current;if(!el||!mode.current||start===null)return;const line=el.value.slice(start).split('\n')[0];if(line.trim()){const edit=bulletInsert(el.value,start,start+line.length,line);if(edit.text!==line)apply(edit);}});
 }}/>
 <p id={uid+'-keys'} className="small muted bullet-keys">{enabled?'Enter adds a bullet. Shift+Enter continues the same bullet. Enter on an empty bullet ends the list.':'Paragraphs are welcome. Turn on Bullets to format each existing line as a bullet.'}</p>{error&&<p id={uid+'-error'} className="small inline-error" role="alert">{error}</p>}</div>;
}
