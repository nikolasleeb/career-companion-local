"""Saved-result pagination and paid workflows verified with fictional sources only."""
import asyncio,copy,io,json
from datetime import datetime,timezone,date
import pytest
from reportlab.pdfgen import canvas
from app import db,job_results as results,job_ai,job_search,job_filters,job_locations,graduation_defaults as gd,ai,credentials,config,integrations as x
from app.models import SearchRequest
from app.network import ServiceError
from conftest import onboard_test_account

def run(c):return asyncio.run(c)
def posting(i=0,**extra):return {'title':'Data Analyst','company':'Fictional Employer','location':'Richmond, VA','country':'US','description':'Use SQL to analyze data. Bachelor degree required. No experience required.','url':'https://employer.example/jobs/'+str(i),'published_at':db.now(),'salary':'$70K - $90K per year','workplace':'hybrid','employment_type':'fulltime','hard_filter_status':'matches',**extra}
def saved(user,n=3):
 from app.resume_conversation import write
 records=[]
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE')
  for i in range(n):
   id=db.uid();data=posting(i,title='Data Analyst '+str(i),description=('Needle5634 SQL' if i==n-1 else 'Use SQL')+' to analyze data. Bachelor degree required. No experience required.');write(c,user,'job',data,id);records.append({'id':id,'data':data})
 return results.save_search(user,{'jobs':records,'query':SearchRequest(interests=['Data analysis'],sources=['ashby']).model_dump(),'sources':[],'checked_at':db.now(),'total_matches':n})

def test_5000_results_all_sizes_free_filter_and_account_scope(client,account,monkeypatch):
 u=account['id'];search=saved(u,5000)
 async def forbidden(*a,**k):raise AssertionError('Paging never invokes a provider')
 monkeypatch.setattr(ai,'structured',forbidden);monkeypatch.setattr(job_search,'discover',forbidden)
 for size in (25,50,100):
  response=client.get(f"/api/job-search/searches/{search['id']}/results?page_size={size}&page=2")
  assert response.status_code==200,response.text
  body=response.json();assert body['total']==5000 and len(body['jobs'])==size and body['pages']==5000//size
  assert 'description' not in body['jobs'][0]['data']
 found=client.get(f"/api/job-search/searches/{search['id']}/results?q=Needle5634").json();assert found['total']==1
 assert client.get(f"/api/job-search/searches/{search['id']}/jobs/{found['jobs'][0]['id']}").json()['data']['description'].startswith('Needle')
 assert client.get('/api/workspace?paged_jobs=true').json()['search'][0]['data'].get('jobs') is None
 assert client.get(f"/api/job-search/searches/{search['id']}/results?page_size=200").status_code==422
 other=client.post('/api/auth/register',json={'username':'other-paging','password':'fictional-password'}).json();onboard_test_account(other)
 assert client.get(f"/api/job-search/searches/{search['id']}/results").status_code==404

def test_561_legacy_membership_saved_and_filter_groups(client,account):
 s=saved(account['id'],561);rows=results.all_rows(account['id'],s['id']);assert len(rows)==561
 id=rows[0]['id'];d=rows[0]['data'];db.save(account['id'],'job',{**d,'interest_state':'saved'},id)
 assert client.get('/api/job-search/searches/saved/results?view=all').json()['total']==1
 assert client.get('/api/job-search/searches/saved/jobs/'+id).status_code==200
 changed=copy.deepcopy(rows);changed[1]['data'].update(hard_filter_status='uncertain',filter_reasons=['Pay unknown'])
 results.save_search(account['id'],{**s['data'],'jobs':changed},s['id'])
 assert client.get(f"/api/job-search/searches/{s['id']}/results?view=review").json()['total']==1
 assert client.get(f"/api/job-search/searches/{s['id']}/results").json()['total']==560
 # The version remains unchanged when the current job is edited.
 db.save(account['id'],'job',{**d,'description':'Later posting revision'},id)
 assert results.all_rows(account['id'],s['id'])[0]['data']['description']!='Later posting revision'

@pytest.mark.parametrize('location',['San Francisco','SF Office','San Francisco, CA - US','Aurora, Arapahoe County, Colorado'])
def test_known_western_locations_excluded(location):
 assert job_search.review(posting(location=location),SearchRequest(location='East Coast')) is None

def test_secondary_location_pay_and_ats_identity():
 job=posting(location='San Francisco',locations=[{'location':'San Francisco','state':'CA'},{'location':'New York, NY','state':'NY'}])
 assert job_search.review(job,SearchRequest(location='East Coast'))['matching_location']=='New York, NY, NY'
 assert job_search.review(posting(salary='$50K - $60K per year'),SearchRequest(minimum_salary=70000)) is None
 assert job_search.review(posting(salary='Not stated'),SearchRequest(minimum_salary=70000))['hard_filter_status']=='uncertain'
 assert job_search.review(posting(salary='Not stated'),SearchRequest())['hard_filter_status']=='matches'
 assert x.posting_key('https://jobs.ashbyhq.com/acme/a/application')==x.posting_key('https://jobs.ashbyhq.com/acme/a')
 assert x.posting_key('https://boards.greenhouse.io/acme/jobs/42?gh_jid=42')==x.posting_key('https://job-boards.greenhouse.io/acme/jobs/42')
 assert x.posting_key('https://jobs.ashbyhq.com/acme/a')!=x.posting_key('https://jobs.ashbyhq.com/acme/b')


def employment(user,start,end,**kw):return db.save(user,'experience',{'category':'employment','title':'Data Analyst','start_date':start,'end_date':end,'description':'SQL data analysis','confirmed':True,**kw})
def test_four_year_default_overlaps_precision_and_manual_override(client,account):
 u=account['id'];employment(u,'2022-10-25','2026-10-25');employment(u,'2023-01-01','2025-01-01')
 assert gd.relevant_months(u,['Data analysis'],date(2026,10,25))==48
 assert gd.for_profile(u,'UTC',datetime(2026,10,25,tzinfo=timezone.utc),['Data analysis'])['job_types']==['mid_career']
 assert gd.relevant_months(u,['Nursing'],date(2026,10,25))==0
 pref=client.get('/api/job-search/preferences').json()['preferences']['data']
 body={'query':{**pref['query'],'job_types':['internship'],'career_levels':['internship']},'job_type_mode':'manual','page_size':100}
 assert client.put('/api/job-search/preferences',json=body).status_code==200
 assert client.get('/api/job-search/preferences').json()['preferences']['data']['query']['job_types']==['internship']
 assert client.get('/api/job-search/preferences').json()['preferences']['data']['page_size']==100
 for r in db.list_entities(u,'experience'):
  if r['data'].get('category')=='employment':db.delete(u,r['id'])
 employment(u,'2022-10','2026-10');assert gd.relevant_months(u,[],date(2026,10,25))==47
 employment(u,'2020','2026',title='Data Analyst Intern');assert gd.relevant_months(u,[],date(2026,10,25))==47

def pdf(blank=False):
 f=io.BytesIO();c=canvas.Canvas(f)
 if not blank:c.drawString(40,700,'Data Analyst. Use SQL and Python. Bachelor degree required. Location Richmond VA.')
 c.showPage();c.save();return f.getvalue()
def test_private_pdf_examples_no_profile_import_and_backup(client,account,monkeypatch):
 before=db.list_entities(account['id'],'experience');raw=pdf()
 response=client.post('/api/job-search/ai/examples',files={'file':('example.pdf',raw)})
 assert response.status_code==200,response.text
 id=response.json()['id'];assert response.json()['ready']
 assert client.get('/api/job-search/ai/examples/'+id+'/download').content==raw
 assert len(db.list_entities(account['id'],'experience'))==len(before) and not db.list_entities(account['id'],'application')
 blank=client.post('/api/job-search/ai/examples',files={'file':('scan.pdf',pdf(True))}).json();assert not blank['ready']
 assert client.patch('/api/job-search/ai/examples/'+blank['id'],json={'text':'Data Analyst job with Python and SQL. Richmond, VA.'}).status_code==200
 assert client.post('/api/job-search/ai/examples',files={'file':('bad.pdf',b'bad')}).status_code==400
 backup=client.get('/api/account/export').json();assert id in backup['files']
 assert client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode())}).status_code==200
 other=client.post('/api/auth/register',json={'username':'other-examples','password':'fictional-password'}).json();onboard_test_account(other)
 assert client.get('/api/job-search/ai/examples').json()==[]
 assert client.get('/api/job-search/ai/examples/'+id+'/download').status_code==404

def test_professional_snapshot_no_drafts_or_private_fields(client,account):
 db.save(account['id'],'experience',{'confirmed':False,'title':'DraftSecret'})
 db.save(account['id'],'experience',{'confirmed':True,'category':'skills','title':'Skills','tools':'SQL, Python','description':'SQL dashboards\nCitizenship: PRIVATE_VALUE','location':'PrivateHome','organization':'PRIVATE_ORG'})
 value=json.dumps(job_ai.profile(account['id']));assert 'DraftSecret' not in value and 'PRIVATE_VALUE' not in value and 'PrivateHome' not in value and 'PRIVATE_ORG' not in value

def output(payload):
 return {'assessments':[{'job_id':j['id'],'fit':'possible','summary':'Some relevant evidence; verify requirements.','evidence':[{'profile_source_id':payload['profile_sources'][0]['id'],'profile_quote':payload['profile_sources'][0]['text'],'posting_quote':'SQL'}],'gaps':[],'unknowns':['Detailed duties need review.']} for j in payload['jobs']]}
def prepare_match(client,account,search,depth='quick',token='fictional-match'):
 credentials.save(account['id'],'sk-fictional-not-used')
 return job_ai.Match(search_id=search['id'],depth=depth,request_token=token)

def test_quick_matching_checkpoints_cancel_resume_and_no_discovery(client,account,monkeypatch):
 search=saved(account['id'],30);body=prepare_match(client,account,search);calls=[]
 async def fake(schema,payload,mode='economy',**kw):
  calls.append(payload);return output(payload),{'fictional':True}
 async def forbidden(*a,**k):raise AssertionError('Matching never rediscovers or uses Adzuna')
 monkeypatch.setattr(ai,'structured',fake);monkeypatch.setattr(job_search,'discover',forbidden)
 captured=[]
 def start(u,k,work,inputs):captured.append(work);return {'task_id':'fictional'}
 # Invoke the registered route through ASGI; real tasks persist their own checkpoints.
 from app.main import workers
 async def scenario():
  response=client.post('/api/job-search/ai/match',json=body.model_dump());assert response.status_code==200,response.text
  # TestClient's event loop owns this task; poll through its HTTP endpoint.
 import time
 response=client.post('/api/job-search/ai/match',json=body.model_dump());assert response.status_code==200,response.text
 for _ in range(100):
  r=client.get('/api/job-search/ai/matches').json()[0]
  if r['data']['state'] not in ('queued','running'):break
  time.sleep(.01)
 assert r['data']['state']=='completed',r
 assert r['data']['screened_count']==30 and r['data']['detailed_count']==25
 assert len(calls)==28 and r['data']['assessment_count']==30
 assert 'profile_snapshot' not in r['data']
 page=client.get(f"/api/job-search/searches/{search['id']}/results?sort=best&match_id={r['id']}").json();assert 'assessment' in page['jobs'][0]
 count=len(calls);assert client.post('/api/job-search/ai/match',json=body.model_dump()).json()['status']=='completed';assert len(calls)==count
 estimate=client.post('/api/job-search/ai/estimate',json=body.model_dump()).json();assert estimate['candidate_count']==30 and estimate['detailed']==25 and len(calls)==count
 db.save(account['id'],'experience',{'category':'skills','title':'SQL development','confirmed':True})
 assert client.get('/api/job-search/ai/matches/'+r['id']).json()['profile_changed']

def test_invalid_evidence_rejected_and_restart_has_no_automatic_ai(client,account,monkeypatch):
 search=saved(account['id'],1);profile=job_ai.profile(account['id']);rows=results.all_rows(account['id'],search['id'])
 payload={'profile_sources':profile['sources'],'jobs':[{'id':rows[0]['id']}]};value=output(payload)
 value['assessments'][0]['evidence'][0]['posting_quote']='INVENTED'
 with pytest.raises(ServiceError):job_ai.validate(value,rows,profile,'detailed')
 id=db.uid();db.save(account['id'],'ai_job_match',{'state':'running','profile_revision':profile['revision'],'use_profile':True,'search_id':search['id'],'assessments':{}},id)
 db.init();assert db.get(account['id'],id,'ai_job_match')['data']['state']=='interrupted'


def test_ai_discovery_criteria_private_no_key_fallback_and_trial_bound(client,account,monkeypatch):
 credentials.save(account['id'],'sk-fictional-not-used');monkeypatch.setattr(config,'ENABLE_WEB_SEARCH',True);calls=[]
 async def fake(schema,payload,mode='economy',**kw):
  assert 'profile_sources' not in payload
  return {'roles':['Data analysis'],'locations':['Richmond, VA'],'workplace':'any','career_levels':['mid_career'],'days':30,'minimum_salary':80000,'pay_period':'year','summary':'Data roles in Richmond from $80,000.','clarification':''},{'fictional':True}
 async def discover(u,request,**kwargs):calls.append(request);return {'jobs':[],'sources':[],'query':request.model_dump(),'ai_calls':[]}
 monkeypatch.setattr(ai,'structured',fake);monkeypatch.setattr(job_search,'discover',discover)
 value=run(job_ai.find(account['id'],job_ai.Discover(prompt='Find mid-career data roles in Richmond, VA from $80K per year.',request_token='fictional-discover')))
 assert value['kind']=='search' and calls[0].career_levels==['mid_career'] and calls[0].minimum_salary==80000
 assert calls[0].request_token=='fictional-discover' and calls[0].trial_roles is None


def test_cancel_keeps_batch_then_explicit_resume_skips_completed(client,account,monkeypatch):
 import time
 search=saved(account['id'],26);body=prepare_match(client,account,search,depth='full',token='cancel-then-resume');calls=[]
 async def fake(schema,payload,mode='economy',**kw):
  calls.append(payload['jobs'][0]['id'])
  if len(calls)==1:
   r=db.list_entities(account['id'],'ai_job_match')[0];job_ai.cancel(r['id'],account['id'])
  return output(payload),{'fictional':True}
 monkeypatch.setattr(ai,'structured',fake)
 response=client.post('/api/job-search/ai/match',json=body.model_dump());assert response.status_code==200
 for _ in range(100):
  r=client.get('/api/job-search/ai/matches').json()[0]
  if r['data']['state'] not in ('queued','running'):break
  time.sleep(.01)
 assert r['data']['state']=='cancelled' and r['data']['assessment_count']==1 and len(calls)==1
 response=client.post('/api/job-search/ai/matches/'+r['id']+'/resume?request_token=explicit-resume');assert response.status_code==200,response.text
 for _ in range(200):
  r=client.get('/api/job-search/ai/matches/'+r['id']).json()
  if r['data']['state']=='completed':break
  time.sleep(.01)
 assert r['data']['state']=='completed' and len(set(calls))==26 and len(calls)==26


def test_failed_paid_batch_remains_unknown_and_read_only_until_explicit_resume(client,account,monkeypatch):
 import time
 search=saved(account['id'],1);body=prepare_match(client,account,search,depth='full',token='unknown-paid-call');calls=[]
 async def failed(*a,**k):calls.append(1);raise ServiceError('Transport response unknown')
 monkeypatch.setattr(ai,'structured',failed)
 assert client.post('/api/job-search/ai/match',json=body.model_dump()).status_code==200
 for _ in range(100):
  r=client.get('/api/job-search/ai/matches').json()[0]
  if r['data']['state']=='failed':break
  time.sleep(.01)
 assert r['data']['in_flight'] and not r['data']['assessment_count'] and len(calls)==1
 assert client.get('/api/job-search/ai/matches/'+r['id']).status_code==200 and len(calls)==1
 backup=client.get('/api/account/export').json()
 assert client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode())}).status_code==200
 imported=next(v for v in client.get('/api/job-search/ai/matches').json() if v['data']['state']=='imported')
 assert client.post('/api/job-search/ai/matches/'+imported['id']+'/resume?request_token=import-resume').status_code==400
 assert len(calls)==1


def test_legacy_results_recheck_locations_without_refetch(client,account):
 west=db.save(account['id'],'job',posting(location='SF Office'))
 east=db.save(account['id'],'job',posting(1,location='New York, NY'))
 old=db.save(account['id'],'search',{'query':SearchRequest(location='East Coast').model_dump(),'jobs':[west,east],'sources':[]})
 data=client.get(f"/api/job-search/searches/{old['id']}/results").json()
 assert data['total']==1 and data['jobs'][0]['id']==east['id']
 assert db.get(account['id'],west['id'],'job') is not None


def test_application_reuse_known_ats_alias_keeps_distinct_requisitions(client,account):
 from app import applications
 one=db.save(account['id'],'job',posting(url='https://jobs.ashbyhq.com/example/a/application'))
 two=db.save(account['id'],'job',posting(url='https://jobs.ashbyhq.com/example/a'))
 three=db.save(account['id'],'job',posting(url='https://jobs.ashbyhq.com/example/b'))
 a=applications.start(account['id'],one['id']);assert applications.start(account['id'],two['id'])['id']==a['id']
 assert applications.start(account['id'],three['id'])['id']!=a['id']


def test_daily_history_summaries_survive_light_workspace(client,account):
 own=db.save(account['id'],'job',posting())
 with db.connect() as c:c.execute('INSERT INTO cc_job_alert_runs VALUES(?,?,?,?,?)',(account['id'],'2026-10-25','done',0,json.dumps({'new_jobs':[own['id']]})))
 assert not client.get('/api/workspace?paged_jobs=true').json()['search']
 body=client.get('/api/job-search/alerts/2026-10-25/jobs').json()
 assert body['jobs'][0]['id']==own['id'] and 'description' not in body['jobs'][0]['data']
 assert client.get('/api/job-search/alerts/2026-10-26/jobs').status_code==404
