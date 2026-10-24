const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
let listener,fetches=0;
const runtime={id:'paired-extension',getURL:()=> 'chrome-extension://paired-extension/',onMessage:{addListener:fn=>listener=fn}};
const context={chrome:{runtime},location:{origin:'http://localhost:3000'},fetch:async()=>{fetches++;return {ok:true,json:async()=>({id:'account',csrf:'fictional-csrf'})};},Set,Error,JSON,AbortController,setTimeout,clearTimeout};
vm.runInNewContext(fs.readFileSync(require('node:path').resolve(__dirname,'../shared/relay.js'),'utf8'),context);
const request={channel:'career-companion-relay-v1',appOrigin:'http://localhost:3000',operation:'context',body:{pairing_id:'p'.repeat(32),secret:'s'.repeat(64)}};
for(const sender of [{id:'other',url:'chrome-extension://other/popup.html'},{id:'paired-extension',tab:{id:10},url:'https://employer.example/'},{id:'paired-extension',tab:{id:11},url:'http://localhost:3000/'},{id:'paired-extension',url:'https://employer.example/'},{}]){
 assert.equal(listener(request,sender,()=>{throw Error('Forged request reached reply');}),undefined);
}
assert.equal(fetches,0);
(async()=>{
 const good={id:'paired-extension',url:'chrome-extension://paired-extension/background.js'};
 const invalid=await new Promise(resolve=>listener({...request,operation:'filesystem'},good,resolve));assert.equal(invalid.ok,false);assert.equal(fetches,0);
 const result=await new Promise(resolve=>listener(request,good,resolve));assert.equal(result.ok,true);assert.equal(fetches,2);
 const tabReply=await new Promise(resolve=>listener(request,{...good,tab:{id:22},url:'chrome-extension://paired-extension/popup.html'},resolve));assert.equal(tabReply.ok,true);assert.equal(fetches,4);
 const manifest=JSON.parse(fs.readFileSync(require('node:path').resolve(__dirname,'../packages/chrome/manifest.json')));
 assert.deepEqual(manifest.permissions,['activeTab','scripting','storage']);assert(!manifest.host_permissions);assert(!manifest.externally_connectable);assert(!manifest.content_scripts);assert(!manifest.optional_host_permissions.includes('<all_urls>'));
 console.log('PASS: forged employer/page/foreign-extension requests rejected; relay is narrow, isolated and activation scoped.');
})().catch(e=>{console.error(e);process.exitCode=1;});
