const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const script=fs.readFileSync(path.join(__dirname,'../shared/popup.js'),'utf8');
const doc=(id,time='2026-10-24T00:00:00')=>({id,title:id,updated_at:time});
const app=id=>({id,title:id,company:'Fictional',resume_ids:['r1','r2'],cover_letter_ids:[]});
const context={applications:[app('a1'),app('a2')],resumes:[doc('r1'),doc('r2')],cover_letters:[]};
let saved=null,now=1000,state={connection:{status:'approved',accountId:'fictional',appOrigin:'http://localhost:3100'},run:null,verified:0,lastError:'',lastContact:1000};
function popup(){let poll,contextLoads=0;const elements={};const element=id=>elements[id]??=( {value:'',textContent:'',checked:false,hidden:false,disabled:false,open:false,children:[],matches:()=>false,append(x){this.children.push(x);},replaceChildren(){this.children=[];this.value='';}} );
 const messages=[];const chrome={runtime:{sendMessage:async m=>{messages.push(m);let result={};if(m.action==='state')result={...state,selections:saved};if(m.action==='context'){contextLoads++;result=context;}if(m.action==='selection')saved={applicationId:m.applicationId,resumeId:m.resumeId,coverLetterId:m.coverLetterId,fingerprint:m.fingerprint};return {ok:true,result:JSON.parse(JSON.stringify(result))};}},permissions:{request:async()=>true}};
 const DateMock=class extends Date{static now(){return now;}};
 vm.runInNewContext(script,{chrome,Date:DateMock,URL,document:{getElementById:element,createElement:()=>({})},setInterval:(fn,ms)=>{assert.equal(ms,1000);poll=fn;}});
 return {element,messages,poll:()=>poll(),loads:()=>contextLoads};}
async function flush(){for(let i=0;i<10;i++)await new Promise(r=>setImmediate(r));}
(async()=>{let p=popup();await flush();assert.equal(p.loads(),1);assert.equal(p.element('application').value,'','Multiple applications require explicit selection');p.element('application').value='a2';await p.element('application').onchange();p.element('resume').value='r2';await p.element('resume').onchange();p.element('approved').checked=true;
 await p.poll();assert.equal(p.element('application').value,'a2');assert.equal(p.element('resume').value,'r2');assert.equal(p.element('approved').checked,true);assert.equal(p.loads(),1,'One-second status polls must not reset selections');
 p=popup();await flush();assert.equal(p.element('application').value,'a2');assert.equal(p.element('resume').value,'r2');assert.equal(p.element('approved').checked,false,'New-run sharing approval is not persisted');
 p.element('approved').checked=true;context.resumes[1].updated_at='2026-10-24T00:01:00';now+=31000;await p.poll();assert.equal(p.element('approved').checked,false,'Changed exact document version requires approval again');
 state={...state,run:{id:'run',state:'needs_input',questions:1,pages:1,writes:2,reason:''},verified:2,reviewVisited:false};await p.poll();assert.equal(p.element('start').textContent,'Review questions');assert(!p.messages.some(m=>m.action==='start'||m.action==='continue'));
 state.reviewVisited=true;await p.poll();assert.equal(p.element('start').textContent,'Resume filling');await p.element('start').onclick();assert.equal(p.messages.filter(m=>m.action==='continue').length,1);
 state.run.state='scanning';state.busy=false;await p.poll();assert.match(p.element('status').textContent,/Recovery needed/);assert.equal(p.element('start').textContent,'Resume filling');
 state.lastError='Login expired';state.connection.status='disconnected';await p.poll();assert.match(p.element('error').textContent,/Login expired/);assert(p.element('start').disabled);assert(!p.element('status').textContent.includes('scanning'));
 console.log('PASS popup: automatic load, one-second polling, retained explicit selections, fresh sharing approval, changed versions, one-button review/resume, inactive recovery and expired login.');
})().catch(e=>{console.error(e);process.exitCode=1;});
