import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const compile=p=>ts.transpileModule(readFileSync(new URL(p,import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const apiURL='data:text/javascript;base64,'+Buffer.from(compile('../src/apiClient.ts')).toString('base64');
const api=await import(apiURL);
const source=compile('../src/coachRecovery.ts').replace("'./apiClient'",JSON.stringify(apiURL));
const coach=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const storage=()=>{const values=new Map();return {getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k),values};};
test('unconfirmed coach actions are scoped by both account and chat, without storing prompts',async()=>{
 const s=storage();const calls=[];const call=async(path,method,body)=>{calls.push(body);throw new api.ApiError('offline');};
 await assert.rejects(()=>coach.coachAction('a','goal-one',{operation:'message',text:'private career goals'},call,null,s));
 const first=coach.pendingCoach('a','goal-one',s);assert.ok(first.token);assert.equal(JSON.stringify([...s.values.values()]).includes('private career goals'),false);
 assert.equal(coach.pendingCoach('b','goal-one',s),null);assert.equal(coach.pendingCoach('a','goal-two',s),null);
 await assert.rejects(()=>coach.coachAction('a','goal-one',{operation:'message',text:'private career goals'},call,null,s));assert.equal(calls[0].request_token,calls[1].request_token);
 await assert.rejects(()=>coach.coachAction('a','goal-one',{operation:'message',text:'different goals'},call,null,s),/saved status/);assert.equal(calls.length,2);
});
test('coach status recovery performs only GET and restores the saved result',async()=>{
 const s=storage();await assert.rejects(()=>coach.coachAction('a','goal-one',{operation:'plan'},async()=>{throw new api.ApiError('offline');},null,s));
 const calls=[];const result=await coach.recoverCoach('a','goal-one',async(path,method)=>{calls.push(path);assert.equal(method,undefined);return path.includes('/actions/')?{task_id:'saved-task'}:{status:'completed',result:{id:'saved-reply'}};},null,s);
 assert.equal(result.id,'saved-reply');assert.equal(calls.length,2);assert.equal(coach.pendingCoach('a','goal-one',s),null);
});
test('expired sign-in retains the unconfirmed action for read-only recovery',async()=>{
 const s=storage();await assert.rejects(()=>coach.coachAction('a','one',{operation:'plan'},async()=>{throw new api.ApiError('session expired',401);},null,s));assert.ok(coach.pendingCoach('a','one',s));
 await assert.rejects(()=>coach.recoverCoach('a','one',async()=>{throw new api.ApiError('access expired',403);},null,s));assert.ok(coach.pendingCoach('a','one',s));
});
test('draft lookup cannot cross account or goal boundaries',()=>{
 const s=storage();s.setItem('career-coach-draft:a:one','One goal question');s.setItem('career-coach-draft:b:one','Another account question');
 assert.equal(coach.initialCoachDraft('a','one','',s),'One goal question');assert.equal(coach.initialCoachDraft('b','one','',s),'Another account question');assert.equal(coach.initialCoachDraft('a','two','',s),'');
});
test('a sent reply clears only the submitted draft and preserves newly typed text',()=>{
 assert.equal(coach.draftAfterSend('Original question','Original question'),'');assert.equal(coach.draftAfterSend('Next question typed while waiting','Original question'),'Next question typed while waiting');
});
test('account deletion clears only that account’s coach references and drafts',()=>{
 const make=()=>{const m=new Map();return {get length(){return m.size;},key:i=>[...m.keys()][i]??null,getItem:k=>m.get(k)||null,setItem:(k,v)=>m.set(k,v),removeItem:k=>m.delete(k)};};const l=make(),s=make();
 for(const v of [l,s]){v.setItem('career-coach-action:a:one','token');v.setItem('career-coach-draft:a:one','private draft');v.setItem('career-coach-selected:a','one');v.setItem('career-coach-draft:b:one','other draft');}
 coach.clearCoachBrowser('a',l,s);assert.equal(l.length,1);assert.equal(s.length,1);assert.equal(s.getItem('career-coach-draft:b:one'),'other draft');
});
