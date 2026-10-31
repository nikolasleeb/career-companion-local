import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
let source=readFileSync(new URL('../src/appRoute.ts',import.meta.url),'utf8').replace(/^import .*from 'react';\n/,'');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const route=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));
const location={pathname:'/',search:'',hash:''},states=[];
globalThis.location=location;globalThis.history={state:null,replaceState(state,_,url){this.state=state;location.hash=url.includes('#')?'#'+url.split('#')[1]:'';states.push(['replace',url]);},pushState(state,_,url){this.state=state;location.hash='#'+url.split('#')[1];states.push(['push',url]);}};
test('routes only serialize navigation identities, never typed/private values',()=>{
 const hash=route.routeHash({view:'coach',tab:'plans',item:'abc123',question:'q1',prompt:'secret text',api_key:'secret-key'});
 assert.equal(hash,'#/career-plans?tab=plans&item=abc123&question=q1');assert(!hash.includes('secret'));
 assert.deepEqual(route.parseRoute('#/settings?tab=connections&api_key=secret'),{view:'settings',tab:'connections'});
 assert.equal(route.parseRoute('#assistant-run=abc'),null);assert.equal(route.parseRoute('#/unknown'),null);
});
test('unfinished root ignores remembered Resources but explicit resource links work',()=>{
 route.resetRoutes();location.hash='';route.initializeRoutes('one',false,{view:'coach',jobId:'old'});assert.equal(route.routeNow().view,'master');assert.equal(route.routeNow().tab,'upload');
 route.resetRoutes();location.hash='#/interview-practice?item=abc';route.initializeRoutes('two',false);assert.deepEqual(route.routeNow(),{view:'interviews',item:'abc'});
 route.resetRoutes();location.hash='#/applications?item=abc';route.initializeRoutes('three',false);assert.equal(route.routeNow().view,'master');
});
test('deliberate navigation pushes once; canonical updates replace and guards prevent loss',()=>{
 route.resetRoutes();location.hash='';route.initializeRoutes('four',true);states.length=0;
 route.setRoute({view:'settings',tab:'connections'});route.setRoute({view:'settings',tab:'connections'});assert.equal(states.length,1);assert.equal(states[0][0],'push');
 route.setRoute({view:'settings',tab:'usage'},true);assert.equal(states.at(-1)[0],'replace');
 const remove=route.routeGuard(()=>false);route.setRoute({view:'master'});assert.equal(route.routeNow().view,'settings');remove();
 route.setRoute({view:'master'});assert.equal(route.routeNow().view,'master');
});

test('legacy Work Styles links preserve attempt identities in canonical Profile workspace',()=>{
 assert.deepEqual(route.parseRoute('#/work-styles?item=attempt-1'),{view:'master',tab:'workstyles',item:'attempt-1'});
 assert.equal(route.routeHash({view:'interests',item:'attempt-1'}),'#/profile?tab=workstyles&item=attempt-1');
 route.resetRoutes();location.hash='#/work-styles?item=attempt-2';route.initializeRoutes('legacy',true);
 assert.deepEqual(route.routeNow(),{view:'master',tab:'workstyles',item:'attempt-2'});assert.equal(location.hash,'#/profile?tab=workstyles&item=attempt-2');
});

test('skill resource links retain a bounded topic and exact plan milestone references',()=>{
 const value={view:'prep',topic:'Patient communication',plan:'saved123',milestone:'step:abc'};
 assert.deepEqual(route.parseRoute(route.routeHash(value)),value);
 assert.deepEqual(route.parseRoute('#/skills?topic='+encodeURIComponent('x'.repeat(151))),{view:'prep'});
 assert.deepEqual(route.parseRoute('#/skills?topic='+encodeURIComponent('SQL\nsecret')),{view:'prep'});
 assert.equal(route.routeHash({view:'coach',item:'chat1',plan:'version2',milestone:'step:abc'}),'#/career-plans?item=chat1&plan=version2&milestone=step%3Aabc');
});
test('document stages and personalization deep links are explicit, bounded navigation fields',()=>{for(const stage of ['posting','resume','letter','finish'])assert.equal(route.parseRoute(route.routeHash({view:stage==='letter'?'cover':'tailor',job:'job',application:'app',stage})).stage,stage);assert.equal(route.parseRoute('#/resume?stage=unknown').stage,undefined);assert.deepEqual(route.parseRoute('#/profile?tab=personalization'),{view:'master',tab:'personalization'});});
