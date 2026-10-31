import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import type {KeyboardEvent,PointerEvent} from 'react';
import {clampCoachWidth,coachPanelLimits,DEFAULT_COACH_WIDTH,MIN_COACH_WIDTH} from './coachPanelSize';

// Only presentation preferences are stored here; conversation state stays in its existing stores.
export function useCoachPanel(accountId:string,open:boolean,suspended:boolean){
 const key='career-coach-width:'+accountId;
 const [preferred,setPreferred]=useState(()=>{try{const n=Number(localStorage.getItem(key));return n>=360&&n<=800?n:DEFAULT_COACH_WIDTH;}catch{return DEFAULT_COACH_WIDTH;}});
 const [expanded,setExpanded]=useState(false),[viewport,setViewport]=useState({width:window.innerWidth,sidebar:244});
 const drag=useRef<{x:number;width:number;preferred:number}|null>(null);
 const limits=coachPanelLimits(viewport.width,viewport.sidebar),width=expanded?limits.expanded:clampCoachWidth(preferred,limits.maximum);
 const current=useRef({preferred,width,maximum:limits.maximum});current.current={preferred,width,maximum:limits.maximum};
 function persist(value:number){try{localStorage.setItem(key,String(value));}catch{}}
 useLayoutEffect(()=>{const measure=()=>setViewport({width:window.innerWidth,sidebar:document.querySelector('.sidebar')?.getBoundingClientRect().width||244});measure();window.addEventListener('resize',measure);const sidebar=document.querySelector('.sidebar'),observer=new ResizeObserver(measure);if(sidebar)observer.observe(sidebar);return()=>{window.removeEventListener('resize',measure);observer.disconnect();};},[]);
 useEffect(()=>{if(!open)setExpanded(false);},[open]);
 useEffect(()=>{if(suspended){drag.current=null;document.body.classList.remove('coach-panel-resizing');}},[suspended]);
 useLayoutEffect(()=>{
  document.body.style.setProperty('--career-coach-width',width+'px');
  document.body.classList.toggle('career-coach-expanded',open&&expanded);
  document.body.classList.toggle('career-coach-task-narrow',open&&!expanded&&viewport.width-viewport.sidebar-width<800);
  return()=>{document.body.style.removeProperty('--career-coach-width');document.body.classList.remove('career-coach-expanded','career-coach-task-narrow');};
 },[width,expanded,open,viewport]);
 useEffect(()=>()=>document.body.classList.remove('coach-panel-resizing'),[]);
 function finish(){if(drag.current){persist(current.current.preferred);drag.current=null;}document.body.classList.remove('coach-panel-resizing');}
 return {width,maximum:limits.maximum,expanded,setExpanded,handle:{
  onPointerDown(e:PointerEvent<HTMLDivElement>){if(suspended||e.button!==0)return;e.preventDefault();e.currentTarget.focus();e.currentTarget.setPointerCapture(e.pointerId);drag.current={x:e.clientX,width,preferred};document.body.classList.add('coach-panel-resizing');},
  onPointerMove(e:PointerEvent<HTMLDivElement>){if(!drag.current||suspended)return;const value=clampCoachWidth(drag.current.width+drag.current.x-e.clientX,current.current.maximum);current.current.preferred=value;setPreferred(value);},
  onPointerUp:finish,onPointerCancel:finish,onLostPointerCapture:finish,
  onKeyDown(e:KeyboardEvent<HTMLDivElement>){if(suspended)return;let next:number|undefined;
   if(e.key==='ArrowLeft')next=width+(e.shiftKey?40:20);if(e.key==='ArrowRight')next=width-(e.shiftKey?40:20);
   if(e.key==='Home')next=MIN_COACH_WIDTH;if(e.key==='End')next=limits.maximum;
   if(e.key==='Escape'&&drag.current){e.preventDefault();e.stopPropagation();setPreferred(drag.current.preferred);drag.current=null;document.body.classList.remove('coach-panel-resizing');return;}
   if(next!==undefined){e.preventDefault();const value=clampCoachWidth(next,limits.maximum);setPreferred(value);persist(value);}
  }
 }};
}
