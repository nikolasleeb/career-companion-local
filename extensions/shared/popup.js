const api=globalThis.browser||globalThis.chrome;
const $=id=>document.getElementById(id);let context=null;
async function send(action,extra={}){const response=await api.runtime.sendMessage({channel:'career-companion-ui-v1',action,...extra});if(!response?.ok)throw Error(response?.error||'Extension unavailable.');return response.result;}
function option(select,value,text){const el=document.createElement('option');el.value=value;el.textContent=text;select.append(el);}
async function state(){const s=await send('state');$('status').textContent=s.run?`${s.run.state.replaceAll('_',' ')} · ${s.run.pages}/20 pages · ${s.run.writes}/300 writes`:s.connection.pairingId?'Connection requested — approve it in Career Companion.':'Disconnected';if(s.connection.appOrigin)$('origin').value=s.connection.appOrigin;if(s.connection.code)$('code').textContent='Pairing code: '+s.connection.code;if(s.lastError)$('error').textContent=s.lastError;}
async function action(fn){$('error').textContent='';for(const b of document.querySelectorAll('button'))b.disabled=true;try{await fn();await state();}catch(error){$('error').textContent=error.message;}finally{for(const b of document.querySelectorAll('button'))b.disabled=false;}}
function versions(){const a=context?.applications.find(x=>x.id===$('application').value);$('resume').replaceChildren();$('cover').replaceChildren();option($('cover'),'','No cover letter');for(const id of a?.resume_ids||[]){const d=context.resumes.find(x=>x.id===id);if(d)option($('resume'),id,`${d.title} · ${d.updated_at.slice(0,16)} · ${id.slice(0,8)}`);}for(const id of a?.cover_letter_ids||[]){const d=context.cover_letters.find(x=>x.id===id);if(d)option($('cover'),id,`${d.title} · ${d.updated_at.slice(0,16)} · ${id.slice(0,8)}`);}$('approved').checked=false;}
$('application').onchange=versions;$('resume').onchange=()=>{$('approved').checked=false;};$('cover').onchange=()=>{$('approved').checked=false;};
$('connect').onclick=()=>action(async()=>{
 const url=new URL($('origin').value);
 const allowed=(url.protocol==='http:'&&['localhost','127.0.0.1'].includes(url.hostname));
 if(!allowed||url.username||url.password)throw Error('Use localhost or 127.0.0.1.');
 // Safari match patterns cannot contain ports. Request the manifest's host
 // pattern, while retaining the exact origin (including port) for pairing.
 const pattern=`${url.protocol}//${url.hostname}/*`;
 if(!await api.permissions.request({origins:[pattern]}))throw Error('Permission was not granted.');
 await send('connect',{origin:url.origin});
});
$('origin').onkeydown=event=>{
 if(event.key==='Enter'){
  event.preventDefault();
  if(!$('connect').disabled)return $('connect').onclick();
 }
};
$('load').onclick=()=>action(async()=>{context=await send('context');$('application').replaceChildren();option($('application'),'','Choose an application');for(const a of context.applications)option($('application'),a.id,`${a.company} — ${a.title}`);versions();});
$('start').onclick=()=>action(async()=>{if(!$('approved').checked||!$('application').value||!$('resume').value)throw Error('Choose an application and confirm the document versions.');await send('start',{applicationId:$('application').value,resumeId:$('resume').value,coverLetterId:$('cover').value,documentsApproved:true});});
$('pause').onclick=()=>action(()=>send('pause'));$('continue').onclick=()=>action(()=>send('continue'));$('disconnect').onclick=()=>action(()=>send('disconnect'));state().catch(e=>{$('error').textContent=e.message;});
