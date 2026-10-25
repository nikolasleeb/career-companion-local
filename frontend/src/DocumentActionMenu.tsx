import React,{useEffect,useId,useRef,useState} from 'react';
import {documentMenuPosition} from './documentMenuPosition';

/** Native top-layer popovers escape the dialog's scrolling and clipping boxes. */
export function DocumentActionMenu({name,disabled,children}:{name:string;disabled:boolean;children:React.ReactNode}){
 const id=useId(),trigger=useRef<HTMLButtonElement>(null),menu=useRef<HTMLDivElement>(null);
 const [open,setOpen]=useState(false);
 function items(){return Array.from(menu.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')||[]);}
 function close(restore=false){menu.current?.hidePopover();if(restore)trigger.current?.focus();}
 function position(){
  const button=trigger.current,popup=menu.current;if(!button||!popup||!popup.matches(':popover-open'))return;
  const anchor=button.getBoundingClientRect(),body=button.closest('.application-details-body')?.getBoundingClientRect();
  const bounds={left:0,right:window.innerWidth,top:Math.max(0,body?.top||0),bottom:Math.min(window.innerHeight,body?.bottom||window.innerHeight)};
  if(anchor.bottom<=bounds.top||anchor.top>=bounds.bottom){close();return;}
  popup.style.maxHeight=Math.max(40,bounds.bottom-bounds.top-16)+'px';
  const next=documentMenuPosition(anchor,popup.getBoundingClientRect(),bounds);
  popup.style.left=next.left+'px';popup.style.top=next.top+'px';
 }
 function show(last=false){
  if(disabled)return;
  const popup=menu.current;if(!popup)return;
  popup.showPopover();position();
  popup.querySelectorAll('button').forEach(button=>{button.setAttribute('role','menuitem');button.tabIndex=-1;});
  const enabled=items();(last?enabled.at(-1):enabled[0])?.focus();
 }
 useEffect(()=>{
  const popup=menu.current;if(!popup)return;
  function toggle(){setOpen(!!popup?.matches(':popover-open'));}
  function scroll(event:Event){if(!popup?.contains(event.target as Node))position();}
  popup.addEventListener('toggle',toggle);window.addEventListener('resize',position);document.addEventListener('scroll',scroll,true);
  return()=>{popup.removeEventListener('toggle',toggle);window.removeEventListener('resize',position);document.removeEventListener('scroll',scroll,true);};
 },[]);
 useEffect(()=>{if(disabled)close();},[disabled]);
 return <><button ref={trigger} type="button" className="document-menu-trigger" disabled={disabled} aria-label={'More actions for '+name} aria-haspopup="menu" aria-expanded={open} aria-controls={id}
  onClick={()=>menu.current?.matches(':popover-open')?close(true):show()}
  onKeyDown={e=>{if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();show(e.key==='ArrowUp');}}}>More <span aria-hidden="true">⌄</span></button>
 <div ref={menu} id={id} popover="auto" role="menu" className="document-action-list" aria-label={'File actions for '+name}
  onClickCapture={e=>{const button=(e.target as Element).closest('button');if(button&&!button.disabled)close(true);}}
  onKeyDown={e=>{
   const enabled=items(),index=enabled.indexOf(document.activeElement as HTMLButtonElement);
   if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close(true);}
   else if(e.key==='Tab'){close(true);}
   else if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){
    e.preventDefault();const next=e.key==='Home'?0:e.key==='End'?enabled.length-1:(index+(e.key==='ArrowDown'?1:-1)+enabled.length)%enabled.length;enabled[next]?.focus();
   }
  }}>{children}</div></>;
}
