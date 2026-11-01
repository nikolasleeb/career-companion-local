"""Fictional accounts and stubbed provider; no external calls."""
import asyncio,copy,json
import pytest
from app import ai,db,applications,document_models,resume_conversation as guided,cover_letters as letters
from app.models import CoverStart,CoverGenerate,CoverContent,ExperienceItem,FinalizeRevision
from test_document_optimizer import PAIR,READY
from test_resume_strategy import scenario

SAME={role:copy.deepcopy(PAIR['writer']) for role in ('writer','reviewer')}

def test_same_models_preview_unsaved_roles_and_global_settings_unchanged(client,account,scenario,monkeypatch):
 uid,job,session,_=scenario
 before=copy.deepcopy(db.settings(uid))
 calls=[]
 async def forbidden(*a,**kw):calls.append(1);raise AssertionError('Estimate must not dispatch')
 monkeypatch.setattr(ai,'call_api',forbidden)
 low={role:{**v,'reasoning_effort':'low'} for role,v in SAME.items()}
 url='/api/resume-conversations/'+session['id']+'/estimate'
 a=client.post(url,json=low);b=client.post(url,json=SAME)
 assert a.status_code==b.status_code==200
 assert a.json()['usd']<b.json()['usd']
 assert b.json()['reasoning_effort']=='high'
 assert db.settings(uid)==before and not calls
 assert client.put('/api/document-models',json=SAME).status_code==200
 assert document_models.configured(db.settings(uid))==SAME
 invalid=client.post(url,json={**SAME,'reviewer':{**SAME['reviewer'],'model':'missing'}})
 assert invalid.status_code in (400,422)
 assert db.settings(uid)['document_models']==SAME


def test_profile_cover_scope_full_cycle_history_export_workflow_and_backup(client,account,monkeypatch):
 uid=account['id']
 fact='Built Python checks for analytical reports and presented the findings to classmates.'
 db.save(uid,'experience',ExperienceItem(category='project',title='Data quality study',description=fact,confirmed=True).model_dump())
 db.update_settings(uid,{'name':'Fictional Student','contact':'student@example.com','document_models':SAME,'authorized_us':'yes'})
 jobs=[client.post('/api/jobs',json={'title':'Data Analyst','company':name,'description':'Data Analyst\nPython analytical reports.'}).json() for name in ('Example Company','Other Company')]
 states=[letters.start(uid,CoverStart(job_id=j['id'],source_kind='profile')) for j in jobs]
 assert states[0]['id']!=states[1]['id']
 assert letters.start(uid,CoverStart(job_id=jobs[0]['id'],source_kind='profile'))['id']==states[0]['id']
 calls=[]
 async def model(schema,payload,*a,**kw):
  calls.append((schema.__name__,payload))
  if schema.__name__=='ResumeQualityReview':return READY,{'estimated_token_cost_usd':0}
  if schema.__name__=='DraftAudit':return {'approved':True,'issues':[]},{'estimated_token_cost_usd':0}
  rows=payload['saved_resume_sources'];row=next(r for r in rows if fact in r['text'])
  return {'paragraphs':[{'text':'I am applying for the Data Analyst position.','evidence':[{'source_id':'posting','quote':'Data Analyst'}]},{'text':fact,'evidence':[{'source_id':row['id'],'quote':fact}]}],'summary':'A grounded application letter.'},{'estimated_token_cost_usd':0}
 monkeypatch.setattr(ai,'structured',model)
 state=states[0]
 result=asyncio.run(letters.generate(uid,state['id'],CoverGenerate(expected_version=0,content=CoverContent.model_validate(state['data']['content']),skip_questions=True)))
 assert result['current']['data']['source_kind']=='profile'
 assert not result['current']['data']['resume_id']
 assert len(calls)==5
 assert all(set(p)=={'task','posting','letter_text','document_checks'} for n,p in calls if n=='ResumeQualityReview')
 assert 'authorized_us' not in json.dumps(calls)
 saved=letters.finalize(uid,state['id'],FinalizeRevision(expected_version=result['data']['version'],revision_id=result['current']['id'],reviewed=True))
 letter=db.get(uid,saved['data']['last_saved_letter_id'],'cover_letter')
 for fmt in ('pdf','docx','txt'):assert letters.export_data(letter['data'],fmt)[0]
 assert letters.state(uid,states[1]['id'])['saved_versions']==[]
 application=db.list_entities(uid,'application')[0] if db.list_entities(uid,'application') else applications.start(uid,jobs[0]['id'])
 # start before attach when the direct module call didn't create an application.
 letters.attach(uid,letter);applications.select_saved_letter(uid,letter)
 application=next(r for r in db.list_entities(uid,'application') if r['data']['job_id']==jobs[0]['id'])
 flow={**application['data']['workflow'],'step':'agent'}
 applications.validate_workflow(uid,application['data'],flow)
 assert flow['cover_source']=='profile' and not flow['resume_id']
 backup=client.get('/api/account/export').json()
 restored=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')})
 assert restored.status_code==200,restored.text
 assert len(db.list_entities(uid,'cover_letter'))==2


def test_missing_selected_resume_never_falls_back_to_profile(client,account):
 job=client.post('/api/jobs',json={'title':'Analyst','description':'Analytical work.'}).json()
 assert client.post('/api/cover-letters/workspace',json={'job_id':job['id'],'resume_id':'deleted'}).status_code==404
 assert client.post('/api/cover-letters/workspace',json={'job_id':job['id'],'resume_id':'deleted','source_kind':'profile'}).status_code==422
 foreign=client.post('/api/auth/register',json={'username':'other','password':'fictional-other-password'}).json()
 from conftest import onboard_test_account
 onboard_test_account(foreign)
 client.headers['X-CSRF-Token']=foreign['csrf']
 assert client.post('/api/cover-letters/workspace',json={'job_id':job['id'],'source_kind':'profile'}).status_code==404

def test_profile_mode_sharing_revocation_blocks_before_provider(client,account,monkeypatch):
 from app import personalization
 from fastapi import HTTPException
 uid=account['id'];job=client.post('/api/jobs',json={'title':'Analyst','description':'Python reports.'}).json()
 db.save(uid,'experience',ExperienceItem(category='project',title='Private unconfirmed',description='UNCONFIRMED FACT NEVER SHARED',confirmed=False).model_dump())
 db.update_settings(uid,{'authorized_us':'yes'})
 state=letters.start(uid,CoverStart(job_id=job['id'],source_kind='profile'))
 rows=letters.professional_sources(uid,state['data'])
 assert 'UNCONFIRMED FACT NEVER SHARED' not in json.dumps(rows)
 assert 'authorized_us' not in json.dumps(rows)
 personalization.put(personalization.Change(expected_revision=0,enabled=False),{'id':uid})
 calls=[]
 async def forbidden(*a,**kw):calls.append(1);raise AssertionError('No provider after revocation')
 monkeypatch.setattr(ai,'structured',forbidden)
 with pytest.raises(HTTPException,match='') as exc:
  asyncio.run(letters.generate(uid,state['id'],CoverGenerate(expected_version=0,content=CoverContent.model_validate(state['data']['content']),skip_questions=True)))
 assert exc.value.status_code==409 and not calls
 assert client.post('/api/cover-letters/workspace',json={'job_id':job['id'],'source_kind':'profile'}).status_code==409


def test_identical_role_requests_have_no_shared_provider_context(monkeypatch):
 seen=[]
 async def fake(body,**kw):
  seen.append(copy.deepcopy(body))
  value=READY if body['text']['format']['name']=='ResumeQualityReview' else {'approved':True,'issues':[],'coverage':[]}
  return {'model':body['model'],'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(value)}]}],'usage':{'input_tokens':1,'output_tokens':1}}
 monkeypatch.setattr(ai,'call_api',fake)
 token=ai._context.set({'process':'resume_guided','profile':{'document_models':SAME}})
 async def cycle():
  from app.models import DraftAudit,ResumeQualityReview
  await ai.structured(DraftAudit,{'writer_private_context':'WRITER ONLY'})
  with document_models.role('reviewer'):await ai.structured(ResumeQualityReview,{'document':'Finished text','posting':'Role','criteria':'Review the document only'})
 try:asyncio.run(cycle())
 finally:ai._context.reset(token)
 assert len(seen)==2 and seen[0]['model']==seen[1]['model']
 assert 'WRITER ONLY' not in json.dumps(seen[1])
 assert all(b.get('store') is False and not b.get('previous_response_id') and not b.get('conversation') for b in seen)
