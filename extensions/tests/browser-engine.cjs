/* Genuine Chromium/WebKit DOM checks. This does not certify Safari extension installation. */
const {chromium,webkit}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');const path=require('node:path');const fs=require('node:fs');const http=require('node:http');
const root=path.resolve(__dirname,'../fixtures'),engine=path.resolve(__dirname,'../shared/engine.js');
(async()=>{
 const server=http.createServer((req,res)=>{const file=path.resolve(root,'.'+decodeURIComponent(req.url.split('?')[0]));if(!file.startsWith(root+path.sep)){res.writeHead(404).end();return;}try{res.setHeader('Content-Type','text/html');res.end(fs.readFileSync(file));}catch{res.writeHead(404).end();}});
 await new Promise(r=>server.listen(3219,'127.0.0.1',r));
 let checks=0;
 try{for(const type of (process.env.CHROME_ONLY?[chromium]:[chromium,webkit])){
  const browser=await type.launch({headless:true,...(process.env.CHROME_ONLY?{channel:'chrome'}:{})});const page=await browser.newPage();
  async function open(name){await page.goto('http://127.0.0.1:3219/'+name);await page.addScriptTag({path:engine});return page.evaluate(()=>CareerCompanionDOM.inspect());}
  async function inspect(){return page.evaluate(()=>CareerCompanionDOM.inspect());}
  async function write(label,value){const scan=await inspect();const id=scan.fields.find(f=>f.label===label)?.id;assert(id,'Missing '+label);return page.evaluate(([id,value])=>CareerCompanionDOM.write(id,value),[id,value]);}
  const scan=await open('native.html');assert.equal(scan.boundaries.length,0);checks++;
  assert.equal(scan.fields.find(f=>f.label==='City').has_value,true);checks++;
  assert.equal((await write('Email','fictional@example.test')).ok,true);assert.equal(await page.locator('#email').inputValue(),'fictional@example.test');checks++;
  await inspect();await page.locator('#name').fill('Manual edit after scan');const id=scan.fields.find(f=>f.label==='Full name').id;assert.equal((await page.evaluate(([id])=>CareerCompanionDOM.write(id,'Overwritten'),[id])).ok,false);assert.equal(await page.locator('#name').inputValue(),'Manual edit after scan');checks++;
  assert.equal((await write('Country','Canada')).ok,true);assert.equal(await page.locator('#country').inputValue(),'CA');checks++;
  assert.equal((await write('Are you a veteran?','Prefer not to answer')).ok,true);assert.equal(await page.locator('input[value="skip"]').isChecked(),true);checks++;
  assert.equal((await write('Send me recruiting updates','Yes')).ok,true);checks++;
  const before=await inspect();await page.locator('#country').evaluate(x=>x.options[2].textContent='Canada under a different definition');const cid=before.fields.find(x=>x.label==='Country').id;assert.equal((await page.evaluate(id=>CareerCompanionDOM.write(id,'Canada'),cid)).ok,false);checks++;
  await page.locator('#country').evaluate(x=>{const p=document.createElement('p');p.id='meaning';p.textContent='Current residence country';document.body.append(p);x.setAttribute('aria-describedby','meaning');});const meaningScan=await inspect();await page.locator('#meaning').evaluate(x=>x.textContent='Citizenship country');const meaningId=meaningScan.fields.find(x=>x.label==='Country').id;assert.equal((await page.evaluate(id=>CareerCompanionDOM.write(id,'United States'),meaningId)).ok,false);checks++;
  const upload=before.fields.find(f=>f.control==='file');assert.equal((await page.evaluate(id=>CareerCompanionDOM.write(id,'/private/file.pdf'),upload.id)).ok,false);checks++;
  assert.equal((await write('Choose a city','Phoenix')).ok,true);checks++;
  await page.evaluate(()=>CareerCompanionDOM.stop());assert.equal((await page.evaluate(()=>CareerCompanionDOM.next())).ok,false);checks++;
  await open('page2.html');let repeat=await inspect();assert.deepEqual(repeat.fields.filter(f=>f.label==='School name').map(f=>f.repeat_index),[0,1]);checks++;
  await page.locator('#dynamic').click();repeat=await inspect();assert.deepEqual(repeat.fields.filter(f=>f.label==='School name').map(f=>f.repeat_index),[0,1,2]);checks++;
  await page.evaluate(()=>CareerCompanionDOM.next());await page.waitForURL('**/review.html');await page.addScriptTag({path:engine});assert.equal((await inspect()).final_review,true);assert.equal((await page.evaluate(()=>CareerCompanionDOM.next())).ok,false);assert.notEqual(await page.locator('body').getAttribute('data-submitted'),'true');checks++;
  for(const [html,boundary] of [['<label>Password<input type="password"></label>','login'],['<label>Signature<input></label>','signature'],['<label>I certify that this is true<input type="checkbox"></label>','attestation'],['<label>Credit card<input></label>','payment'],['<iframe src="https://captcha.example/"></iframe>','captcha'],['<label>Custom control<div contenteditable="true"></div></label>','unsupported_control']]){
   await page.setContent(html);await page.addScriptTag({path:engine});assert((await inspect()).boundaries.includes(boundary),boundary);assert.equal((await page.evaluate(()=>CareerCompanionDOM.next())).ok,false);checks++;
  }
  await page.setContent(`<form action="/Register"><style>#email{position:absolute;top:20px}#city{position:absolute;top:120px}</style><label>City<input id="city"></label><label>Email<input id="email" type="email"></label><label>First name<input id="existing" value="Unknown"></label><label>Password<input id="password" type="password"></label><label>I acknowledge<input id="consent" type="checkbox"></label><button onclick="document.body.dataset.advanced='yes'">Save and continue</button></form>`);await page.addScriptTag({path:engine});
  const mixed=await inspect();assert.deepEqual(mixed.boundaries,[]);assert(mixed.metadata.page_handoffs.includes('login'));assert(mixed.fields.findIndex(f=>f.label==='Email')<mixed.fields.findIndex(f=>f.label==='City'));checks++;
  assert(mixed.metadata.review_existing.includes(mixed.fields.find(f=>f.label==='First name').id));checks++;
  // Even reading the password value must be unnecessary to inspect or reject writes.
  await page.locator('#password').evaluate(el=>Object.defineProperty(el,'value',{get(){throw Error('Credential value was read');},set(){throw Error('Credential value was changed');}}));
  assert.equal((await write('Email','fictional@example.test')).ok,true);assert.equal((await write('City','Fixture City')).ok,true);checks++;
  assert.equal((await write('Password','forbidden')).ok,false);assert.equal((await write('I acknowledge','Yes')).ok,false);assert.equal(await page.locator('#consent').isChecked(),false);checks++;
  assert.equal((await page.evaluate(()=>CareerCompanionDOM.next())).ok,false);assert.notEqual(await page.locator('body').getAttribute('data-advanced'),'yes');assert.equal(await page.locator('#existing').inputValue(),'Unknown');checks++;
  await open('mapping.html');const mapped=await inspect();
  assert.deepEqual(mapped.fields.filter(f=>f.label==='School').map(f=>[f.section,f.repeat_index]),[['education',0],['education',1]]);checks++;
  assert.deepEqual(mapped.fields.filter(f=>f.label.startsWith('As of today')).map(f=>f.repeat_index),[0,1]);checks++;
  assert.equal(mapped.fields.find(f=>f.label==='Job Title *').section,'employment');assert.equal(mapped.fields.find(f=>f.label==='Start Date *').control,'month');checks++;
  assert.equal(mapped.fields.find(f=>f.label.startsWith('Legally authorized')).section,'');checks++;
  assert.equal(mapped.fields.find(f=>f.label==='Country *').has_value,false);assert.equal((await write('Country *','United States')).ok,true);checks++;
  const legal=(await inspect()).fields.find(f=>f.label==='First name (legal) *').id;
  assert.equal((await page.evaluate(id=>CareerCompanionDOM.write(id,'Avery'),legal)).ok,false);assert.equal(await page.locator('#legal').inputValue(),'Unknown');checks++;
  assert.equal((await page.evaluate(id=>CareerCompanionDOM.write(id,'Avery',{replacePlaceholder:true}),legal)).ok,true);checks++;
  const chosen=(await inspect()).fields.find(f=>f.label==='First name (legal) *').id;assert.equal((await page.evaluate(id=>CareerCompanionDOM.write(id,'Different',{replacePlaceholder:true}),chosen)).ok,false);checks++;
  const school=(await inspect()).fields.find(f=>f.label==='School').id;assert.equal((await page.evaluate(id=>CareerCompanionDOM.write(id,'Fixture University'),school)).ok,true);assert.equal(await page.locator('#school0').inputValue(),'Fixture University');checks++;
  assert.equal((await write('Start Date *','2026-08')).ok,true);assert.equal(await page.locator('#start').inputValue(),'2026-08');checks++;
  assert.equal(await page.locator('#auth').inputValue(),'');assert.equal(await page.locator('#consent').isChecked(),false);assert.equal((await page.evaluate(()=>CareerCompanionDOM.next())).ok,false);checks++;
  await page.setContent(`<label>School<div id="wrapped" role="combobox" aria-label="School" aria-haspopup="listbox"><span id="selected">Select an option</span></div></label><script>document.querySelector('#wrapped').onclick=()=>{if(document.querySelector('#results'))return;let list=document.createElement('div');list.id='results';list.role='listbox';let query=document.createElement('input');query.setAttribute('aria-controls','results');query.oninput=()=>{list.innerHTML='';if(query.value==='Fixture University'){let opt=document.createElement('div');opt.role='option';opt.textContent=query.value;opt.onclick=()=>{document.querySelector('#selected').textContent=opt.textContent;list.remove();query.remove();};list.append(opt);}};document.body.append(query,list);document.querySelector('#wrapped').setAttribute('aria-controls','results');};</script>`);await page.addScriptTag({path:engine});
  const wrapped=await inspect();assert.equal(wrapped.fields.length,1);assert.equal(wrapped.fields[0].has_value,false);assert.equal(wrapped.metadata.manual_fields.length,0);checks++;
  assert.equal((await write('School','Fixture University')).ok,true);assert.equal(await page.locator('#selected').innerText(),'Fixture University');checks++;
  await open('native.html');await page.locator('button').evaluate(x=>x.textContent='Next and submit application');assert.equal((await page.evaluate(()=>CareerCompanionDOM.next())).ok,false);checks++;
  await browser.close();console.log(type.name()+': passed fictional controls, edits, changed options, boundaries, repeated/dynamic fields, navigation and uploads');
 }}finally{server.close();}
 console.log('PASS '+checks+' genuine-browser assertions ('+(process.env.CHROME_ONLY?'installed Google Chrome':'Chromium and WebKit')+'; not Safari extension acceptance).');
})().catch(e=>{console.error(e);process.exitCode=1;});
