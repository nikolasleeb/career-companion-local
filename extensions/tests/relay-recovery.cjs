/* Offline regression: restoring an app relay never retries a server request or starts filling. */
const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{webcrypto}=require('node:crypto');
const source=fs.readFileSync(path.join(__dirname,'../shared/background.js'),'utf8');
const clone=v=>v==null?v:JSON.parse(JSON.stringify(v));
const connection={appOrigin:'http://localhost:3100',relayTab:7,pairingId:'pair',secret:'f'.repeat(64),accountId:'account',employerTab:12,employerOrigin:'https://employer.example',runId:'r'.repeat(32)};
const run={id:'r'.repeat(32),account_id:'account',application_id:'application',pairing_id:'pair',tab_id:12,allowed_origin:'https://employer.example',state:'paused',reason:'connection_lost',version:4,pages:1,writes:2,unresolved:[],documents:{},expires:Date.now()/1000+3600};
function worker(options={}){
 let listener,ready=options.ready||false;const injections=[],calls=[];
 const memory={connection:clone(connection),lastRun:{...clone(run),questions:0},lastError:options.lastError??'Could not establish connection. Receiving end does not exist.',selections:{account:{applicationId:'application',resumeId:'resume',coverLetterId:'',fingerprint:'retained'}},receipt:{runId:run.id,version:4,baseline:2,ids:[]}};
 const api={runtime:{id:'test',getURL:()=> 'chrome-extension://test/',onMessage:{addListener:fn=>listener=fn}},storage:{session:{get:async k=>({[k]:clone(memory[k])}),set:async value=>Object.assign(memory,clone(value)),remove:async keys=>{for(const k of [].concat(keys))delete memory[k];}}},tabs:{get:async id=>{assert.equal(id,7);if(options.closed)throw Error('No tab with id');return {id,url:options.url||connection.appOrigin+'/#/resume',incognito:!!options.incognito};},query:async()=>[{id:12,url:'https://employer.example'}],sendMessage:async(id,message)=>{
  assert.equal(id,7);assert.equal(message.appOrigin,connection.appOrigin);assert.equal(message.accountId,'account');calls.push(message.operation);
  if(!ready)throw Error('Could not establish connection. Receiving end does not exist.');
  if(options.disconnect)throw Error(options.disconnect);
  return {ok:true,accountId:options.account||'account',result:message.operation==='overview'?{protocol_version:2,pairings:[{id:'pair',status:options.revoked?'revoked':'approved'}],runs:[clone(run)]}:{applications:[],resumes:[],cover_letters:[]}};
 }},scripting:{executeScript:async detail=>{assert.equal(detail.target.tabId,7);assert.equal(detail.world,'ISOLATED');assert.deepEqual([...detail.files],['relay.js']);injections.push(detail);if(options.denied)throw Error('Cannot access contents of tab');ready=true;return [];}}};
 vm.runInNewContext(source,{chrome:api,URL,crypto:webcrypto,TextEncoder,setTimeout,clearTimeout});
 const send=action=>new Promise(resolve=>listener({channel:'career-companion-ui-v1',action},{id:'test',url:'chrome-extension://test/popup.html'},resolve));
 return {send,memory,calls,injections};
}
(async()=>{
 const w=worker();let reply=await w.send('state');assert(reply.ok&&reply.result.connection.status==='approved');assert.equal(reply.result.lastError,'');assert.equal(reply.result.busy,false);assert.equal(reply.result.run.state,'paused');assert.equal(reply.result.verified,2);assert.equal(w.memory.selections.account.resumeId,'resume');assert.equal(w.memory.receipt.baseline,2);assert.equal(w.injections.length,1);assert.deepEqual(w.calls,['overview']);
 reply=await w.send('context');assert(reply.ok);assert.deepEqual(w.calls,['overview','context']);assert.equal(w.injections.length,2);assert.equal(w.memory.connection.runId,run.id);
 for(const options of [{closed:true},{url:'https://employer.example/'},{url:'http://localhost:3999/'},{incognito:true},{denied:true}]){
  const x=worker(options),r=await x.send('context');assert.equal(r.ok,false);assert.match(r.error,/Career Companion|reconnect/);assert.equal(x.calls.length,0);assert.equal(x.memory.selections.account.resumeId,'resume');
 }
 for(const error of ['Could not establish connection. Receiving end does not exist.','The message port closed before a response was received.']){
  const x=worker({disconnect:error}),r=await x.send('context');assert.equal(r.ok,false);assert.equal(x.calls.length,1,'Never replay a server operation with any outcome');assert.equal(x.memory.connection.runId,run.id);
 }
 const switched=worker({account:'different-account'});reply=await switched.send('state');assert(reply.ok);assert.equal(reply.result.connection.status,'disconnected');assert.equal(switched.memory.connection,undefined);assert.equal(switched.memory.selections,undefined);
 const revoked=worker({revoked:true});reply=await revoked.send('state');assert.equal(reply.result.connection.status,'revoked');assert.match(reply.result.lastError,/revoked/);
 const other=worker({lastError:'A field failed validation.'});reply=await other.send('state');assert.equal(reply.result.lastError,'A field failed validation.');
 assert(!w.calls.some(c=>['create','scan','control','progress'].includes(c)));
 console.log('PASS relay recovery: exact paired app tab, refresh recovery, retained selections/receipts, no automatic filling or server retries, closed/foreign/private/denied tabs, changed accounts and revoked pairings.');
})().catch(e=>{console.error(e);process.exitCode=1;});
