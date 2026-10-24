const api=globalThis.browser||globalThis.chrome;
const $=id=>document.getElementById(id);
let context=null,current=null,account='',refreshing=false,acting=false,lastContext=0,localError='';
async function send(action,extra={}){const response=await api.runtime.sendMessage({channel:'career-companion-ui-v1',action,...extra});if(!response?.ok)throw Error(response?.error||'Extension unavailable. Reopen the popup.');return response.result;}
function option(select,value,text){const el=document.createElement('option');el.value=value;el.textContent=text;select.append(el);}
function selection(){const a=$('application').value,r=$('resume').value,c=$('cover').value;const docs=[...context?.resumes||[],...context?.cover_letters||[]];return {applicationId:a,resumeId:r,coverLetterId:c,fingerprint:JSON.stringify([a,...[r,c].filter(Boolean).map(id=>[id,docs.find(d=>d.id===id)?.updated_at||''])])};}
async function retain(){if(context)await send('selection',selection());}
function versions(saved){const a=context?.applications.find(x=>x.id===$('application').value);$('resume').replaceChildren();$('cover').replaceChildren();option($('resume'),'','Choose a resume');option($('cover'),'','No cover letter');
 const resumes=context.resumes.filter(d=>a?.resume_ids.includes(d.id));
 for(const d of resumes)option($('resume'),d.id,`${d.title} · ${d.updated_at.slice(0,16)} · ${d.id.slice(0,8)}`);
 for(const d of context.cover_letters.filter(d=>a?.cover_letter_ids.includes(d.id)))option($('cover'),d.id,`${d.title} · ${d.updated_at.slice(0,16)} · ${d.id.slice(0,8)}`);
 $('resume').value=resumes.some(d=>d.id===saved?.resumeId)?saved.resumeId:resumes.length===1?resumes[0].id:'';
 $('cover').value=a?.cover_letter_ids.includes(saved?.coverLetterId)?saved.coverLetterId:'';
}
async function load(saved){const previous=context?selection():saved,approved=$('approved').checked;context=await send('context');lastContext=Date.now();
 // Only applications with a currently available saved resume can start a run.
 context.applications=context.applications.filter(a=>a.resume_ids.some(id=>context.resumes.some(d=>d.id===id)));
 $('application').replaceChildren();option($('application'),'','Choose an application');for(const a of context.applications)option($('application'),a.id,`${a.company} — ${a.title}`);
 $('application').value=context.applications.some(a=>a.id===previous?.applicationId)?previous.applicationId:context.applications.length===1?context.applications[0].id:'';
 versions(previous);$('approved').checked=approved&&previous?.fingerprint===selection().fingerprint;await retain();
}
function render(){if(!current)return;const s=current,r=s.run,active=r&&!['stopped','failed'].includes(r.state);const running=s.busy&&!s.lastError;
 $('status').textContent=s.lastError?'Filling stopped — action needed':r?`${running?r.state.replaceAll('_',' '):r.state==='ready_for_final_review'?'Finished':r.state==='needs_input'?'Questions need review':r.state==='paused'?'Paused':'Recovery needed'}\n${s.verified} verified filled · ${r.questions} needing attention · ${r.pages}/20 pages`:s.connection.status==='approved'?'Connected · Ready to start':s.connection.status==='pending'?'Approve the matching code in Career Companion':'Connect your browser to begin';
 $('contact').textContent=s.lastContact?'Last successful contact '+new Date(s.lastContact).toLocaleTimeString():'';
 $('error').textContent=localError||s.lastError||'';$('reason').textContent=r?({final_review:'Review the full form and submit personally.',manual_handoff:'Complete the flagged controls personally on the employer tab.',validation:'A field needs your review on the employer tab.',user_action:'Paused by you.',connection_lost:'Check your connection before resuming.'}[r.reason]||r.reason||'')+(!s.busy&&!['paused','needs_input','ready_for_final_review','stopped','failed'].includes(r.state)?' The saved run is inactive. Resume filling to recover explicitly.':''):'';
 $('start').textContent=r?.state==='ready_for_final_review'?'Finished—review on employer site':active?(r.state==='needs_input'&&r.questions&&!s.reviewVisited?'Review questions':'Resume filling'):'Start filling';
 $('start').disabled=acting||s.busy||s.connection.status!=='approved'||r?.state==='ready_for_final_review';
 $('newrun').hidden=!r||!['stopped','failed','ready_for_final_review'].includes(r.state);$('newrun').disabled=acting||s.busy;
 $('pause').hidden=!s.busy;$('pause').disabled=acting;
 $('choices').hidden=!!active;for(const id of ['application','resume','cover','approved','connect','load','disconnect'])$(id).disabled=acting||s.busy;
 if(!$('origin').matches(':focus')&&s.connection.appOrigin)$('origin').value=s.connection.appOrigin;
 $('code').textContent=s.connection.status==='pending'?'Pairing code: '+s.connection.code:s.connection.status==='approved'?'Connected to this account':'';
 if(!s.connection.pairingId)$('settings').open=true;
}
async function state(){if(refreshing||acting)return;refreshing=true;try{current=await send('state');if(account!==current.connection.accountId){context=null;account=current.connection.accountId||'';$('approved').checked=false;}
 render();if(current.connection.status==='approved'&&(!context||Date.now()-lastContext>30000))await load(current.selections);
 render();}catch(e){$('error').textContent=e.message;$('status').textContent='Connection unavailable — check Career Companion';}finally{refreshing=false;}}
async function action(fn){if(acting)return;acting=true;localError='';$('error').textContent='';render();try{await fn();}catch(e){localError=e.message;$('error').textContent=localError;return;}finally{acting=false;render();}await state();}
$('application').onchange=()=>action(async()=>{versions();$('approved').checked=false;await retain();});
for(const id of ['resume','cover'])$(id).onchange=()=>action(async()=>{$('approved').checked=false;await retain();});
$('connect').onclick=()=>action(async()=>{const url=new URL($('origin').value);if(!((url.protocol==='http:'&&['localhost','127.0.0.1'].includes(url.hostname)))||url.username||url.password)throw Error('Use a localhost Career Companion address.');const permission=api.permissions.request({origins:[`${url.protocol}//${url.hostname}/*`]});const connecting=send('connect',{origin:url.origin,waitForPermission:true});connecting.catch(()=>{});if(!await permission)throw Error('Permission was not granted.');await connecting;context=null;});
$('origin').onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();if(!$('connect').disabled)return $('connect').onclick();}};
$('newrun').onclick=()=>action(async()=>{await send('reset');$('approved').checked=false;});
$('load').onclick=()=>action(()=>load(current?.selections));
$('start').onclick=()=>action(async()=>{const r=current?.run;if(r&&!['stopped','failed'].includes(r.state)){await send(r.state==='needs_input'&&r.questions&&!current.reviewVisited?'review':'continue');return;}
 if(!$('approved').checked||!$('application').value||!$('resume').value)throw Error('Choose the application and resume, then approve sharing these exact versions.');
 await send('start',{...selection(),documentsApproved:true});});
$('pause').onclick=()=>action(()=>send('pause'));$('disconnect').onclick=()=>action(async()=>{await send('disconnect');context=null;});
state();setInterval(state,1000);
