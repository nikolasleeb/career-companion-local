import asyncio,json
from datetime import datetime,timezone
import pytest
from fastapi.testclient import TestClient
from app import db,onboarding,graduation_defaults as gd,role_catalog,provider_connections as pc,job_alerts,job_search,config,credentials
from app.main import app

def education(user,**kw):
 return db.save(user,'experience',{'category':'education','organization':'Fictional University','degree':'BS','title':'Computer science','confirmed':True,**kw})

def clear_education(user):
 for r in db.list_entities(user,'experience'):
  if r['data'].get('category')=='education':db.delete(user,r['id'])

@pytest.mark.parametrize('expected,types',[
 ('2027-07-24',['early_career']),('2027-07-25',['early_career']),('2027-07-26',['internship']),
 ('2027-07',['internship','early_career']),('2027',['internship','early_career']),('2027-06',['early_career']),('2027-08',['internship']),
 ('July 2027',['internship','early_career']),('unknown',['internship','early_career']),('', ['internship','early_career'])])
def test_precision_and_calendar_boundary(client,account,expected,types):
 clear_education(account['id']);education(account['id'],expected_graduation=expected)
 assert gd.for_profile(account['id'],'UTC',datetime(2026,10,25,tzinfo=timezone.utc))['job_types']==types

def test_multiple_degrees_completed_unknown_and_timezone(client,account):
 u=account['id'];education(u,expected_graduation='2028-05');education(u,expected_graduation='2027-05')
 assert gd.for_profile(u,'UTC',datetime(2026,10,25,tzinfo=timezone.utc))['job_types']==['early_career']
 education(u,expected_graduation='')
 assert gd.for_profile(u)['job_types']==gd.BOTH
 clear_education(u);education(u,end_date='2025-05')
 assert gd.for_profile(u)['job_types']==['early_career']
 clear_education(u);education(u,expected_graduation='2027-07-25');now=datetime(2026,10,25,0,30,tzinfo=timezone.utc)
 assert gd.for_profile(u,'UTC',now)['job_types']==['early_career']
 assert gd.for_profile(u,'America/Phoenix',now)['job_types']==['internship']

@pytest.mark.parametrize('program,role', [('Nursing','Nursing'),('Accounting','Accounting'),('Mechanical engineering','Mechanical engineering'),('Marketing','Marketing'),('Public health','Public health'),('Computer science','Software engineering')])
def test_confirmed_profile_suggestions_across_disciplines(client,account,program,role):
 u=account['id'];clear_education(u);education(u,title=program,major=program)
 assert role in role_catalog.suggestions(u)
 assert len(role_catalog.suggestions(u))<=4
 clear_education(u);education(u,title=program,major=program,confirmed=False)
 assert role_catalog.suggestions(u)==[]
 assert job_search.title_match('Registered Nurse New Graduate','Nursing')
 assert job_search.title_match('Junior Accountant','Accounting')

def test_sparse_profile_and_no_private_inference(client,account):
 clear_education(account['id']);education(account['id'],title='Diploma',degree='Diploma')
 assert role_catalog.suggestions(account['id'])==[]

def test_gate_optional_drafts_education_removal_and_workspace_preservation(client,account):
 u=account['id'];job=db.save(u,'job',{'title':'Saved work'})
 db.save(u,'experience',{'category':'project','title':'Draft Nursing project','confirmed':False})
 assert client.get('/api/onboarding').json()['completed']
 clear_education(u)
 # Old completion metadata, including imported grandfathering, cannot unlock.
 db.save(u,'onboarding',{'schema_version':1,'version':1,'empty_sections':[],'completed_at':db.now(),'grandfathered':True},onboarding.identity(u))
 assert not client.get('/api/me').json()['onboarding']['completed']
 for route in ('/api/jobs/search','/api/application-agent/runs','/api/job-search/preferences'):
  assert client.get(route).status_code in (403,405) if route=='/api/jobs/search' else client.get(route).status_code==403
 for route in ('/api/work-style','/api/resources'):
  assert client.get(route).status_code==200
 assert client.post('/api/jobs/search',json={}).status_code==403
 assert client.get('/api/workspace').json()['job']==[]
 assert db.get(u,job['id'])
 education(u)
 assert client.get('/api/onboarding').json()['completed']
 assert client.get('/api/workspace').json()['job'][0]['id']==job['id']

def test_legacy_choices_manual_and_restoring_automatic(client,account):
 u=account['id'];clear_education(u);education(u,expected_graduation='2090-05')
 db.save(u,'job_search_preferences',{'query':{'title':'Nursing','interests':['Nursing'],'location':'United States','job_types':['early_career'],'sources':['ashby']}},job_alerts.ident(u,'job_search_preferences'))
 data=client.get('/api/job-search/preferences').json();assert data['preferences']['data']['job_type_mode']=='manual'
 assert data['preferences']['data']['query']['job_types']==['early_career']
 payload={'query':data['preferences']['data']['query'],'timezone':'America/Phoenix','job_type_mode':'automatic'}
 assert client.put('/api/job-search/preferences',json=payload).json()['data']['query']['job_types']==['internship']
 data=client.get('/api/job-search/preferences').json();assert data['preferences']['data']['timezone']=='America/Phoenix'
 assert data['preferences']['data']['job_type_mode']=='automatic'
 payload['job_type_mode']='manual';payload['query']['job_types']=['early_career'];client.put('/api/job-search/preferences',json=payload)
 assert client.get('/api/job-search/preferences').json()['preferences']['data']['query']['job_types']==['early_career']
 assert client.put('/api/job-search/preferences',json={**payload,'timezone':'Invalid/Town'}).status_code==422

def test_provider_encryption_migration_no_fallback_and_one_call(client,account,monkeypatch):
 u=account['id'];calls=[]
 async def fetch(url,params,*args):calls.append(params);return {'results':[]}
 monkeypatch.setattr('app.integrations.fetch_json',fetch)
 monkeypatch.setattr(config,'ADZUNA_ID','forbidden-global-id');monkeypatch.setattr(config,'ADZUNA_KEY','forbidden-global-key')
 assert not job_alerts.capabilities(u)['adzuna']
 assert pc.migrate_trial(u,'student','fictional-id','fictional-trial-key')
 assert not pc.migrate_trial(u,'student','replace-id','different-key')
 assert not calls and pc.public(u)['test_only']
 result=asyncio.run(job_search.discover(u,job_alerts.SearchRequest(title='Data analyst',sources=['adzuna'])))
 assert not calls and result['sources'][0]['status']=='setup'
 with db.connect() as c:
  cipher=c.execute('SELECT ciphertext FROM cc_provider_connections WHERE user_id=?',(u,)).fetchone()[0]
 assert 'fictional' not in cipher
 assert 'fictional-trial-key' not in client.get('/api/account/export').text
 assert 'fictional-trial-key' not in client.get('/api/settings/job-connections').text
 assert client.post('/api/settings/job-connections/adzuna/test').status_code==200
 assert len(calls)==1 and calls[0]['results_per_page']==1
 revision=pc.public(u)['revision'];client.delete('/api/settings/job-connections/adzuna')
 assert pc.public(u)['revision']>revision and pc.resolve(u,testing=True) is None
 assert not pc.migrate_trial(u,'student','fictional-id','fictional-trial-key')

def test_two_account_concurrent_provider_resolution(client,account,monkeypatch):
 u=account['id']
 with TestClient(app,base_url='http://localhost') as other:
  user=other.post('/api/auth/register',json={'username':'second','password':'fictional-password'}).json();v=user['id'];education(v)
  pc.store(u,pc.Adzuna(app_id='first',app_key='first-secret',usage='regular'));pc.store(v,pc.Adzuna(app_id='second',app_key='second-secret',usage='regular'))
  calls=[]
  async def fetch(url,params,*args):
   await asyncio.sleep(0);calls.append(params['app_id']);return {'results':[]}
  monkeypatch.setattr('app.integrations.fetch_json',fetch)
  async def concurrent():await asyncio.gather(job_search.adzuna(u,'Nursing','US'),job_search.adzuna(v,'Accounting','US'))
  asyncio.run(concurrent())
  assert sorted(calls)==['first','second']
  assert pc.resolve(v)['app_key']=='second-secret'
  assert job_alerts.capabilities(u)['usajobs_scope']=='Shared connection'
  assert pc.public(u)['revision']==1


def test_cache_revision_and_catalog_version_and_no_implicit_role(client,account,monkeypatch):
 from test_app import wait
 u=account['id'];calls=[]
 data=client.get('/api/job-search/preferences?timezone=America/Phoenix').json()
 assert data['preferences']['data']['query']['interests']==[]
 assert data['preferences']['data']['query']['title']==''
 assert data['preferences']['data']['job_type_mode']=='automatic'
 async def discover(uid,request):
  calls.append(uid);return {'jobs':[],'sources':[],'query':request.model_dump(),'checked_at':db.now(),'ai_calls':[]}
 monkeypatch.setattr('app.integrations.discover',discover)
 body={'title':'Accounting','interests':['Accounting'],'sources':['ashby']}
 first=client.post('/api/jobs/search',json=body);assert first.status_code==200
 assert wait(client,first.json()['task_id'])['status']=='completed'
 assert client.post('/api/jobs/search',json=body).json()['cached']
 pc.store(u,pc.Adzuna(app_id='fixture-id',app_key='fixture-secret'))
 second=client.post('/api/jobs/search',json=body);assert 'task_id' in second.json()
 wait(client,second.json()['task_id']);assert len(calls)==2
 pc.remove({'id':u})
 third=client.post('/api/jobs/search',json=body);wait(client,third.json()['task_id']);assert len(calls)==3
 monkeypatch.setattr(job_search,'VERSION',job_search.VERSION+1)
 fourth=client.post('/api/jobs/search',json=body);wait(client,fourth.json()['task_id']);assert len(calls)==4


def test_provider_keys_do_not_restore_into_another_account(client,account):
 u=account['id'];pc.store(u,pc.Adzuna(app_id='fictional-id',app_key='fictional-secret'))
 backup=client.get('/api/account/export').json()
 assert 'fictional-secret' not in json.dumps(backup)
 other=client.post('/api/auth/register',json={'username':'restored_owner','password':'fictional-password'}).json()
 client.headers['X-CSRF-Token']=other['csrf']
 response=client.post('/api/account/import',files={'file':('fictional.json',json.dumps(backup),'application/json')})
 assert response.status_code==200,response.text
 assert client.get('/api/me').json()['onboarding']['completed']
 assert not pc.public(other['id'])['configured']
 assert pc.public(u)['configured']
 with pytest.raises(ValueError):pc.migrate_trial(other['id'],'wrong_owner','fictional-id','fictional-secret')
