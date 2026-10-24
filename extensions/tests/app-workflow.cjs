/* Browser + server + shared engine acceptance using fictional accounts and DOM only. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const fixture=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../../qa/ui-fixture.json')));
const engine=path.resolve(__dirname,'../shared/engine.js');
(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000}});const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  page.on('dialog',d=>d.accept());await page.goto('http://127.0.0.1:3100');
  await page.getByLabel('Username',{exact:true}).fill(fixture.username);await page.getByLabel('Password',{exact:true}).fill(fixture.password);await page.getByRole('button',{name:'Sign in',exact:true}).click();await page.getByRole('heading',{name:'Applications',exact:true}).waitFor();
  await page.evaluate(f=>localStorage.setItem('next-step-workspace:'+f.user_id,JSON.stringify({view:'agent',jobId:f.job_id,applicationId:f.application_id})),fixture);await page.reload();await page.getByRole('heading',{name:'Application Assistant',exact:true}).waitFor();
  const csrf=await page.evaluate(async()=> (await (await fetch('/api/me')).json()).csrf);
  async function api(route,body,method='POST'){const response=await context.request.fetch('http://127.0.0.1:3100/api'+route,{method,headers:{'X-CSRF-Token':csrf},...(body?{data:body}:{})});assert(response.ok(),response.status()+' '+await response.text());return response.json();}
  for(const packageName of ['chrome','safari']){const download=await context.request.get('http://127.0.0.1:3100/extensions/career-companion-'+packageName+'.zip');assert.equal(download.status(),200);assert.equal((await download.body()).subarray(0,2).toString(),'PK');}
  const secret='a'.repeat(64);const pair=await api('/application-agent/pairings/request',{secret,label:'Extension test fixture'});
  await page.getByRole('button',{name:'Approve matching code'}).click();await page.getByText('approved · code',{exact:false}).waitFor();
  const connection={pairing_id:pair.id,secret};let run=await api('/application-agent/runs',{...connection,application_id:fixture.application_id,resume_id:fixture.resume_id,allowed_origin:'http://127.0.0.1:3219',tab_id:12,documents_approved:true});
  // Use the browser DOM adapter on a fictional form; no extension permission is spoofed.
  const form=await context.newPage();await form.setContent('<h1>Fictional application</h1><label>Email<input id="email" type="email"></label><label>Are you a veteran?<select id="v"><option value="">Choose</option><option>Yes</option><option>No</option><option>Prefer not to answer</option></select></label><label>Manual note<input id="manual" value="Preserve this edit"></label>');await form.addScriptTag({path:engine});
  const scan=await form.evaluate(()=>CareerCompanionDOM.inspect());
  const plan=await api('/application-agent/runs/'+run.id+'/scan',{...connection,...scan,origin:run.allowed_origin,tab_id:12,signature:'b'.repeat(64),expected_version:run.version});run=plan.run;
  assert.deepEqual(plan.writes,[{id:'f0',value:'fixture@example.test'}]);
  for(const item of plan.writes){await api('/application-agent/runs/'+run.id+'/relay-status',connection);assert((await form.evaluate(x=>CareerCompanionDOM.write(x.id,x.value),item)).ok);}
  run=await api('/application-agent/runs/'+run.id+'/progress',{...connection,expected_version:run.version,origin:run.allowed_origin,tab_id:12,state:'needs_input',write_ids:['f0']});
  await page.getByRole('heading',{name:'Are you a veteran?',exact:true}).waitFor();
  await page.getByLabel('Your reviewed answer',{exact:true}).selectOption('Prefer not to answer');
  await page.getByLabel('I reviewed this answer and its meaning.').check();await page.getByRole('button',{name:'Use once',exact:true}).click();await page.getByRole('heading',{name:'Are you a veteran?',exact:true}).waitFor({state:'hidden'});
  await page.getByRole('button',{name:'Resume after review'}).click();await page.locator('.assistant-state strong').filter({hasText:/scanning/i}).waitFor();
  run=await api('/application-agent/runs/'+run.id,undefined,'GET');
  const nextScan=await form.evaluate(()=>CareerCompanionDOM.inspect());const plan2=await api('/application-agent/runs/'+run.id+'/scan',{...connection,...nextScan,origin:run.allowed_origin,tab_id:12,signature:'c'.repeat(64),expected_version:run.version});
  assert.deepEqual(plan2.writes,[{id:'f1',value:'Prefer not to answer'}]);
  assert((await form.evaluate(x=>CareerCompanionDOM.write(x.id,x.value),plan2.writes[0])).ok);assert.equal(await form.locator('#manual').inputValue(),'Preserve this edit');
  const downloaded=await context.request.get('http://127.0.0.1:3100/api/application-agent/runs/'+run.id+'/documents/'+fixture.resume_id);assert.equal(downloaded.status(),200);assert.equal(downloaded.headers()['content-type'],'application/pdf');
  await page.reload();await page.getByRole('heading',{name:'Application Assistant',exact:true}).waitFor();await page.screenshot({path:path.resolve(__dirname,'../../qa/assistant-desktop.png'),fullPage:true});
  await page.getByRole('button',{name:'I submitted this application',exact:true}).click();await page.getByRole('dialog').waitFor();assert.equal(await page.getByRole('dialog').locator('select').first().inputValue(),'applied');await page.getByRole('button',{name:'Cancel',exact:true}).click();
  const workspace=await api('/workspace',undefined,'GET');assert.equal(workspace.application.find(x=>x.id===fixture.application_id).data.status,'preparing');
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.resolve(__dirname,'../../qa/assistant-mobile.png'),fullPage:true});const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);assert.equal(overflow,false,'Mobile horizontal overflow');
  await page.getByRole('button',{name:'Profile',exact:true}).click();await page.getByRole('heading',{name:'Private application answers',exact:true}).waitFor();
  assert.equal(errors.length,0,errors.join('\n'));
  console.log('PASS: app sign-in, assistant restoration, pairing approval, local fill, private use-once review, resume, approved PDF handoff, tracker submission review without automatic status change, Profile vault access and 390px overflow checks.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
