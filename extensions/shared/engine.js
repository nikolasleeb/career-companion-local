/* Structured DOM adapter: data in, bounded readback-verified writes out. */
(()=>{
 if(globalThis.CareerCompanionDOM)return;
 const visible=el=>!!(el.getClientRects().length)&&getComputedStyle(el).visibility!=='hidden'&&!el.closest('[hidden],[aria-hidden="true"],[inert]');
 const clean=s=>String(s||'').replace(/\s+/g,' ').trim().slice(0,500);
 const norm=s=>clean(s).toLocaleLowerCase();
 const boundary=/signature|attest|under penalty|certify that|certification of|credit card|payment|captcha|recaptcha|hcaptcha|sign in|log in|login/i;
 const edited=new WeakSet();for(const type of ['input','change'])document.addEventListener(type,event=>{if(event.isTrusted&&event.target instanceof Element)edited.add(event.target);},true);
 let refs=new Map();let snapshots=new Map();let stopped=false;
 function label(el){
   const labelled=(el.getAttribute('aria-labelledby')||'').split(/\s+/).map(id=>document.getElementById(id)?.textContent||'').join(' ');
   const own=el.labels?[...el.labels].map(x=>{const copy=x.cloneNode(true);for(const child of copy.querySelectorAll('input,select,textarea,button,[role="option"]'))child.remove();return copy.textContent;}).join(' '):'';
   return clean(labelled||el.getAttribute('aria-label')||own||el.getAttribute('placeholder')||el.name||'Unlabelled field');
 }
 function value(el){return el.type==='checkbox'||el.type==='radio'?el.checked:el.value??el.getAttribute('aria-valuetext')??el.textContent??'';}
 function groupLabel(el){const group=el.closest('fieldset,[role="radiogroup"],[role="group"]');return clean(group?.querySelector('legend')?.textContent||group?.getAttribute('aria-label')||label(el));}
 function inspect(){
  refs=new Map();snapshots=new Map();stopped=false;
  const fields=[];const boundaries=new Set();const radios=new Set();const repeatGroups={education:[],employment:[]};
  if(document.querySelector('input[type="password"]'))boundaries.add('login');
  if([...document.querySelectorAll('iframe')].some(x=>visible(x)&&/captcha/i.test((x.src||'')+' '+x.title)))boundaries.add('captcha');
  for(const frame of document.querySelectorAll('iframe')){
   if(!visible(frame))continue;
   try{if(!frame.contentDocument||frame.contentDocument.querySelector('input,select,textarea,button'))boundaries.add('inaccessible_frame');}catch{boundaries.add('inaccessible_frame');}
  }
  for(const el of document.querySelectorAll('input:not([type="hidden"]),textarea,select,[role="combobox"],[role="checkbox"],[role="radio"],[contenteditable="true"],canvas')){
   if(!visible(el)||el.disabled||(el.readOnly&&el.getAttribute('role')!=='combobox')||el.closest('[data-career-companion-ui]'))continue;
   if(['submit','button','reset','image'].includes(el.type))continue;
   const text=label(el);const context=clean(el.closest('fieldset,[role="group"],[role="radiogroup"]')?.querySelector('legend')?.textContent||'');
   const description=clean((el.getAttribute('aria-describedby')||'').split(/\s+/).map(id=>{const x=document.getElementById(id);return x&&!x.closest('[role="status"],[role="alert"],[aria-live]')?x.textContent:'';}).join(' '));
   let control=el.tagName==='SELECT'?'select':el.tagName==='TEXTAREA'?'textarea':el.getAttribute('role')==='combobox'?'combobox':el.type||'unsupported';
   if(!['text','email','tel','url','number','date','textarea','select','radio','checkbox','combobox','file'].includes(control))control='unsupported';
   if(control==='unsupported')boundaries.add('unsupported_control');
   if(boundary.test(text+' '+context+' '+description))boundaries.add(/captcha/i.test(text)?'captcha':/signature/i.test(text)?'signature':/payment|credit card/i.test(text)?'payment':/sign in|log in|login/i.test(text)?'login':'attestation');
   let options=[];let members=null;let question=text;
   if(control==='radio'){
    const name=el.name;if(!name){boundaries.add('unsupported_control');continue;}
    if(radios.has(name))continue;radios.add(name);
    members=[...document.querySelectorAll('input[type="radio"]')].filter(x=>x.name===name&&visible(x));options=members.map(label);question=groupLabel(el);
    if(new Set(options.map(norm)).size!==options.length)boundaries.add('unsupported_control');
   }
   if(control==='select')options=[...el.options].filter(x=>!x.disabled&&x.value!=='').map(x=>clean(x.textContent));
   if(control==='checkbox')options=['Yes','No'];
   if(control==='combobox'){
    const list=document.getElementById(el.getAttribute('aria-controls')||el.getAttribute('aria-owns')||'');
    options=list?[...list.querySelectorAll('[role="option"]')].map(x=>clean(x.textContent)):[];
    if(!options.length)boundaries.add('unsupported_control');
   }
   const container=el.closest('fieldset,[role="group"],[data-repeat-section]');
   const heading=clean(container?.querySelector('legend,h2,h3,h4')?.textContent||container?.getAttribute('aria-label')||container?.getAttribute('data-repeat-section'));
   const section=/education|school/i.test(heading)?'education':/employment|work experience|previous employer/i.test(heading)?'employment':'';
   let repeat_index=0;
   if(section&&container){if(!repeatGroups[section].includes(container))repeatGroups[section].push(container);repeat_index=repeatGroups[section].indexOf(container);}
   if(text.length>=500||description.length>=500||context.length>=500||options.some(x=>x.length>=500))boundaries.add('unsupported_control');
   const group=el.closest('fieldset,[role="group"],[role="radiogroup"]');
   if(/veteran|disab|gender|race|ethnic|clearance/i.test(question+' '+context)&&group?.querySelector('p')&&!el.getAttribute('aria-describedby'))boundaries.add('unsupported_control');
   const id='f'+fields.length;refs.set(id,{el,members,control,question,description,context,options});snapshots.set(id,members?members.map(value):value(el));
   fields.push({id,label:question,description,context,control,autocomplete:clean(el.autocomplete).replace(/^section-\S+\s*/,'').replace(/^(shipping|billing)\s*/,''),options,has_value:members?members.some(x=>x.checked||edited.has(x)):edited.has(el)||(control==='checkbox'?el.checked:!!String(value(el)).trim()),required:!!el.required||el.getAttribute('aria-required')==='true',section,repeat_index});
  }
  if(fields.length>120)boundaries.add('unsupported_control');
  const buttons=[...document.querySelectorAll('button,input[type="submit"],a[role="button"]')].filter(visible);
  const names=buttons.map(x=>clean(x.innerText||x.value||x.getAttribute('aria-label')));
  const reviewHeading=[...document.querySelectorAll('h1,h2,h3,[role="heading"]')].some(x=>visible(x)&&/final review|review (?:your )?application|confirm (?:your )?submission/i.test(clean(x.textContent)));
  const final_review=reviewHeading||names.some(x=>/^(submit|submit application|submit my application|send application|apply now|finish application|complete application)$/i.test(x));
  return {fields:fields.slice(0,120),boundaries:[...boundaries],final_review};
 }
 function unchanged(id){
  const ref=refs.get(id);if(!ref||!ref.el.isConnected||!visible(ref.el)||ref.el.disabled||(ref.el.readOnly&&ref.control!=='combobox'))return false;
  if((ref.control==='radio'?groupLabel(ref.el):label(ref.el))!==ref.question)return false;
  const context=clean(ref.el.closest('fieldset,[role="group"],[role="radiogroup"]')?.querySelector('legend')?.textContent||'');
  const description=clean((ref.el.getAttribute('aria-describedby')||'').split(/\s+/).map(id=>{const x=document.getElementById(id);return x&&!x.closest('[role="status"],[role="alert"],[aria-live]')?x.textContent:'';}).join(' '));
  if(context!==ref.context||description!==ref.description)return false;
  const choices=ref.control==='radio'?ref.members.map(label):ref.control==='select'?[...ref.el.options].filter(x=>!x.disabled&&x.value!=='').map(x=>clean(x.textContent)):ref.control==='combobox'?[...(document.getElementById(ref.el.getAttribute('aria-controls')||ref.el.getAttribute('aria-owns')||'')?.querySelectorAll('[role="option"]')||[])].map(x=>clean(x.textContent)):ref.options;
  if(JSON.stringify(choices)!==JSON.stringify(ref.options))return false;
  return JSON.stringify(ref.members?ref.members.map(value):value(ref.el))===JSON.stringify(snapshots.get(id));
 }
 function write(id,wanted){
  const ref=refs.get(id);if(stopped||!ref||!unchanged(id))return {id,ok:false,reason:'conflict'};
  const {el,members,control}=ref;
  if(['file','unsupported'].includes(control)||boundary.test(ref.question))return {id,ok:false,reason:'manual_handoff'};
  if(control==='checkbox'){
   if(!['Yes','No'].includes(wanted))return {id,ok:false,reason:'choice'};
   if(el.checked!==(wanted==='Yes'))el.click();
  }else if(control==='radio'){
   const choices=members.filter(x=>label(x)===wanted);if(choices.length!==1)return {id,ok:false,reason:'choice'};choices[0].click();
  }else if(control==='select'){
   const choices=[...el.options].filter(x=>!x.disabled&&clean(x.textContent)===wanted);if(choices.length!==1)return {id,ok:false,reason:'choice'};
   Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(el,choices[0].value);
  }else if(control==='combobox'){
   const list=document.getElementById(el.getAttribute('aria-controls')||el.getAttribute('aria-owns')||'');
   const choices=list?[...list.querySelectorAll('[role="option"]')].filter(x=>clean(x.textContent)===wanted&&visible(x)):[];
   if(choices.length!==1)return {id,ok:false,reason:'manual_handoff'};choices[0].click();
  }else{
   const prototype=el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
   Object.getOwnPropertyDescriptor(prototype,'value').set.call(el,wanted);
  }
  el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));
  const actual=control==='radio'?members.find(x=>x.checked):control==='select'?clean(el.selectedOptions[0]?.textContent):control==='checkbox'?(el.checked?'Yes':'No'):String(value(el));
  const ok=(control==='radio'?actual&&label(actual)===wanted:actual===wanted)&&el.getAttribute('aria-invalid')!=='true'&&(!el.validity||el.validity.valid);
  return {id,ok:!!ok,reason:ok?'':'validation'};
 }
 function next(){
  if(stopped)return {ok:false,reason:'stopped'};
  const scan=inspect();if(scan.boundaries.length||scan.final_review)return {ok:false,reason:'boundary'};
  if([...document.querySelectorAll('[aria-invalid="true"],input:invalid,select:invalid,textarea:invalid')].some(visible))return {ok:false,reason:'validation'};
  // Only literal ordinary Next/Continue controls; all mixed/ambiguous labels require a person.
  const candidates=[...document.querySelectorAll('button,input[type="button"],input[type="submit"]')].filter(x=>visible(x)&&!x.disabled&&/^(next|continue|save and continue)$/i.test(clean(x.innerText||x.value||x.getAttribute('aria-label'))));
  if(candidates.length!==1)return {ok:false,reason:'manual_handoff'};
  const button=candidates[0];const form=button.form;
  if(form){const dest=new URL(form.action||location.href,location.href);if(dest.origin!==location.origin||/\/(submit|final|complete|payment|checkout)(\/|$)/i.test(dest.pathname)||form.target&&form.target!=='_self')return {ok:false,reason:'origin_changed'};}
  const labelText=clean(button.innerText||button.value||button.getAttribute('aria-label'));
  button.click();return {ok:true,label:labelText};
 }
 globalThis.CareerCompanionDOM={inspect,write,next,stop:()=>{stopped=true;refs.clear();snapshots.clear();},version:1};
})();
