"""Fictional role, pause/continue, provenance and exact-document checks. No provider access."""
import asyncio,copy,io
import pytest
from docx import Document
from app import ai,db,document_models,resume_conversation as guided,resume_strategy,cover_letters as letters
from app.models import DraftAudit,ResumeQualityReview,CoverGenerate,CoverContent,ExperienceItem,FinalizeRevision
from app.network import ServiceError
from test_resume_strategy import scenario,provider
from test_cover_letters import env

PAIR={'writer':{'model':'gpt-6.1-sol','reasoning_effort':'high','speed':'standard'},'reviewer':{'model':'gpt-5.6-terra','reasoning_effort':'medium','speed':'standard'}}
READY={'strengths':['Specific supported examples.'],'findings':[],'next_actions':[]}

def test_model_pair_owned_validated_and_does_not_replace_global_settings(client,account):
 before=db.settings(account['id'])
 assert client.get('/api/document-models').json()['pair'] is None
 assert client.put('/api/document-models',json=PAIR).status_code==200
 assert db.settings(account['id'])['document_models']==PAIR
 assert {k:v for k,v in db.settings(account['id']).items() if k!='document_models'}==before
 assert client.put('/api/document-models',json={**PAIR,'reviewer':PAIR['writer']}).status_code==422
 assert client.put('/api/document-models',json={**PAIR,'writer':{**PAIR['writer'],'reasoning_effort':'none'}}).status_code==422
 assert db.settings(account['id'])['document_models']==PAIR

def test_provider_dispatch_freezes_roles_and_keeps_reviewer_isolated(monkeypatch):
 seen=[]
 async def fake(body,**kw):
  import json
  seen.append(body)
  value=READY if body['text']['format']['name']=='ResumeQualityReview' else {'approved':True,'issues':[],'coverage':[]}
  return {'model':body['model'],'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(value)}]}],'usage':{'input_tokens':1000,'input_tokens_details':{'cached_tokens':200},'output_tokens':300}}
 monkeypatch.setattr(ai,'call_api',fake)
 token=ai._context.set({'process':'resume_guided','profile':{'document_models':copy.deepcopy(PAIR)}})
 async def cycle():
  _,writer=await ai.structured(DraftAudit,{'confirmed_sources':['fictional']})
  with document_models.role('reviewer'):
   _,reviewer=await ai.structured(ResumeQualityReview,{'document_text':'fictional','posting':'fictional'})
  assert ai.options('economy')['model']==PAIR['writer']['model']
  return writer,reviewer
 try:w,r=asyncio.run(cycle())
 finally:ai._context.reset(token)
 assert [b['model'] for b in seen]==[PAIR['writer']['model'],PAIR['reviewer']['model']]
 assert all(b['store'] is False for b in seen)
 assert w['document_role']=='writer' and r['document_role']=='reviewer'
 assert w['estimated_token_cost_usd']==pytest.approx(.00462)
 assert r['estimated_token_cost_usd']==pytest.approx(.00524)
 assert 'confirmed_sources' not in seen[1]['input']

def test_missing_model_pair_fails_before_provider():
 with pytest.raises(ServiceError,match='Choose and save'):document_models.configured({})


def test_resume_questions_pause_without_provider_and_resume_after_skip(scenario,monkeypatch):
 calls=provider(monkeypatch,scenario);uid,job,session,_=scenario
 record=guided.mutate(uid,session['id'],0,lambda d,c:d.update({'questions':[{'text':'What was your individual contribution?','reason':'Clarify the example.','status':'open'}],'asked_questions':[]}))
 result=asyncio.run(guided.build(uid,session['id'],record['data']['version'],'economy'))
 assert not calls and result['data']['optimization_waiting'] and not result['current']
 resumed=asyncio.run(guided.build(uid,session['id'],result['data']['version'],'economy',skip_questions=True))
 assert resumed['current'] and not resumed['data'].get('optimization_waiting')
 assert [n for n,p in calls]==['ResumeStrategy','ResumeComposition','ResumeQualityReview','ResumeComposition','ResumeQualityReview','DraftAudit']
 assert all(q['status']=='skipped' for q in resumed['data']['asked_questions'])


def test_resume_reviewer_feedback_precedes_revision_and_final_review(scenario,monkeypatch):
 calls=provider(monkeypatch,scenario)
 state=asyncio.run(guided.build(scenario[0],scenario[2]['id'],0,'economy'))
 revision=next(p for n,p in calls if n=='ResumeComposition' and 'first_draft' in p)
 assert revision['independent_feedback']==READY or revision['independent_feedback']['findings']==[]
 reviews=[p for n,p in calls if n=='ResumeQualityReview']
 assert len(reviews)==2 and all(set(p)=={'task','posting','resume'} for p in reviews)
 snapshot=state['current']['data']['snapshot']
 assert snapshot['optimization']['quality_review']['document_hash']
 from app import documents
 raw=copy.deepcopy(snapshot);raw.pop('artifacts',None)
 doc=Document(io.BytesIO(documents.export_resume(raw,'docx')[0]))
 assert doc.sections[0].left_margin.inches==.6
 assert any(p.text=='EDUCATION' for p in doc.paragraphs)
 assert any(p.paragraph_format.tab_stops for p in doc.paragraphs if '\t' in p.text)


def test_cover_loop_uses_extra_confirmed_profile_and_exact_saved_resume(env):
 uid,job,resume,state,calls=env
 db.save(uid,'experience',ExperienceItem(category='project',title='Separate SQL project',description='Built SQL checks for analytical data.',confirmed=True).model_dump())
 result=asyncio.run(letters.generate(uid,state['id'],CoverGenerate(expected_version=state['data']['version'],content=CoverContent.model_validate(state['data']['content']),skip_questions=True)))
 assert [n for n,p in calls]==['CoverLetterOutput','ResumeQualityReview','CoverLetterOutput','DraftAudit','ResumeQualityReview']
 assert any(r['id'].startswith('profile:') and 'SQL checks' in r['text'] for r in calls[0][1]['saved_resume_sources'])
 assert all('saved_resume_sources' not in p and 'conversation' not in p for n,p in calls if n=='ResumeQualityReview')
 current=result['current']['data'];assert current['resume_id']==resume['id'] and current['quality_review']['status']=='ready'
 assert current['profile_sources'] and not any('authorized_us' in str(x) for x in current['profile_sources'])


def test_cover_waiting_questions_do_not_generate_a_document(env,monkeypatch):
 uid,job,resume,state,calls=env;old=ai.structured
 async def model(schema,payload,*a,**kw):
  if schema.__name__=='CoverQuestionsOutput':return {'message':'A useful question.','questions':[{'text':'What did you decide in the analytical project?','purpose':'A concrete contribution.','topic':'story','source_ids':['resume:0:0:0'],'job_quote':'Analyst Intern','guidance_ids':[],'project_context_ids':[]}]},{'estimated_token_cost_usd':.001}
  return await old(schema,payload,*a,**kw)
 monkeypatch.setattr(ai,'structured',model)
 result=asyncio.run(letters.generate(uid,state['id'],CoverGenerate(expected_version=state['data']['version'],content=CoverContent.model_validate(state['data']['content']))))
 assert result['data']['optimization_waiting'] and not result['current']
 assert not any(n=='CoverLetterOutput' for n,p in calls)


def test_models_csrf_and_account_ownership(client,account):
 cookie=dict(client.cookies)
 assert client.put('/api/document-models',json=PAIR,headers={'X-CSRF-Token':'wrong'}).status_code==403
 assert client.put('/api/document-models',json=PAIR).status_code==200
 client.cookies.clear();client.headers.pop('X-CSRF-Token',None)
 assert client.get('/api/document-models').status_code==401
 second=client.post('/api/auth/register',json={'username':'second-document-user','password':'fictional-document-password'}).json()
 from conftest import onboard_test_account
 onboard_test_account(second)
 client.headers['X-CSRF-Token']=second['csrf']
 response=client.get('/api/document-models');assert response.status_code==200,response.text
 assert response.json()['pair'] is None
 reverse={'writer':PAIR['reviewer'],'reviewer':PAIR['writer']}
 assert client.put('/api/document-models',json=reverse).status_code==200
 client.cookies.clear();client.cookies.update(cookie);client.headers['X-CSRF-Token']=account['csrf']
 assert client.get('/api/document-models').json()['pair']==PAIR


def test_concurrent_roles_reset_on_failure_and_cancellation():
 async def actor(pair,break_with):
  token=ai._context.set({'process':'resume_guided','profile':{'document_models':copy.deepcopy(pair)}})
  try:
   writer=ai.options('economy')['model']
   try:
    with document_models.role('reviewer'):
     await asyncio.sleep(0)
     assert ai.options('economy')['model']==pair['reviewer']['model']
     raise break_with
   except (RuntimeError,asyncio.CancelledError):pass
   await asyncio.sleep(0)
   assert ai.options('economy')['model']==writer
  finally:ai._context.reset(token)
 async def run():await asyncio.gather(actor(PAIR,RuntimeError('fictional')),actor({'writer':PAIR['reviewer'],'reviewer':PAIR['writer']},asyncio.CancelledError()))
 asyncio.run(run())
 assert document_models._role.get()=='writer'


def test_task_settings_snapshot_survives_mid_run_change(client,account,monkeypatch):
 from app import credentials
 monkeypatch.setattr(credentials,'effective',lambda user:'fictional-key')
 uid=account['id'];db.update_settings(uid,{'document_models':PAIR})
 token=ai.set_user_context(uid,process='resume_guided')
 try:
  db.update_settings(uid,{'document_models':{'writer':PAIR['reviewer'],'reviewer':PAIR['writer']}})
  assert ai.options('economy')['model']==PAIR['writer']['model']
  with document_models.role('reviewer'):assert ai.options('economy')['model']==PAIR['reviewer']['model']
 finally:ai.reset_user_context(token)
 assert db.settings(uid)['document_models']['writer']['model']==PAIR['reviewer']['model']


def test_additional_cover_profile_sources_respect_sharing_and_revocation(env):
 from app import personalization
 uid,job,resume,state,calls=env
 db.save(uid,'experience',ExperienceItem(category='project',title='Extra confirmed source',description='Built SQL checks for analytical data.',confirmed=True).model_dump())
 sources=letters.professional_sources(uid,state['data']);assert sources
 record=letters.mutate(uid,state['id'],state['data']['version'],lambda d,c:d.update({'profile_sources':sources}))
 personalization.put(personalization.Change(expected_revision=0,enabled=False),{'id':uid})
 assert letters.professional_sources(uid,state['data'])==[]
 workspace,token=letters.begin(uid,state['id'],CoverGenerate(expected_version=record['data']['version'],content=CoverContent.model_validate(state['data']['content']),request_token='privacy-review'))
 assert workspace['data']['profile_sources']==[]
 assert all(not r['id'].startswith('profile:') for r in letters.sources(workspace['data']))
 # Frozen old revisions remain readable; no historical source or employer file is rewritten.
 assert sources


def test_same_quote_reduced_project_attribution_rejects_partial_revision_before_model(env,monkeypatch):
 from app.models import CoverEdit
 uid,job,resume,state,calls=env
 live={'id':'profile:unchanged-fact','label':'SQL Project · confirmed Profile','text':'Built SQL checks for analytical data.','record_id':'project','category':'project','field':'description','dates':'2026','allowed_destinations':['project','agency-job'],'allowed_attribution':[{'record_id':'project','title':'SQL Project','category':'project'},{'record_id':'agency-job','title':'Agency role','category':'employment'}]}
 monkeypatch.setattr(letters,'professional_sources',lambda *a:copy.deepcopy([live]))
 original=ai.structured;dispatches=[]
 async def writer(schema,payload,*a,**kw):
  dispatches.append(schema.__name__)
  if schema.__name__=='CoverLetterOutput':
   source=next(r for r in payload['saved_resume_sources'] if r['id']==live['id'])
   text='At the agency, I built SQL checks for analytical data.' if 'agency-job' in source['allowed_destinations'] else source['text']
   return {'paragraphs':[{'text':'I am applying for the Analyst Intern position.','evidence':[{'source_id':'posting','quote':'Analyst Intern'}]},{'text':text,'evidence':[{'source_id':source['id'],'quote':source['text']}]}],'summary':'A source-owned example.'},{'model':'fictional','estimated_token_cost_usd':0}
  return await original(schema,payload,*a,**kw)
 monkeypatch.setattr(ai,'structured',writer)
 body=CoverGenerate(expected_version=state['data']['version'],content=CoverContent.model_validate(state['data']['content']),skip_questions=True)
 first=asyncio.run(letters.generate(uid,state['id'],body));old_id=first['current']['id'];old=copy.deepcopy(db.get(uid,old_id,'cover_revision')['data'])
 live['allowed_destinations']=['project'];live['allowed_attribution']=live['allowed_attribution'][:1]
 edit=CoverGenerate(expected_version=first['data']['version'],content=CoverContent.model_validate(first['data']['content']),request_token='narrow-after-revocation')
 workspace,token=letters.begin(uid,state['id'],edit)
 assert workspace['data']['profile_sources'][0]['allowed_destinations']==['project']
 n=len(dispatches)
 with pytest.raises(ServiceError,match='allowed attribution changed'):
  asyncio.run(letters.draft(uid,workspace,token,edit,feedback={'revision_instruction':'Shorten the opening.','revise_all':False,'paragraph_indices':[0]}))
 assert len(dispatches)==n and db.get(uid,old_id,'cover_revision')['data']==old
 current=letters.state(uid,state['id'])
 with pytest.raises(ServiceError,match='allowed attribution changed'):
  asyncio.run(letters.render(uid,state['id'],CoverEdit(expected_version=current['data']['version'],content=CoverContent.model_validate(current['data']['content']),request_token='local-after-revocation')))
 assert len(dispatches)==n
 current=letters.state(uid,state['id'])
 rebuilt=asyncio.run(letters.generate(uid,state['id'],CoverGenerate(expected_version=current['data']['version'],content=CoverContent.model_validate(current['data']['content']),skip_questions=True)))
 assert rebuilt['current']['id']!=old_id and 'At the agency' not in str(rebuilt['current']['data']['content'])
 assert db.get(uid,old_id,'cover_revision')['data']==old
 assert rebuilt['current']['data']['profile_sources'][0]['allowed_destinations']==['project']


@pytest.mark.parametrize('revoke_during',['writer','audit'])
def test_partial_revision_revalidates_same_text_attribution_at_commit(env,monkeypatch,revoke_during):
 uid,job,resume,state,calls=env
 live={'id':'profile:stable-quote','label':'SQL Project','text':'Built SQL checks for analytical data.','record_id':'project','category':'project','field':'description','dates':'2026','allowed_destinations':['project','agency-job'],'allowed_attribution':[{'record_id':'project','title':'SQL Project'},{'record_id':'agency-job','title':'Agency role'}]}
 monkeypatch.setattr(letters,'professional_sources',lambda *a:copy.deepcopy([live]))
 original=ai.structured;partial=False;seen=[]
 async def model(schema,payload,*a,**kw):
  seen.append(schema.__name__)
  if partial and ((revoke_during=='writer' and schema.__name__=='CoverLetterOutput') or (revoke_during=='audit' and schema.__name__=='DraftAudit')):
   live['allowed_destinations']=['project'];live['allowed_attribution']=live['allowed_attribution'][:1]
  if schema.__name__=='CoverLetterOutput':
   row=next(r for r in payload['saved_resume_sources'] if r['id']==live['id'])
   return {'paragraphs':[{'text':'I am applying for the Analyst Intern position.','evidence':[{'source_id':'posting','quote':'Analyst Intern'}]},{'text':row['text'],'evidence':[{'source_id':row['id'],'quote':row['text']}]}],'summary':'A supported example.'},{'model':'fictional','estimated_token_cost_usd':0}
  return await original(schema,payload,*a,**kw)
 monkeypatch.setattr(ai,'structured',model)
 first=asyncio.run(letters.generate(uid,state['id'],CoverGenerate(expected_version=state['data']['version'],content=CoverContent.model_validate(state['data']['content']),skip_questions=True)))
 old_id=first['current']['id'];old=copy.deepcopy(db.get(uid,old_id,'cover_revision')['data']);partial=True;n=len(seen)
 body=CoverGenerate(expected_version=first['data']['version'],content=CoverContent.model_validate(first['data']['content']),request_token='mid-request-permission-change')
 workspace,token=letters.begin(uid,state['id'],body)
 with pytest.raises(ServiceError,match='allowed attribution changed during'):
  asyncio.run(letters.draft(uid,workspace,token,body,feedback={'revision_instruction':'Shorten the opening.','revise_all':False,'paragraph_indices':[0]}))
 assert seen[n:]==['CoverLetterOutput','DraftAudit']
 assert letters.state(uid,state['id'])['current']['id']==old_id and db.get(uid,old_id,'cover_revision')['data']==old


def test_real_canonical_profile_source_can_commit_inside_revision_transaction(env,monkeypatch):
 uid,job,resume,state,calls=env
 db.save(uid,'experience',ExperienceItem(category='project',title='Canonical SQL project',description='Built SQL checks for analytical data.',confirmed=True).model_dump())
 original=ai.structured
 async def model(schema,payload,*a,**kw):
  if schema.__name__=='CoverLetterOutput':
   row=next(r for r in payload['saved_resume_sources'] if r['id'].startswith('profile:') and r['text']=='Built SQL checks for analytical data.')
   return {'paragraphs':[{'text':'I am applying for the Analyst Intern position.','evidence':[{'source_id':'posting','quote':'Analyst Intern'}]},{'text':row['text'],'evidence':[{'source_id':row['id'],'quote':row['text']}]}],'summary':'A canonical source.'},{'model':'fictional','estimated_token_cost_usd':0}
  return await original(schema,payload,*a,**kw)
 monkeypatch.setattr(ai,'structured',model)
 from app.main import run_task,get_task
 from test_shared_progress import task
 identity=task(uid,'cover_letter')
 async def work():return await letters.generate(uid,state['id'],CoverGenerate(expected_version=state['data']['version'],content=CoverContent.model_validate(state['data']['content']),skip_questions=True))
 asyncio.run(run_task(identity,uid,work))
 completed=get_task(identity,user={'id':uid});assert completed['status']=='completed',completed
 result=completed['result']
 assert result['current']['data']['quality_review']['status']=='ready'
 assert result['current']['data']['evidence'][1]['evidence'][0]['source_id'].startswith('profile:')
