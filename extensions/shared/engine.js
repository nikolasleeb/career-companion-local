/* Structured DOM adapter: data in, bounded readback-verified writes out. */
(()=>{
 if(globalThis.CareerCompanionDOM?.version===4)return;
 const visible=el=>!!(el.getClientRects().length)&&getComputedStyle(el).visibility!=='hidden'&&!el.closest('[hidden],[aria-hidden="true"],[inert]');
 const clean=s=>String(s||'').replace(/\s+/g,' ').trim().slice(0,500);
 const norm=s=>clean(s).toLocaleLowerCase();
 const boundary=/password|passcode|one[ -]time code|verification code|i acknowledge|consent|i agree|i confirm|opt[ -]?in|subscribe|signature|attest|under penalty|certify that|certification of|credit card|payment|captcha|recaptcha|hcaptcha|sign in|log in|login/i;
 const edited=new WeakSet();for(const type of ['input','change'])document.addEventListener(type,event=>{if(event.isTrusted&&event.target instanceof Element)edited.add(event.target);},true);
 let refs=new Map();let snapshots=new Map();let stopped=false;
 function label(el){
   const labelled=(el.getAttribute('aria-labelledby')||'').split(/\s+/).map(id=>document.getElementById(id)?.textContent||'').join(' ');
   const labels=el.labels?[...el.labels]:el.closest('label')?[el.closest('label')]:[];
   const own=labels.map(x=>{const copy=x.cloneNode(true);for(const child of copy.querySelectorAll('input,select,textarea,button,[role="option"],[contenteditable]' ))child.remove();return copy.textContent;}).join(' ');
   return clean(labelled||el.getAttribute('aria-label')||own||el.getAttribute('placeholder')||el.name||'Unlabelled field');
 }
 const comboInput=el=>el instanceof HTMLInputElement?el:el.querySelector('input');
 const comboList=el=>{const input=comboInput(el);return document.getElementById(el.getAttribute('aria-controls')||el.getAttribute('aria-owns')||input?.getAttribute('aria-controls')||input?.getAttribute('aria-owns')||'');};
 let headingNodes=[];
 function value(el){if(el.getAttribute('role')==='combobox'&&!(el instanceof HTMLInputElement))return el.getAttribute('aria-valuetext')||clean(el.textContent)||comboInput(el)?.value||'';return el.type==='checkbox'||el.type==='radio'?el.checked:el.value??el.getAttribute('aria-valuetext')??el.textContent??'';}
 function groupLabel(el){const group=el.closest('fieldset,[role="radiogroup"],[role="group"]');return clean(group?.querySelector('legend')?.textContent||group?.getAttribute('aria-label')||label(el));}

 const placeholder=v=>/^(unknown|undefined|null|n\/a)$/i.test(String(v).trim());
 const emptyChoice=v=>/^(?:select|choose)(?: (?:an?|your))? (?:option|country|state|school|major|degree)|^not required$|^--+$|^please select/i.test(clean(v));
 function sectionInfo(el,text){
  const explicit=el.closest('[data-repeat-section],fieldset,[role="group"]');
  let heading=clean(explicit?.getAttribute('data-repeat-section')||explicit?.getAttribute('aria-label')||explicit?.querySelector('legend')?.textContent);
  if(!/education|employment|work experience|previous employer/i.test(heading)){
   const preceding=headingNodes.filter(h=>!!(h.compareDocumentPosition(el)&Node.DOCUMENT_POSITION_FOLLOWING));
   heading=clean(preceding.at(-1)?.textContent);
  }
  let section=/education|school/i.test(heading)?'education':/employment|work experience|previous employer/i.test(heading)?'employment':'';
  if(!section&&/^(job title|current job|employer|company name)\s*[:?*]*$/i.test(text))section='employment';
  if(!section&&/^(school|school name|education level|primary major\/program|degree)\s*[:?*]*$/i.test(text))section='education';
  let container=explicit;
  if(section&&!container){
   // Plain employer layouts often use divs rather than semantic fieldsets.
   // Bind a repeated entry only while it contains one organization anchor and no other section.
   for(let node=el.parentElement;node&&node.tagName!=='FORM'&&node!==document.body;node=node.parentElement){
    const controls=[...node.querySelectorAll('input:not([type="hidden"]),select,textarea,[role="combobox"]')];
    const anchor=section==='education'?/^(school|university)(?:\s|$)/i:/^(employer|company)(?:\s|$)/i;
    if(controls.filter(x=>anchor.test(label(x))).length>1)break;
    if(controls.some(x=>section==='education'?/^(job title|current job)/i.test(label(x)):/^(school|education level)/i.test(label(x))))break;
    if(controls.length>1&&controls.some(x=>anchor.test(label(x))))container=node;
   }
  }
  return {section,container};
 }
 function inspect(){
  refs=new Map();snapshots=new Map();stopped=false;
  headingNodes=[...document.querySelectorAll('h2,h3,h4,legend,[role="heading"],div,span,p,strong')].filter(h=>visible(h)&&(/^(?:personal information|education history|work experience|employment history|immigration information|deloitte alumni information|password)$/i.test(clean(h.textContent))||h.matches('h2,h3,h4,legend,[role="heading"]')));
  const fields=[];const manual_fields=[];const review_existing=[];const boundaries=new Set();const radios=new Set();const repeatGroups={education:[],employment:[]};
  if([...document.querySelectorAll('input[type="password"]')].some(x=>visible(x)&&!x.disabled))boundaries.add('login');
  if([...document.querySelectorAll('iframe')].some(x=>visible(x)&&/captcha/i.test((x.src||'')+' '+x.title)))boundaries.add('captcha');
  for(const frame of document.querySelectorAll('iframe')){
   if(!visible(frame))continue;
   try{if(!frame.contentDocument||frame.contentDocument.querySelector('input,select,textarea,button'))boundaries.add('inaccessible_frame');}catch{boundaries.add('inaccessible_frame');}
  }
  const controls=[...document.querySelectorAll('input:not([type="hidden"]),textarea,select,[role="combobox"],[role="checkbox"],[role="radio"],[contenteditable="true"],canvas')];
  // Process rows top to bottom, then left to right; preserve DOM order on ties.
  controls.sort((a,b)=>{const x=a.getBoundingClientRect(),y=b.getBoundingClientRect();return Math.abs(x.top-y.top)>3?x.top-y.top:x.left-y.left;});
  for(const el of controls){
   if(!visible(el)||el.disabled||(el.readOnly&&el.getAttribute('role')!=='combobox')||el.closest('[data-career-companion-ui]'))continue;
   if(el.closest('[role="combobox"]')&&el.closest('[role="combobox"]')!==el)continue;
   if(['submit','button','reset','image'].includes(el.type))continue;
   const text=label(el);const context=clean(el.closest('fieldset,[role="group"],[role="radiogroup"]')?.querySelector('legend')?.textContent||'');
   const description=clean((el.getAttribute('aria-describedby')||'').split(/\s+/).map(id=>{const x=document.getElementById(id);return x&&!x.closest('[role="status"],[role="alert"],[aria-live]')?x.textContent:'';}).join(' '));
   let control=el.tagName==='SELECT'?'select':el.tagName==='TEXTAREA'?'textarea':el.getAttribute('role')==='combobox'?'combobox':el.type||'unsupported';
   if(!['text','email','tel','url','number','date','month','textarea','select','radio','checkbox','combobox','file'].includes(control))control='unsupported';
   const credential=el.type==='password'||/^(current-password|new-password|one-time-code)$/.test(el.autocomplete);
   let manual=credential||control==='unsupported'||control==='file';
   const protectedText=text+' '+context+' '+description;
   if(boundary.test(protectedText)){manual=true;if(/captcha/i.test(protectedText))boundaries.add('captcha');else if(/payment|credit card/i.test(protectedText))boundaries.add('payment');else if(/password|passcode|verification code|sign in|log in|login/i.test(protectedText))boundaries.add('login');else if(/signature/i.test(protectedText))boundaries.add('signature');else boundaries.add('attestation');}
   let options=[];let members=null;let question=text;
   if(control==='radio'){
    const name=el.name;if(!name){manual=true;control='unsupported';}
    if(radios.has(name))continue;radios.add(name);
    members=[...document.querySelectorAll('input[type="radio"]')].filter(x=>x.name===name&&visible(x));options=members.map(label);question=groupLabel(el);
    if(new Set(options.map(norm)).size!==options.length)manual=true;
   }
   if(control==='select')options=[...el.options].filter(x=>!x.disabled&&x.value!=='').map(x=>clean(x.textContent));
   if(control==='checkbox')options=['Yes','No'];
   if(control==='combobox'){
    const list=comboList(el);
    options=list?[...list.querySelectorAll('[role="option"]')].map(x=>clean(x.textContent)):[];
    if(!options.length&&!el.getAttribute('aria-controls')&&!el.getAttribute('aria-owns')&&!comboInput(el)?.getAttribute('aria-controls')&&el.getAttribute('aria-haspopup')!=='listbox')manual=true;
   }
   if(new Set(options.map(norm)).size!==options.length)manual=true;
   const {section,container}=sectionInfo(el,text);
   let repeat_index=0;
   if(section&&container){if(!repeatGroups[section].includes(container))repeatGroups[section].push(container);repeat_index=repeatGroups[section].indexOf(container);}
   if(text.length>=500||description.length>=500||context.length>=500||options.some(x=>x.length>=500)||options.length>500){manual=true;options=[];}
   const group=el.closest('fieldset,[role="group"],[role="radiogroup"]');
   if(/veteran|disab|gender|race|ethnic|clearance/i.test(question+' '+context)&&group?.querySelector('p')&&!el.getAttribute('aria-describedby'))manual=true;
   const id='f'+fields.length;if(manual)manual_fields.push(id);
   const existing=credential?'':value(el);
   if(!credential&&placeholder(existing))review_existing.push(id);
   refs.set(id,{el,members,control,question,description,context,options,manual});snapshots.set(id,credential?null:members?members.map(value):existing);
   fields.push({id,label:question,description,context,control,autocomplete:clean(el.autocomplete).replace(/^section-\S+\s*/,'').replace(/^(shipping|billing)\s*/,''),options,has_value:credential?false:members?members.some(x=>x.checked||edited.has(x)):edited.has(el)||(control==='checkbox'?el.checked:control==='select'?!!el.value&&!emptyChoice(el.selectedOptions[0]?.textContent):control==='combobox'?!!String(existing).trim()&&!emptyChoice(existing):!!String(existing).trim()),required:!!el.required||el.getAttribute('aria-required')==='true',section,repeat_index});
  }
  // Mixed application pages can be filled without touching protected controls.
  // Keep page barriers for navigation, and pure login/payment pages fail closed.
  if(fields.some(f=>f.control==='unsupported'))boundaries.add('unsupported_control');
  const page_handoffs=[...boundaries];
  const applicationFields=fields.filter(f=>!manual_fields.includes(f.id)&&/name|address|city|postal|zip|country|state|school|degree|major|employer|job title|phone/i.test(f.label+' '+f.autocomplete));
  if(applicationFields.length)boundaries.clear();
  if(fields.length>120)boundaries.add('unsupported_control');
  const buttons=[...document.querySelectorAll('button,input[type="submit"],a[role="button"]')].filter(visible);
  const names=buttons.map(x=>clean(x.innerText||x.value||x.getAttribute('aria-label')));
  const reviewHeading=[...document.querySelectorAll('h1,h2,h3,[role="heading"]')].some(x=>visible(x)&&/final review|review (?:your )?application|confirm (?:your )?submission/i.test(clean(x.textContent)));
  const final_review=reviewHeading||names.some(x=>/^(submit|submit application|submit my application|send application|apply now|finish application|complete application)$/i.test(x));
  return {fields:fields.slice(0,120),boundaries:[...boundaries],final_review,metadata:{version:3,manual_fields:manual_fields.slice(0,120),review_existing:review_existing.slice(0,120),page_handoffs}};
 }
 function unchanged(id){
  const ref=refs.get(id);if(!ref||!ref.el.isConnected||!visible(ref.el)||ref.el.disabled||(ref.el.readOnly&&ref.control!=='combobox'))return false;
  if((ref.control==='radio'?groupLabel(ref.el):label(ref.el))!==ref.question)return false;
  const context=clean(ref.el.closest('fieldset,[role="group"],[role="radiogroup"]')?.querySelector('legend')?.textContent||'');
  const description=clean((ref.el.getAttribute('aria-describedby')||'').split(/\s+/).map(id=>{const x=document.getElementById(id);return x&&!x.closest('[role="status"],[role="alert"],[aria-live]')?x.textContent:'';}).join(' '));
  if(context!==ref.context||description!==ref.description)return false;
  const choices=ref.control==='radio'?ref.members.map(label):ref.control==='select'?[...ref.el.options].filter(x=>!x.disabled&&x.value!=='').map(x=>clean(x.textContent)):ref.control==='combobox'?[...(comboList(ref.el)?.querySelectorAll('[role="option"]')||[])].map(x=>clean(x.textContent)):ref.options;
  if(JSON.stringify(choices)!==JSON.stringify(ref.options))return false;
  return JSON.stringify(ref.members?ref.members.map(value):value(ref.el))===JSON.stringify(snapshots.get(id));
 }
 async function write(id,wanted,{replacePlaceholder=false}={}){
  const ref=refs.get(id);if(stopped||!ref)return {id,ok:false,reason:'conflict'};
  // Reject manual controls before reading their current value or snapshot.
  if(ref.manual)return {id,ok:false,reason:'manual_handoff'};
  if(!unchanged(id))return {id,ok:false,reason:'conflict'};
  const {el,members,control}=ref;
  const current=members?members.some(x=>x.checked):value(el);
  const occupied=control==='checkbox'?el.checked:control==='radio'?current:control==='select'?!!el.value&&!emptyChoice(el.selectedOptions[0]?.textContent):control==='combobox'?!!String(current).trim()&&!emptyChoice(current):!!String(current).trim();
  if(occupied&&!(replacePlaceholder&&placeholder(current)&&!edited.has(el)))return {id,ok:false,reason:'conflict'};
  if(ref.manual||['file','unsupported'].includes(control)||boundary.test(ref.question+' '+ref.context+' '+ref.description))return {id,ok:false,reason:'manual_handoff'};
  if(control==='checkbox'){
   if(!['Yes','No'].includes(wanted))return {id,ok:false,reason:'choice'};
   if(el.checked!==(wanted==='Yes'))el.click();
  }else if(control==='radio'){
   const choices=members.filter(x=>label(x)===wanted);if(choices.length!==1)return {id,ok:false,reason:'choice'};choices[0].click();
  }else if(control==='select'){
   const choices=[...el.options].filter(x=>!x.disabled&&clean(x.textContent)===wanted);if(choices.length!==1)return {id,ok:false,reason:'choice'};
   Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(el,choices[0].value);
  }else if(control==='combobox'){
   const options=()=>{const list=comboList(el);return list?[...list.querySelectorAll('[role="option"]')].filter(x=>visible(x)&&x.getAttribute('aria-disabled')!=='true'):[];};
   el.click();await new Promise(resolve=>setTimeout(resolve,100));
   const list=comboList(el);const input=comboInput(el)||(list?.id?document.querySelector('input[aria-controls="'+CSS.escape(list.id)+'"]'):null);
   const originalQuery=input?.value||'';
   if(input instanceof HTMLInputElement&&!options().some(x=>norm(x.textContent)===norm(wanted))){
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,wanted);
    input.dispatchEvent(new Event('input',{bubbles:true}));
   }
   let choices=[];
   for(let i=0;i<15;i++){
    if(stopped||edited.has(el)||input&&edited.has(input)||!el.isConnected||label(el)!==ref.question)return {id,ok:false,reason:'conflict'};
    choices=options().filter(x=>norm(x.textContent)===norm(wanted));
    if(choices.length)break;await new Promise(resolve=>setTimeout(resolve,100));
   }
   if(choices.length!==1){
    // Remove only our temporary query; never erase a concurrent user edit.
    if(input instanceof HTMLInputElement&&!edited.has(el)&&!edited.has(input)){Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,originalQuery);input.dispatchEvent(new Event('input',{bubbles:true}));}
    el.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
    return {id,ok:false,reason:'manual_handoff'};
   }
   choices[0].click();await new Promise(resolve=>setTimeout(resolve,50));
  }else{
   const prototype=el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
   Object.getOwnPropertyDescriptor(prototype,'value').set.call(el,wanted);
  }
  el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));
  const actual=control==='radio'?members.find(x=>x.checked):control==='select'?clean(el.selectedOptions[0]?.textContent):control==='checkbox'?(el.checked?'Yes':'No'):String(value(el));
  const ok=(control==='radio'?actual&&label(actual)===wanted:(control==='combobox'?norm(actual)===norm(wanted):actual===wanted))&&el.getAttribute('aria-invalid')!=='true'&&(!el.validity||el.validity.valid);
  return {id,ok:!!ok,reason:ok?'':'validation'};
 }
 function next(){
  if(stopped)return {ok:false,reason:'stopped'};
  const scan=inspect();if(scan.boundaries.length||scan.metadata.page_handoffs.length||scan.metadata.manual_fields.length||scan.final_review)return {ok:false,reason:'boundary'};
  if([...document.querySelectorAll('[aria-invalid="true"],input:invalid,select:invalid,textarea:invalid')].some(visible))return {ok:false,reason:'validation'};
  // Only literal ordinary Next/Continue controls; all mixed/ambiguous labels require a person.
  const candidates=[...document.querySelectorAll('button,input[type="button"],input[type="submit"]')].filter(x=>visible(x)&&!x.disabled&&/^(next|continue|save and continue)$/i.test(clean(x.innerText||x.value||x.getAttribute('aria-label'))));
  if(candidates.length!==1)return {ok:false,reason:'manual_handoff'};
  const button=candidates[0];const form=button.form;
  if(form){const dest=new URL(form.action||location.href,location.href);if(dest.origin!==location.origin||/\/(submit|final|complete|payment|checkout)(\/|$)/i.test(dest.pathname)||form.target&&form.target!=='_self')return {ok:false,reason:'origin_changed'};}
  const labelText=clean(button.innerText||button.value||button.getAttribute('aria-label'));
  button.click();return {ok:true,label:labelText};
 }
 globalThis.CareerCompanionDOM={inspect,write,next,stop:()=>{stopped=true;refs.clear();snapshots.clear();},version:4};
})();
