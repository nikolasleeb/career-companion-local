import React,{useEffect,useId,useRef,useState} from 'react';
import {locationChoices} from './locationChoices';
import {addLocation} from './locationSelection';
type Props={selected:string[];history:string[];catalog:string[];onChange:(values:string[])=>void;onCommit:(value:string)=>void;disabled?:boolean};
export function LocationPicker({selected,history,catalog,onChange,onCommit,disabled=false}:Props){
 const id=useId(),root=useRef<HTMLDivElement>(null),input=useRef<HTMLInputElement>(null);
 const [text,setText]=useState(''),[open,setOpen]=useState(false),[active,setActive]=useState(-1),[error,setError]=useState('');
 const choices=locationChoices([...selected,...history],catalog,text);
 const custom=!!text.trim()&&!choices.some(v=>v.toLocaleLowerCase()===text.trim().toLocaleLowerCase());
 const options=[...(custom?[text.trim()]:[]),...choices];
 function close(){setOpen(false);setActive(-1);}
 useEffect(()=>{if(disabled)close();},[disabled]);
 function choose(value:string){
  const exists=selected.some(v=>v.toLocaleLowerCase()===value.toLocaleLowerCase());
  try{const next=exists?selected.filter(v=>v.toLocaleLowerCase()!==value.toLocaleLowerCase()):addLocation(selected,value);onChange(next);if(!exists)onCommit(value);setText('');setActive(-1);setError('');input.current?.focus();setOpen(true);}catch(e){setError((e as Error).message);}
 }
 useEffect(()=>{function outside(e:PointerEvent){if(!root.current?.contains(e.target as Node))close();}document.addEventListener('pointerdown',outside);return()=>document.removeEventListener('pointerdown',outside);},[]);
 useEffect(()=>{if(open&&active>=0)document.getElementById(id+'-'+active)?.scrollIntoView({block:'nearest'});},[active,open,id]);
 return <div className="location-picker" ref={root} onBlur={e=>{if(!e.currentTarget.contains(e.relatedTarget as Node))close();}}>
 <label htmlFor={id}>Locations</label><span id={id+'-help'} className="sr-only">Type a city, state or region and press Enter. Match any selected location, up to ten. Choosing United States replaces narrower locations.</span>
 <div className="location-picker-control"><input id={id} ref={input} value={text} disabled={disabled} maxLength={120} placeholder="Add a city, state or region" autoComplete="off" role="combobox" aria-autocomplete="list" aria-expanded={open} aria-controls={id+'-options'} aria-describedby={id+'-help'} aria-activedescendant={open&&active>=0?id+'-'+active:undefined} onFocus={()=>{setOpen(true);setActive(-1);}} onChange={e=>{setText(e.target.value);setOpen(true);setActive(-1);setError('');}} onKeyDown={e=>{if(e.nativeEvent.isComposing)return;if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();setOpen(true);setActive(v=>e.key==='ArrowDown'?Math.min(v+1,options.length-1):Math.max(0,v-1));}else if(e.key==='Escape'){e.preventDefault();close();}else if(e.key==='Enter'){e.preventDefault();if(open&&active>=0&&options[active])choose(options[active]);else if(text.trim())choose(text);else setOpen(v=>!v);}}}/><button type="button" className="location-picker-toggle" disabled={disabled} aria-label="Browse locations" aria-expanded={open} aria-controls={id+'-options'} onMouseDown={e=>e.preventDefault()} onClick={()=>{if(open)close();else{input.current?.focus();setActive(-1);setOpen(true);}}}><span className="search-control-chevron" aria-hidden="true"/></button>
 {open&&<div className="location-picker-options" id={id+'-options'} role="listbox" aria-label="Saved and suggested locations" aria-multiselectable="true">{options.map((v,i)=>{const checked=selected.some(s=>s.toLocaleLowerCase()===v.toLocaleLowerCase());return <button key={v.toLocaleLowerCase()} id={id+'-'+i} type="button" role="option" aria-selected={checked} tabIndex={-1} disabled={disabled} className={i===active?'active':''} onMouseDown={e=>e.preventDefault()} onClick={()=>choose(v)}><span><span aria-hidden="true">{checked?'✓ ':'＋ '}</span>{custom&&i===0?'Add “'+v+'”':v}</span>{history.some(h=>h.toLocaleLowerCase()===v.toLocaleLowerCase())&&!checked&&<small>Previously used</small>}</button>;})}</div>}
 </div>
 <div className="role-chips" aria-label="Selected locations">{selected.map(value=><span className="role-chip" key={value.toLocaleLowerCase()}>{value}<button type="button" disabled={disabled} aria-label={'Remove location '+value} onClick={()=>{onChange(selected.filter(v=>v!==value));setError('');}}>×</button></span>)}</div>
 <p className="small muted location-selection-help">Match any selected location · up to 10</p>
 {error&&<p className="field-error" role="alert">{error}</p>}
 </div>;
}
