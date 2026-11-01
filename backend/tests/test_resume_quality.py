"""Fictional checks for fresh critic context, bounded repairs and revision safety."""
import asyncio,base64,copy,json
import pytest
from fastapi import HTTPException
from app import ai,db,resume_quality as quality,resume_strategy as strategy,resume_conversation as guided
from app.models import FinalizeRevision,ResumeQualityRequest,ConversationMessage,WorkingRender
from app.network import ServiceError
from test_resume_strategy import scenario,provider,source
from test_guided_resume import env,build,request,response,META

READY={'strengths':['Clear relevant examples.'],'findings':[],'next_actions':[]}

def finding(kind='writing',material=True):
 return {'strengths':[],'findings':[{'kind':kind,'material':material,'issue':'The contribution needs clearer emphasis.','resume_quote':'','posting_quote':'Build digital solutions','action':'Clarify the relevant contribution using confirmed evidence.'}],'next_actions':['Review the relevant contribution.']}


def test_reviewer_is_separate_from_writer_and_final_source_audit(scenario,monkeypatch):
 calls=provider(monkeypatch,scenario)
 result=asyncio.run(guided.build(scenario[0],scenario[2]['id'],0,'custom'))
 critic=next(p for name,p in calls if name=='ResumeQualityReview')
 assert set(critic)=={'task','posting','resume'}
 assert 'professional_evidence' not in critic and 'strategy' not in critic and 'messages' not in critic
 assert calls[-1][0]=='DraftAudit'
 assert result['current']['data']['snapshot']['optimization']['quality_review']['status']=='ready'


@pytest.mark.parametrize('kind,material,expected,repair',[('evidence_gap',True,'needs_input',True),('writing',True,'needs_manual_changes',True),('selection',True,'needs_manual_changes',True),('presentation',True,'needs_manual_changes',True),('writing',False,'ready',False)])
def test_material_quality_issues_have_honest_verdicts_and_bounded_repair(scenario,monkeypatch,kind,material,expected,repair):
 calls=provider(monkeypatch,scenario);original=ai.structured
 async def model(schema,payload,*a,**kw):
  result,meta=await original(schema,payload,*a,**kw)
  if schema.__name__=='ResumeQualityReview':result=finding(kind,material)
  return result,meta
 monkeypatch.setattr(ai,'structured',model)
 state=asyncio.run(guided.build(scenario[0],scenario[2]['id'],0,'economy'))
 value=state['current']['data']['snapshot']['optimization']['quality_review']
 assert value['status']==expected and len(calls)<=8
 repairs=[p for name,p in calls if name=='ResumeComposition' and 'independent_feedback' in p]
 assert len(repairs)==1 # Exactly one writer revision, even when it preserves an already-good draft.
 if repair:assert repairs[0]['professional_evidence'] and repairs[0]['independent_feedback']['findings']


def test_blinded_comparison_keeps_original_on_tie_or_regression(scenario,monkeypatch):
 provider(monkeypatch,scenario);snap=source(scenario)
 snap.update(artifacts={'pdf':'eA=='},layout={'pages':1,'validated':True})
 other=copy.deepcopy(snap);other['headline']='Changed focus'
 monkeypatch.setattr(quality,'document',lambda s:{'text':s.get('headline',''),'checks':{}})
 monkeypatch.setattr(quality.secrets,'choice',lambda x:False)
 seen=[]
 async def judge(schema,payload,*a,**kw):
  seen.append(payload);assert set(payload)=={'task','posting','a','b'} and kw['retry_allowed'] is False
  return {'preferred':'tie','reason':'No meaningful improvement.','a':READY,'b':READY},META
 monkeypatch.setattr(ai,'structured',judge)
 chosen,review,meta,reason=asyncio.run(quality.compare(snap,other,'custom'))
 assert chosen is snap and review==READY and seen


@pytest.mark.parametrize('error',[ServiceError('Fictional review unavailable'),asyncio.CancelledError()])
def test_review_failure_or_cancellation_never_claims_success_or_retries(scenario,monkeypatch,error):
 calls=provider(monkeypatch,scenario);old=ai.structured
 async def fail(schema,payload,*a,**kw):
  if schema.__name__=='ResumeQualityReview':calls.append((schema.__name__,payload));raise error
  return await old(schema,payload,*a,**kw)
 monkeypatch.setattr(ai,'structured',fail)
 if isinstance(error,asyncio.CancelledError):
  with pytest.raises(asyncio.CancelledError):asyncio.run(guided.build(scenario[0],scenario[2]['id'],0,'economy'))
  assert not db.list_entities(scenario[0],'resume_revision')
 else:
  result=asyncio.run(guided.build(scenario[0],scenario[2]['id'],0,'economy'))
  assert result['current']['data']['snapshot']['optimization']['quality_review']['status']=='unavailable'
 assert sum(name=='ResumeQualityReview' for name,p in calls)==1


def test_fabricated_review_excerpt_is_rejected():
 bad=finding();bad['findings'][0]['resume_quote']='Invented excerpt'
 with pytest.raises(ServiceError,match='rendered resume'):quality.validate(bad,{'text':'Confirmed text.'},{'description':'Build digital solutions'})


def test_quality_acknowledgment_is_exact_revision_scoped_and_legacy_compatible(scenario,monkeypatch):
 provider(monkeypatch,scenario);state=asyncio.run(guided.build(scenario[0],scenario[2]['id'],0,'economy'));uid=scenario[0]
 revision=db.get(uid,state['current']['id'],'resume_revision');snap=revision['data']['snapshot'];snap['optimization']['quality_review']['status']='needs_manual_changes'
 db.save(uid,'resume_revision',revision['data'],revision['id'])
 body=dict(revision_id=revision['id'],expected_version=state['data']['version'],reviewed=True)
 with pytest.raises(HTTPException,match='409'):guided.finalize(uid,state['id'],FinalizeRevision(**body))
 saved=guided.finalize(uid,state['id'],FinalizeRevision(**body,quality_warning_acknowledged=True))
 assert db.get(uid,saved['data']['last_saved_resume_id'],'resume')['data']['quality_warning_acknowledged']
 assert quality.acknowledgment_required({'artifacts':{'pdf':'eA=='}}) is False


def test_changed_document_invalidates_quality_without_changing_history():
 old={'artifacts':{'pdf':'eA=='},'posting_snapshot':{'description':'Build digital solutions'}}
 old['optimization']={'quality_review':quality.stamp(old,READY)}
 new=copy.deepcopy(old);new['artifacts']['pdf']=base64.b64encode(b'new document').decode();quality.invalidate(new)
 assert new['optimization']['quality_review']['status']=='not_rechecked'
 assert old['optimization']['quality_review']['status']=='ready'


def test_recheck_preserves_bytes_factual_status_and_pending_feedback(scenario,monkeypatch):
 calls=provider(monkeypatch,scenario);uid=scenario[0];state=asyncio.run(guided.build(uid,scenario[2]['id'],0,'economy'))
 old=db.get(uid,state['current']['id'],'resume_revision')['data'];before=copy.deepcopy(old['snapshot'])
 def pending(d,c):d['pending_feedback']={'revision_instruction':'Retained separately.'}
 record=guided.mutate(uid,state['id'],state['data']['version'],pending)
 out=asyncio.run(guided.recheck_quality(uid,state['id'],ResumeQualityRequest(expected_version=record['data']['version'],revision_id=state['current']['id'],request_token='one-recheck')))
 new=db.get(uid,out['current']['id'],'resume_revision')['data']['snapshot']
 assert new['artifacts']==before['artifacts'] and new['optimization']['source_checked']==before['optimization']['source_checked']
 assert out['data']['pending_feedback']['revision_instruction']=='Retained separately.'
 assert len(calls)==7 and out['current']['id']!=state['current']['id']
 with pytest.raises(HTTPException):asyncio.run(guided.recheck_quality(uid,state['id'],ResumeQualityRequest(expected_version=0,revision_id=state['current']['id'],request_token='stale')))


def test_estimate_and_quality_reading_are_free_and_owner_scoped(scenario,monkeypatch):
 calls=provider(monkeypatch,scenario);state=asyncio.run(guided.build(scenario[0],scenario[2]['id'],0,'economy'));n=len(calls)
 assert guided.quality_estimate(scenario[0],state['id'],'economy')['usd'] is not None
 guided.state(scenario[0],state['id']);assert len(calls)==n
 with pytest.raises(HTTPException):guided.quality_estimate('another-account',state['id'],'economy')


@pytest.mark.parametrize('text,expected',[('• Shorten first bullet\n• Keep headline',2),('Use clearer words.\nKeep the meaning.',1),('• Shorten first bullet\n  preserve the number\n• Keep headline',2),('•\n-\n',0)])
def test_request_parsing_preserves_prose_and_continuations(text,expected):assert len(guided.request_items(text))==expected


def test_batch_defers_facts_and_conflicts_without_blocking_clear_edits():
 items=guided.request_items('• Shorten the first bullet\n• I led 40 people\n• Keep and remove the headline')
 results=[{'request_id':'R1','status':'updated','explanation':'Shorten.','instruction':'Shorten the first bullet.'},{'request_id':'R2','status':'updated','explanation':'Use new facts.','instruction':'I led 40 people'},{'request_id':'R3','status':'needs_clarification','explanation':'Contradictory requests.','instruction':''}]
 out=guided.request_results({'request_results':results},items,[{'fields':[{'user_quote':'I led 40 people'}]}])
 assert [r['status'] for r in out]==['updated','awaiting_approval','needs_clarification']
 assert not out[1]['instruction']


def test_batch_no_success_before_save_and_failed_revision_retains_list(env,monkeypatch):
 state=build(env);uid=env[0];text='• Shorten my first bullet\n• Keep my headline'
 async def chat(schema,payload,*a,**kw):
  return {**response(action='revise'),'request_results':[{'request_id':'R1','status':'updated','explanation':'Shortening.','instruction':'Shorten first bullet.'},{'request_id':'R2','status':'already_satisfied','explanation':'The headline is preserved.','instruction':''}]},META
 async def fail(*a,**kw):raise ServiceError('Fictional revision failed.')
 monkeypatch.setattr(ai,'structured',chat);monkeypatch.setattr(guided,'build',fail)
 with pytest.raises(ServiceError):asyncio.run(guided.send(uid,state['id'],ConversationMessage(text=text,expected_version=state['data']['version'])))
 after=guided.state(uid,state['id']);result=after['data']['messages'][-1]['request_results'][0]
 assert result['status']=='not_applied' and after['data']['last_message_input']==text and after['current']['id']==state['current']['id']


def test_empty_marker_request_starts_no_model_call(scenario,monkeypatch):
 calls=provider(monkeypatch,scenario)
 with pytest.raises(ServiceError,match='empty bullet'):asyncio.run(guided.send(scenario[0],scenario[2]['id'],ConversationMessage(text='•\n-',expected_version=0)))
 assert not calls


def test_mixed_batch_applies_clear_edit_without_dispatching_unapproved_facts(env,monkeypatch):
 from test_guided_resume import proposal
 state=build(env);uid=env[0];raw=ai.structured;seen=[]
 text='• Change my headline to Python data analysis\n• I managed forty people'
 proposed=proposal(env,text='I managed forty people')
 async def model(schema,payload,*args,**kwargs):
  if schema.__name__=='ResumeChatOutput':
   return {**response([proposed],action='revise'),'change_headline':True,'request_results':[
    {'request_id':'R1','status':'updated','explanation':'Update headline.','instruction':'Change the headline to Python data analysis.'},
    {'request_id':'R2','status':'awaiting_approval','explanation':'Review the new claim.','instruction':''}]},META
  if schema.__name__=='OptimizationOutput':
   seen.append(payload)
   assert 'I managed forty people' not in json.dumps(payload)
  return await raw(schema,payload,*args,**kwargs)
 monkeypatch.setattr(ai,'structured',model)
 out=asyncio.run(guided.send(uid,state['id'],ConversationMessage(text=text,expected_version=state['data']['version'])))
 assert seen and out['current']['id']!=state['current']['id']
 results=next(m['request_results'] for m in out['data']['messages'] if m.get('request_results'))
 assert [r['status'] for r in results]==['updated','awaiting_approval']
 assert out['data']['proposals'][-1]['status']=='pending'
 assert not any('forty' in str(r['data']) for r in db.list_entities(uid,'experience'))


def test_revised_document_gets_final_independent_check_with_bounded_layout_correction(scenario,monkeypatch):
 from app import resume_layout
 calls=provider(monkeypatch,scenario);raw=ai.structured;render=resume_layout.render
 def measured(snap):
  value=render(snap);item=next(i for e in strategy.entries(snap).values() for i in e['content_items'] if i['field']=='description')
  value['layout']['issues']=[{'kind':'dangling_words','item_id':item['item_id'],'text':'A short carryover line.'}]
  return value
 monkeypatch.setattr(resume_layout,'render',measured)
 monkeypatch.setattr(quality.secrets,'choice',lambda choices:False)
 async def model(schema,payload,*args,**kwargs):
  if schema.__name__=='ResumeQualityComparison':
   calls.append((schema.__name__,payload));assert set(payload)=={'task','posting','a','b'}
   return {'preferred':'b','reason':'Clearer supported cloud contribution.','a':finding(),'b':READY},META
  value,meta=await raw(schema,payload,*args,**kwargs)
  if schema.__name__=='ResumeQualityReview':value=READY if sum(n=='ResumeQualityReview' for n,p in calls)>1 else finding()
  if schema.__name__=='ResumeComposition' and payload.get('independent_feedback'):
   for entry in value['entries']:
    for item in entry['items']:
     if item['text'].startswith('Designed AWS ingestion'):item['text']='Designed AWS ingestion pipelines.'
  return value,meta
 monkeypatch.setattr(ai,'structured',model)
 out=asyncio.run(guided.build(scenario[0],scenario[2]['id'],0,'economy'))
 assert [name for name,p in calls]==['ResumeStrategy','ResumeComposition','ResumeQualityReview','ResumeComposition','OptimizationOutput','ResumeQualityReview','DraftAudit']
 assert out['current']['data']['snapshot']['optimization']['quality_review']['status']=='ready'


def test_quality_action_token_deduplicates_without_dispatching_twice(scenario,monkeypatch,client):
 from app import main
 import time
 calls=provider(monkeypatch,scenario);uid=scenario[0];state=asyncio.run(guided.build(uid,scenario[2]['id'],0,'economy'))
 monkeypatch.setattr(main,'require_ai',lambda *args:None)
 body={'revision_id':state['current']['id'],'expected_version':state['data']['version'],'request_token':'quality-unique-token','mode':'economy'}
 path='/api/resume-conversations/'+state['id']+'/quality-review'
 first=client.post(path,json=body);second=client.post(path,json=body)
 assert first.status_code==200 and second.status_code==200 and first.json()['task_id']==second.json()['task_id']
 task=first.json()['task_id']
 for _ in range(100):
  status=client.get('/api/tasks/'+task).json()
  if status['status'] not in ('queued','running'):break
  time.sleep(.01)
 assert status['status']=='completed',status
 assert sum(name=='ResumeQualityReview' for name,p in calls)==3


def test_source_changes_during_recheck_reject_late_output(scenario,monkeypatch):
 calls=provider(monkeypatch,scenario);uid=scenario[0];state=asyncio.run(guided.build(uid,scenario[2]['id'],0,'economy'));old=state['current']['id'];raw=ai.structured
 async def change(schema,payload,*args,**kw):
  result=await raw(schema,payload,*args,**kw)
  if schema.__name__=='ResumeQualityReview':
   record=scenario[3]['cloud'];db.save(uid,'experience',{**record['data'],'description':'Updated during the review.'},record['id'])
  return result
 monkeypatch.setattr(ai,'structured',change)
 with pytest.raises((ServiceError,HTTPException)):asyncio.run(guided.recheck_quality(uid,state['id'],ResumeQualityRequest(expected_version=state['data']['version'],revision_id=old,request_token='freshness')))
 assert guided.state(uid,state['id'])['current']['id']==old and len(calls)==7


def test_writer_revision_cannot_publish_unsupported_claim(scenario,monkeypatch):
 calls=provider(monkeypatch,scenario);raw=ai.structured
 async def bad_repair(schema,payload,*args,**kwargs):
  value,meta=await raw(schema,payload,*args,**kwargs)
  if schema.__name__=='ResumeQualityReview':value=finding()
  if schema.__name__=='ResumeComposition' and payload.get('independent_feedback'):
   item=next(item for entry in value['entries'] for item in entry['items'] if item['text'].startswith('Built a Python'))
   item['text']='Improved outcomes by 97%.'
  return value,meta
 monkeypatch.setattr(ai,'structured',bad_repair)
 with pytest.raises(ServiceError,match='unsupported number'):
  asyncio.run(guided.build(scenario[0],scenario[2]['id'],0,'economy'))
 assert not db.list_entities(scenario[0],'resume_revision')


def test_deferred_requests_cannot_expand_another_requests_edit_scope():
 results=[{'request_id':'R1','status':'updated','instruction':'Shorten this bullet.','target_item_ids':['safe-item'],'target_record_ids':[],'change_headline':False,'change_selection':False,'template':'unchanged'},
 {'request_id':'R2','status':'awaiting_approval','instruction':'','target_item_ids':['private-item'],'target_record_ids':['new-fact'],'change_headline':True,'change_selection':True,'template':'experience'}]
 out=guided.actionable_feedback({'change_headline':True,'change_selection':True,'template':'experience'},results)
 assert out['target_item_ids']==['safe-item'] and out['target_record_ids']==[]
 assert not out['change_headline'] and not out['change_selection'] and out['template']=='unchanged'


def test_conflicting_section_orders_defer_both_but_keep_the_headline_request():
 items=guided.request_items('• Set my headline\n• Education first\n• Experience first')
 results=[{'request_id':'R1','status':'updated','explanation':'Change headline.','instruction':'Set the headline.','change_headline':True,'template':'unchanged'},
 {'request_id':'R2','status':'updated','explanation':'Set order.','instruction':'Education first.','template':'education'},
 {'request_id':'R3','status':'updated','explanation':'Set order.','instruction':'Experience first.','template':'experience'}]
 checked=guided.request_results({'request_results':results},items,[])
 assert [r['status'] for r in checked]==['updated','needs_clarification','needs_clarification']
 output=guided.actionable_feedback({},checked)
 assert output['change_headline'] and output['template']=='unchanged' and output['revision_instruction']=='Set the headline.'


def test_source_audit_corrects_nonessential_coverage_without_blocking_truthful_draft():
 cov=[{'id':'team','included':True,'included_source_ids':['fact'],'essential':False}]
 checks={'approved':True,'issues':[],'coverage':[{'priority_id':'team','demonstrated':False,'explanation':'The final bullet describes individual ownership, not the shared work.'}]}
 result=strategy.audited_coverage(cov,checks)
 assert result[0]['included'] is False and result[0]['semantic_checked'] and result[0]['coverage_explanation']
 cov[0]['essential']=True
 with pytest.raises(ServiceError,match='essential'):strategy.audited_coverage(cov,checks)


def test_source_audit_cannot_claim_unselected_or_unknown_evidence():
 cov=[{'id':'sql','included':False,'included_source_ids':[],'essential':False}]
 for checks in [[{'priority_id':'other','demonstrated':False,'explanation':'Unavailable.'}],[{'priority_id':'sql','demonstrated':True,'explanation':'Claimed but not selected.'}]]:
  with pytest.raises(ServiceError):strategy.audited_coverage(cov,{'coverage':checks})


def test_headline_only_refinement_preserves_unrelated_selection_explanations():
 from app import optimization
 item={'item_id':'a','text':'Built a prototype.','original':'Built a prototype.','field':'description'}
 old={'source_id':'job','content_items':[item],'selection_reason':'Relevant reviewed prototype.'}
 source={'sections':[{'entries':[copy.deepcopy(old)]}]};current={**source,'headline':'Existing focus','optimization':{}}
 proposal={'headline':'New focus','headline_evidence':[],'entries':[{'record_id':'job','reason':'Paid internship evidence.','items':[{'item_id':'a','text':'Built a prototype.','priority':80,'reason':'Relevant.'}]}],'omissions':[{'record_id':'other','reason':'Unrequested new omission.'}]}
 result=optimization.constrain(proposal,source,current,{'change_headline':True})
 assert result['entries'][0]['reason']=='Relevant reviewed prototype.' and result['omissions']==[]
 assert result['entries'][0]['items'][0]['text']==item['text']
