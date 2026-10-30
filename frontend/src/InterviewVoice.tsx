import {useAppRoute} from './appRoute';
import React,{forwardRef,useEffect,useImperativeHandle,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {transcriptState} from './interviewTranscript';
import {useGlobalInterviewProgress} from './InterviewStatus';
import {pollTask} from './apiClient';
import {recordingWav,audioActionKey} from './interviewAudioData';
export type InterviewVoiceState={row:any;ready:boolean;hasRecordingBuffer:boolean};
export type InterviewVoiceHandle={confirmForReview:()=>Promise<string>};
type Props={account:string;session:string;question:string;call:any;available:boolean;blocked:boolean;onFormat:(value:string)=>void;onBusy:(value:boolean)=>void;format:string;statusHost:HTMLElement|null;onRecording:(value:boolean)=>void;onReady:()=>void;onState:(value:InterviewVoiceState)=>void};
export {DeliveryFeedback} from './InterviewDelivery';
export const InterviewVoice=forwardRef<InterviewVoiceHandle,Props>(function InterviewVoice({account,session,question,call,available,blocked,onFormat,onBusy,format,statusHost,onRecording,onReady,onState},ref){
 const key=audioActionKey(account,session,question);
 const [recording,setRecording]=useState(false),[seconds,setSeconds]=useState(0),[level,setLevel]=useState(0),[blob,setBlob]=useState<Blob|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[row,setRow]=useState<any>(null),[text,setText]=useState(''),[reviewed,setReviewed]=useState(false),[revision,setRevision]=useState(''),[playback,setPlayback]=useState(''),[pending,setPending]=useState<any>(()=>{try{return JSON.parse(localStorage.getItem(key)||'null');}catch{return null;}});
 const capture=useRef<any>(null),alive=useRef(true),playRef=useRef('');const locked=blocked||busy||!!pending;
 const navRoute=useAppRoute(),globalProgress=useGlobalInterviewProgress();
 const transcriptKey=(id:string)=>'interview-transcript:'+account+':'+id;
 const stale=!!row&&revision!==row.updated_at;
 const ready=!!row&&!!row.data.transcript?.trim()&&!!text.trim()&&reviewed&&!stale&&!busy&&!pending&&!recording&&!blob;
 useEffect(()=>onState({row,ready,hasRecordingBuffer:!!blob||!!pending}),[row,ready,blob,pending]);
 useImperativeHandle(ref,()=>({confirmForReview:async()=>{
  if(!ready)throw Error('Check and confirm the transcript before reviewing your spoken answer.');
  if(row.data.reviewed_at&&row.data.reviewed_transcript===text)return row.id;
  setBusy(true);onBusy(true);setError('');
  try{const value=await call('/interview-practice/voice/'+row.id+'/transcript','PUT',{expected_updated_at:revision,transcript:text,reviewed:true});sessionStorage.removeItem(transcriptKey(row.id));loadRow(value);return value.id;}catch(error){setError((error as Error).message);throw error;}finally{setBusy(false);onBusy(false);}
 }}),[ready,row,text,revision]);
 useEffect(()=>{if(navRoute.view!=='interviews'){if(capture.current){stop(true);setError('Recording stopped and discarded when you left Interview Practice.');}setBlob(null);if(playRef.current){URL.revokeObjectURL(playRef.current);playRef.current='';}}},[navRoute.view]);
 useEffect(()=>{onRecording(recording);},[recording]);
 function release(){const c=capture.current;if(!c)return;capture.current=null;c.stream.getTracks().forEach((t:MediaStreamTrack)=>t.stop());cancelAnimationFrame(c.frame);clearInterval(c.timer);if(c.context.state!=='closed')void c.context.close();}
 function stop(discard=false){const c=capture.current;if(!c)return;c.discard=discard;if(c.recorder.state!=='inactive')c.recorder.stop();release();setRecording(false);setLevel(0);if(discard)setBlob(null);}
 function loadRow(r:any){setRow(r);let draft:any=null;try{draft=JSON.parse(sessionStorage.getItem(transcriptKey(r.id))||'null');}catch{}const value=transcriptState(r,draft);setText(value.text);setRevision(value.revision);setReviewed(value.reviewed);}
 function restoreGenerated(){if(!row)return;const value=row.data.transcript||'';setText(value);setRevision(row.updated_at);setReviewed(false);sessionStorage.setItem(transcriptKey(row.id),JSON.stringify({text:value,revision:row.updated_at}));}
 async function refresh(){const rows=await call('/interview-practice/sessions/'+session+'/voice');const r=rows.find((v:any)=>v.data.question_id===question);if(alive.current&&r)loadRow(r);}
 useEffect(()=>{alive.current=true;void refresh().catch((e:Error)=>setError(e.message));return()=>{alive.current=false;onRecording(false);onBusy(false);if(capture.current){capture.current.discard=true;if(capture.current.recorder.state!=='inactive')capture.current.recorder.stop();release();}if(playRef.current)URL.revokeObjectURL(playRef.current);};},[question]);
 useEffect(()=>{const hide=()=>{if(document.hidden&&capture.current){stop(true);setError('Recording stopped and discarded when this tab was hidden.');}};document.addEventListener('visibilitychange',hide);return()=>document.removeEventListener('visibilitychange',hide);},[]);
 async function record(){setError('');setBlob(null);setReviewed(false);try{
  if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder)throw Error('Recording is unavailable in this browser. Typed answers remain available.');
  const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true}});if(!alive.current){stream.getTracks().forEach(t=>t.stop());return;}
  let context:AudioContext;let analyser:AnalyserNode;try{context=new AudioContext();analyser=context.createAnalyser();analyser.fftSize=256;context.createMediaStreamSource(stream).connect(analyser);await context.resume();}catch(e){stream.getTracks().forEach(t=>t.stop());throw e;}
  const recorder=new MediaRecorder(stream),chunks:Blob[]=[],c:any={stream,context,recorder,discard:false,frame:0,timer:0};capture.current=c;let count=0,bytes=0;
  recorder.ondataavailable=e=>{if(e.data.size){bytes+=e.data.size;chunks.push(e.data);if(bytes>20*1024*1024){stop(true);setError('The recording exceeded 20 MB and was discarded.');}}};
  recorder.onstop=()=>{if(!c.discard&&alive.current)setBlob(new Blob(chunks,{type:recorder.mimeType}));chunks.length=0;};recorder.onerror=()=>{stop(true);setError('Recording failed. Your typed work is preserved.');};
  const levels=new Uint8Array(analyser.frequencyBinCount);const meter=()=>{analyser.getByteTimeDomainData(levels);setLevel(Math.min(1,Math.sqrt(Array.from(levels).reduce((a,v)=>a+(v-128)**2,0)/levels.length)/40));c.frame=requestAnimationFrame(meter);};meter();
  c.timer=window.setInterval(()=>{count++;setSeconds(count);if(count>=300)stop();},1000);setSeconds(0);setRecording(true);recorder.start(500);
 }catch(e){release();setRecording(false);setError((e as Error).message||'Microphone permission was denied. Typed practice remains available.');}}
 function remember(v:any){setPending(v);if(v)localStorage.setItem(key,JSON.stringify(v));else localStorage.removeItem(key);}
 async function finish(v:any){if(!v.id){const s=await call('/interview-practice/voice-actions/'+v.token);v={...v,id:s.task_id};remember(v);}const result=await pollTask(v.id,call,undefined,600);if(v.operation==='narrate'){
  const audio=await call('/interview-practice/voice-playback/'+result.playback_token);const bytes=Uint8Array.from(atob(audio.base64),c=>c.charCodeAt(0));if(playRef.current)URL.revokeObjectURL(playRef.current);const url=URL.createObjectURL(new Blob([bytes],{type:'audio/wav'}));playRef.current=url;if(alive.current)setPlayback(url);
 }else await refresh();remember(null);if(alive.current)onReady();}
 async function run(operation:'audio'|'narrate',recovery=false){setBusy(true);onBusy(true);setError('');
 try{let v=pending;if(!recovery){if(operation!=='audio')throw Error('Only recording processing can be started here.');let wav:Blob|null=null;if(operation==='audio'){if(!blob)throw Error('Record an answer first.');wav=await recordingWav(blob);if(wav.size>20*1024*1024)throw Error('The recording exceeds 20 MB.');}v={token:crypto.randomUUID(),operation};remember(v);const result=await call('/interview-practice/sessions/'+session+(operation==='audio'?'/voice?question_id='+question+'&request_token='+v.token:'/narration'),'POST',operation==='audio'?wav:{question_id:question,request_token:v.token});v={...v,id:result.task_id};remember(v);setBlob(null);}await finish(v);
 }catch(e){setError((e as Error).message);await refresh().catch(()=>{});if((e as any).status&&[400,404,409,410,413,422,499].includes((e as any).status))remember(null);}finally{setBlob(null);setBusy(false);onBusy(false);}}
 return <section className="interview-voice"><h3>Answer format</h3>
 <div className="card-actions" role="group" aria-label="Answer format">{['typed','voice','mixed'].map(v=><button type="button" className={'button '+(format===v?'primary':'secondary')} aria-pressed={format===v} disabled={busy||recording||blocked||!!pending} key={v} onClick={()=>{if(v!==format)onFormat(v);}}>{v[0].toUpperCase()+v.slice(1)}</button>)}</div>
 {format==='mixed'&&<p className="small muted">Record your answer and add typed notes or code. Both are included in your answer review.</p>}
 {format!=='typed'&&<><p>Record up to 5 minutes. Recording starts only when you choose Start recording.</p><p className="small muted">Processing sends audio to your account’s AI provider for transcription and delivery observations. Recordings are temporary; provider retention terms apply.</p>
 <div className="card-actions">{!recording?<button type="button" className="button secondary" disabled={locked} onClick={()=>void record()}>Start recording</button>:<><span role="status">● Recording · {Math.floor(seconds/60)}:{String(seconds%60).padStart(2,'0')}</span><meter min={0} max={1} value={level} aria-label="Microphone input level"/><button type="button" className="button secondary" onClick={()=>stop()}>Stop recording</button><button type="button" className="text-button" onClick={()=>stop(true)}>Discard recording</button></>}
 {blob&&<><span>Recording ready · not sent</span><button type="button" className="button primary" disabled={locked||!available} onClick={()=>void run('audio')}>Process recording · paid</button><button type="button" className="text-button" onClick={()=>setBlob(null)}>Discard</button></>}</div>
 <p className="small muted">Estimate: transcription $0.0045/min + delivery analysis about $0.04/min. Review my answer is a separate AI request for content feedback.</p>
 {row&&<div className="interview-transcript"><h3>Check your transcript</h3>
 {row.data.state==='processing'&&<p role="status">Recording processing has not finished. Check its saved status above.</p>}
 {stale&&<p role="alert" className="notice">The saved transcript changed. Your edits are kept. Restore generated transcript, or <button type="button" className="text-button" onClick={()=>{setRevision(row.updated_at);setReviewed(false);sessionStorage.setItem(transcriptKey(row.id),JSON.stringify({text,revision:row.updated_at}));}}>keep my edits against the latest version</button> and confirm them again.</p>}
 {row.data.warnings?.map((v:string,i:number)=><p className="notice" key={i}>{v}</p>)}
 {row.data.transcript?.trim()?<><p className="small muted">The transcript is ready. Check the text and confirm it, then choose Review my answer for content feedback. Delivery observations are on Feedback &amp; conversation.</p>
 <label>Transcript<textarea aria-label="Transcript" rows={7} maxLength={24000} disabled={busy||recording} value={text} onChange={e=>{setText(e.target.value);setReviewed(false);sessionStorage.setItem(transcriptKey(row.id),JSON.stringify({text:e.target.value,revision}));}}/></label>
 {(text!==row.data.transcript||stale)&&<button type="button" className="text-button" disabled={busy||recording} onClick={restoreGenerated}>Restore generated transcript</button>}
 {!text.trim()&&<p role="alert">Your transcript draft is empty. The generated transcript remains available to restore.</p>}
 <label className="check-line"><input type="checkbox" checked={reviewed} disabled={!text.trim()||busy||recording||stale||row.data.state==='processing'} onChange={e=>setReviewed(e.target.checked)}/>I reviewed and corrected this transcript.</label>
 <p className="small muted">Review my answer saves this confirmed transcript before requesting feedback. New statements do not automatically update Profile.</p>
 </>:row.data.state!=='processing'&&<p role="alert" className="notice">{row.data.delivery?'Delivery observations are available, but transcription did not produce usable text. Content review cannot run without a confirmed transcript.':'No usable transcript is available. Processing was incomplete.'} Your typed drafts are kept. Choose Typed or explicitly record again; no paid retry runs automatically.</p>}
 </div>}
 </>}
 {statusHost&&createPortal(<>{busy&&!globalProgress&&<p role="status">Processing your audio request…{pending?.id&&<button type="button" className="text-button" onClick={()=>void call('/tasks/'+pending.id+'/cancel','POST',{}).catch((e:Error)=>setError(e.message))}>Stop processing</button>}</p>}
 {pending&&!busy&&<div className="notice"><p>A submitted audio request has a saved status. Checking it makes no new model request.</p><button type="button" className="button secondary" onClick={()=>void run(pending.operation,true)}>Check saved audio status</button>{pending.id&&<button type="button" className="text-button" onClick={()=>void call('/tasks/'+pending.id+'/cancel','POST',{}).catch((e:Error)=>setError(e.message))}>Stop processing</button>}<button type="button" className="text-button" onClick={async()=>{try{const s=await call('/interview-practice/voice-actions/'+pending.token);const t=await call('/tasks/'+s.task_id);if(['queued','running','cancelling'].includes(t.status))throw Error('The request is still active. Stop it or check its status.');remember(null);await refresh();}catch(e){if((e as any).status===404)remember(null);else setError((e as Error).message);}}}>Resolve completed or unconfirmed request</button></div>}
 {error&&<p role="alert" className="notice">{error}</p>}{playback&&<audio aria-label="Recovered question narration" controls src={playback}/>}</>,statusHost)}
 </section>;
});
