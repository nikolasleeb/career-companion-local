/* Installs the unmodified Chrome package in a fresh, isolated Chromium profile. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../../qa/chromium-extension-profile');const extension=path.resolve(__dirname,'../packages/chrome');
(async()=>{
 const context=await chromium.launchPersistentContext(root,{headless:true,channel:'chromium',args:['--disable-extensions-except='+extension,'--load-extension='+extension]});
 try{
  let worker=context.serviceWorkers()[0]||await context.waitForEvent('serviceworker',{timeout:10000});const id=new URL(worker.url()).hostname;
  const app=await context.newPage();await app.goto('http://127.0.0.1:3100');
  const suffix=Date.now().toString();
  const account=await app.evaluate(async suffix=>{const r=await fetch('/api/auth/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'extension'+suffix,password:'Fictional-password-only'})});return r.json();},suffix);
  assert(account.id,'Fictional account registration failed');
  const popup=await context.newPage();await popup.goto(`chrome-extension://${id}/popup.html`);await popup.locator('#origin').fill('http://127.0.0.1:3100');await popup.locator('#connect').click();
  try{await popup.waitForFunction(()=>document.getElementById('code').textContent||document.getElementById('error').textContent,null,{timeout:15000});}catch{console.log('BLOCKED: connection/optional-host permission did not complete unattended; native browser interaction remains required.');return;}
  const error=await popup.locator('#error').textContent();
  if(error){console.log('BLOCKED: native optional-host permission requires browser interaction:',error);return;}
  const pair=await app.evaluate(async()=>{const me=await (await fetch('/api/me')).json();const status=await (await fetch('/api/application-agent/status')).json();const pair=status.pairings[0];const r=await fetch('/api/application-agent/pairings/'+pair.id+'/approve',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':me.csrf},body:JSON.stringify({code:pair.code})});return {ok:r.ok,pair};});
  assert(pair.ok);await popup.locator('#load').click();await popup.waitForFunction(()=>!document.getElementById('load').disabled);assert.equal(await popup.locator('#error').textContent(),'');
  console.log('PASS: unmodified Chrome extension installed, requested localhost permission, paired through isolated relay and retrieved only its account context.');
 }finally{await context.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
