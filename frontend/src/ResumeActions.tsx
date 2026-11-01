import React,{useEffect,useState} from 'react';
import {ApplicationDocuments,UploadedResumeReview} from './ApplicationDocuments';
export type GeneratedResumeActions={present:boolean;blocked:boolean;reason:string;proceed:()=>Promise<void>;download:(format:string)=>Promise<void>};
export function ResumeActions({application,workspace,generated,disabled,call,refresh,advance,onBusy}:{application:any;workspace:any;generated:GeneratedResumeActions|null;disabled:boolean;call:(path:string,method?:string,body?:any)=>Promise<any>;refresh:()=>Promise<void>;advance:(selection:any)=>Promise<void>;onBusy:(value:boolean)=>void}){
 const [working,setWorking]=useState(false),[editing,setEditing]=useState(false),[error,setError]=useState(''),[formats,setFormats]=useState(false);
 const selected=application?.data.workflow?.resume_id||'';
 const [source,setSource]=useState(selected||'draft');
 useEffect(()=>{if(selected)setSource(selected);},[selected]);
 const resumes=workspace.resume.filter((r:any)=>application?.data.resume_ids?.includes(r.id)&&r.data.job_id===application?.data.job_id);
 const resume=resumes.find((r:any)=>r.id===source),draft=source==='draft'&&generated?.present;
 const blocked=disabled||working||editing;
 const reason=draft?generated!.reason:resume?.data.origin==='uploaded'&&!resume.data.source_reviewed?'Review the uploaded resume text before proceeding.':source!=='draft'&&!resume?'The selected resume is unavailable. Choose a source explicitly.':'';
 async function act(fn:()=>Promise<void>){if(blocked)return;setWorking(true);onBusy(true);setError('');try{await fn();}catch(e){setError((e as Error).message);}finally{setWorking(false);onBusy(false);}}
 const controls=(open:()=>void)=><div className="resume-primary-actions"><button type="button" className="button secondary" disabled={blocked} onClick={open}>Upload a resume</button><div className="resume-download"><button type="button" className="button secondary" aria-expanded={formats} disabled={blocked||!generated?.present||generated.blocked} onClick={()=>setFormats(v=>!v)}>Download optimized resume</button>{formats&&<div className="card-actions" aria-label="Optimized resume download formats">{['pdf','docx','txt'].map(format=><button type="button" key={format} className="button secondary" disabled={blocked||generated?.blocked} onClick={()=>void act(()=>generated!.download(format))}>{format==='docx'?'Word':format.toUpperCase()}</button>)}</div>}</div></div>;
 return <section className="panel resume-action-group" aria-labelledby="resume-actions-title"><h2 id="resume-actions-title">Resume actions</h2>
 {application?<ApplicationDocuments application={application} documents={workspace.document} resumes={workspace.resume} analyses={workspace.analysis} call={call} onChange={refresh} resumeOnly uploadedOnly compactUpload disabled={blocked} onBusy={value=>{setWorking(value);onBusy(value);}} onFileEdit={setEditing} onSelectResume={r=>setSource(r.id)} uploadControl={controls}/>:controls(()=>setError('The application is still loading. Try again when it is ready.'))}
 {resumes.length>0&&<label>Resume for the next step<select value={source} disabled={blocked} onChange={e=>setSource(e.target.value)}><option value="draft">{generated?.present?'Current optimized draft':'Continue using Profile without a resume'}</option>{resumes.map((r:any)=><option value={r.id} key={r.id}>{r.data.title} · {r.data.origin==='uploaded'?'uploaded':'saved'}</option>)}</select></label>}
 {resume?.data.origin==='uploaded'&&!resume.data.source_reviewed&&application&&<UploadedResumeReview key={resume.id} resume={resume} application={application} call={call} onReviewed={refresh}/>}
 {!generated?.present&&<p className="small muted">Create and review an optimized resume to download it.</p>}
 {generated?.present&&generated.blocked&&source!=='draft'&&<p className="small muted">Optimized download: {generated.reason}</p>}
 <p className="small" role="status">{reason||(!draft&&!resume?'Proceed saves this application and opens Cover Letter using your confirmed Profile and this posting.':`Selected: ${draft?'current optimized draft':resume?.data.title}.`)}</p>
 {error&&<p role="alert">{error}</p>}
 <button type="button" className="button primary resume-proceed" disabled={blocked||!!reason||!!draft&&generated!.blocked||!generated} onClick={()=>void act(async()=>{if(draft)await generated!.proceed();else await advance({resume_id:resume?.id||'',cover_source:resume?'resume':'profile',cover_letter_id:'',cover_skipped:false});})}>{working?'Saving…':'Proceed to Cover Letter'}</button>
 </section>;
}
