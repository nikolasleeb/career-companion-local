import React,{useEffect,useRef,useState} from 'react';

export function ResumePreview({revision,pages,previous=false}:{revision:string;pages:number;previous?:boolean}){
 const viewport=useRef<HTMLDivElement>(null);
 const [zoom,setZoom]=useState<'page'|'width'|number>('page');
 const [space,setSpace]=useState({width:816,height:600});
 useEffect(()=>{
  const element=viewport.current;if(!element)return;
  const measure=()=>setSpace({width:element.clientWidth,height:Math.min(window.innerHeight*.76,1100)});
  const observer=new ResizeObserver(measure);observer.observe(element);window.addEventListener('resize',measure);measure();
  return()=>{observer.disconnect();window.removeEventListener('resize',measure);};
 },[]);
 const available=Math.max(160,space.width-32),paperWidth=816;
 const width=zoom==='page'?Math.min(available,Math.max(160,space.height-36)*8.5/11,paperWidth):zoom==='width'?available:paperWidth*zoom/100;
 const percent=Math.round(width/paperWidth*100);
 const adjust=(step:number)=>setZoom(Math.max(25,Math.min(200,Math.round(percent/10)*10+step)));
 return <div className="resume-preview-viewer">
  <div className="preview-zoom-controls" role="group" aria-label="Resume preview zoom">
   <button type="button" className="button secondary" aria-label="Zoom out resume preview" disabled={percent<=25} onClick={()=>adjust(-10)}>−</button>
   <output aria-live="polite" aria-label="Preview zoom">{percent}%</output>
   <button type="button" className="button secondary" aria-label="Zoom in resume preview" disabled={percent>=200} onClick={()=>adjust(10)}>+</button>
   <button type="button" className="button secondary" aria-pressed={zoom==='page'} onClick={()=>setZoom('page')}>Fit page</button>
   <button type="button" className="button secondary" aria-pressed={zoom==='width'} onClick={()=>setZoom('width')}>Fit width</button>
   <button type="button" className="button secondary" aria-pressed={zoom===100} onClick={()=>setZoom(100)}>100%</button>
   <span className="small muted">Preview only · PDF size stays the same</span>
  </div>
  <div className="resume-preview-viewport" ref={viewport} tabIndex={0} role="region" aria-label="Resume PDF preview. Scroll to view zoomed pages.">
   <div className="resume-preview-pages" style={{width}}>{Array.from({length:pages},(_,i)=><img className={'pdf-preview '+(previous?'preview-previous':'')} alt={'Working resume PDF, page '+(i+1)} src={'/api/resume-revisions/'+revision+'/pages/'+(i+1)} key={revision+':'+i}/>)}</div>
  </div>
 </div>;
}
