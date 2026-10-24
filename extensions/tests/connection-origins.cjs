/* Safari-compatible match patterns must not weaken exact app-origin binding. */
const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const assert=require('node:assert/strict'),{webcrypto}=require('node:crypto');
const source=name=>fs.readFileSync(path.resolve(__dirname,'../shared',name),'utf8');

async function popup(origin,granted=true,keyboard=false){
 const elements=new Map(),requests=[],messages=[];
 const element=id=>{
  if(!elements.has(id))elements.set(id,{value:'',textContent:'',disabled:false});
  return elements.get(id);
 };
 const api={
  permissions:{request:async request=>{requests.push(request);return granted;}},
  runtime:{sendMessage:async message=>{
   messages.push(message);
   return {ok:true,result:message.action==='state'?{connection:{}}:{code:'123456'}};
  }}
 };
 const sandbox={browser:api,URL,document:{getElementById:element,querySelectorAll:()=>[]}};
 vm.runInNewContext(source('popup.js'),sandbox);
 element('origin').value=origin;
 if(keyboard){
  let prevented=false;
  await element('origin').onkeydown({key:'Enter',preventDefault:()=>{prevented=true;}});
  assert.equal(prevented,true);
 }else await element('connect').onclick();
 return {requests,messages,error:element('error').textContent};
}

async function background(origin,tabs){
 let listener;const queries=[],injections=[],relays=[],saved={};
 const api={
  runtime:{id:'test-extension',getURL:()=> 'safari-web-extension://test-extension/',onMessage:{addListener:fn=>listener=fn}},
  storage:{local:{get:async key=>({[key]:saved[key]}),set:async values=>Object.assign(saved,values),remove:async key=>{delete saved[key];}}},
  tabs:{query:async query=>{queries.push(query);return tabs;},sendMessage:async (tabId,message)=>{
   relays.push({tabId,message});return {ok:true,result:{id:'pair-id',code:'123456'},accountId:'account-id'};
  }},
  scripting:{executeScript:async details=>{injections.push(details);return [];}}
 };
 vm.runInNewContext(source('background.js'),{browser:api,URL,crypto:webcrypto,TextEncoder,setTimeout});
 const reply=await new Promise(resolve=>listener({channel:'career-companion-ui-v1',action:'connect',origin},
  {id:'test-extension',url:'safari-web-extension://test-extension/popup.html'},resolve));
 return {reply,queries,injections,relays,saved};
}

(async()=>{
 for(const [origin,pattern] of [
  ['http://localhost:3000','http://localhost/*'],
  ['http://127.0.0.1:3000','http://127.0.0.1/*'],
  ['http://127.0.0.1:3100','http://127.0.0.1/*']
 ]){
  const p=await popup(origin);
  assert.equal(p.error,'');assert.equal(p.requests[0].origins[0],pattern);
  assert.equal(p.messages.find(m=>m.action==='connect').origin,origin);
  const b=await background(origin,[
   {id:1,url:origin.replace(/:\d+$/,'')+':3999/',incognito:false},
   {id:2,url:origin+'/',incognito:true},
   {id:3,url:'https://employer.example/',incognito:false},
   {id:4,url:origin+'/applications',incognito:false}
  ]);
  assert.equal(b.reply.ok,true);assert.equal(b.queries[0].url,pattern);
  assert.equal(b.injections.length,1);assert.equal(b.injections[0].target.tabId,4);
  assert.equal(b.relays[0].tabId,4);assert.equal(b.relays[0].message.appOrigin,origin);
  assert.equal(b.saved.connection.appOrigin,origin);
 }
 const denied=await popup('http://localhost:3000',false);
 assert.match(denied.error,/Permission was not granted/);
 assert(!denied.messages.some(m=>m.action==='connect'));
 for(const origin of ['https://employer.example','http://localhost.evil.example:3000','http://user:password@localhost:3000','https://remote.example:444']){
  const p=await popup(origin);assert(p.error);assert.equal(p.requests.length,0);
  const b=await background(origin,[]);assert.equal(b.reply.ok,false);assert.equal(b.queries.length,0);
 }
 const wrongPort=await background('http://localhost:3000',[
  {id:1,url:'http://localhost:3100/'},{id:2,url:'http://localhost:3000/',incognito:true},{id:3,url:'not a URL'}
 ]);
 assert.equal(wrongPort.reply.ok,false);assert.match(wrongPort.reply.error,/Open and sign in/);
 assert.equal(wrongPort.injections.length,0);assert.equal(wrongPort.relays.length,0);
 const keyboard=await popup('http://localhost:3000',true,true);
 assert.equal(keyboard.error,'');assert.equal(keyboard.requests[0].origins[0],'http://localhost/*');
 assert.equal(keyboard.messages.filter(m=>m.action==='connect').length,1);
 const keyboardDenied=await popup('http://localhost:3000',false,true);
 assert.match(keyboardDenied.error,/Permission was not granted/);
 assert(!keyboardDenied.messages.some(m=>m.action==='connect'));
 console.log('PASS: port-free Safari permission/query patterns, exact origin selection, denied permissions and foreign/private tabs.');
})().catch(error=>{console.error(error);process.exitCode=1;});
