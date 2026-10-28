"""Fictional sources only: no network, model calls, or trial quota consumption."""
import asyncio,json,time,copy
from datetime import datetime,timezone,timedelta
import pytest
from app import db,config,job_search as search,public_job_feeds as feeds,provider_connections as pc,integrations as x,job_alerts
from app.models import SearchRequest
from app.network import ServiceError
from conftest import onboard_test_account

def run(value):return asyncio.run(value)
def posting(i=0,company='Example',**extra):
 return x.normalize_job('ashby','Data Analyst',company,'Richmond, VA','Bachelor degree. Full-time. No experience required.',f'https://employer.example/jobs/{company}/{i}',source_identity=f'ashby:{company}:{i}',origin_key='ashby:'+company,country='US',employment_type='fulltime',published_at=db.now(),salary='$60000',**extra)
def owner(monkeypatch,u):
 monkeypatch.setattr(pc,'trial_owner',lambda user:user==u)
def mode(client,usage):return client.patch('/api/settings/job-connections/adzuna/mode',json={'usage':usage})
def setup_trial(client,account,monkeypatch):
 owner(monkeypatch,account['id']);pc.store(account['id'],pc.Adzuna(app_id='owner-id',app_key='owner-secret'))
 assert mode(client,'manual_trial').status_code==200

def test_catalog_has_verified_unique_boards():
 rows=feeds.CATALOG['employers']
 assert len(rows)>=299 and len({feeds.board_key(b) for b in rows})==len(rows)
 assert {r['provider'] for r in rows}=={'greenhouse','ashby','lever'}
 assert all(r['identity_label'] and r['verified_at'] and r['verified_job_count']>=0 and r['career_url'].startswith('https://') for r in rows)
 assert feeds.CATALOG['attribution']['license']=='CC BY 4.0'

def test_mode_changes_preserve_ciphertext_and_other_accounts(client,account,monkeypatch):
 u=account['id'];owner(monkeypatch,u);pc.store(u,pc.Adzuna(app_id='private-id',app_key='private-secret'))
 before=dict(pc.row(u));assert mode(client,'manual_trial').status_code==200
 assert pc.row(u)['ciphertext']==before['ciphertext'] and pc.public(u)['revision']==before['revision']+1
 assert pc.resolve(u) is None and pc.resolve(u,manual=True)['app_id']=='private-id'
 assert mode(client,'manual_trial').status_code==200 and pc.public(u)['revision']==before['revision']+1
 other=client.post('/api/auth/register',json={'username':'other-owner','password':'fictional-other-password'}).json();onboard_test_account(other);client.headers['X-CSRF-Token']=other['csrf']
 assert client.get('/api/settings/job-connections').json()['adzuna']['configured'] is False
 assert mode(client,'manual_trial').status_code==403
 assert not pc.resolve(other['id'],manual=True)
 assert 'private-secret' not in client.get('/api/account/export').text

def test_trial_two_calls_total_and_durable_duplicates(client,account,monkeypatch):
 setup_trial(client,account,monkeypatch);calls=[]
 async def fetch(url,params=None,headers=None):
  calls.append((url,params));assert params['results_per_page']==25 and params['app_id']=='owner-id'
  return {'results':[{'id':str(len(calls)),'title':'Data Analyst','location':{'display_name':'Richmond, VA'},'company':{'display_name':'Example'},'redirect_url':'https://www.adzuna.com/land/ad/'+str(len(calls)),'created':db.now()}]*25}
 monkeypatch.setattr(x,'fetch_json',fetch)
 req=SearchRequest(interests=['Data analysis','Data engineering','Marketing'],sources=['adzuna'],request_token='fictional-request')
 result=run(search.discover(account['id'],req))
 assert len(calls)==2 and all(url.endswith('/1') for url,_ in calls)
 assert result['adzuna_trial']['roles']==req.interests[:2] and result['adzuna_trial']['attempted_requests']==2
 again=run(search.discover(account['id'],req));assert len(calls)==2 and again['adzuna_trial']['attempted_requests']==0
 assert pc.public(account['id'])['installation_requests']==2
 with db.connect() as c:assert c.execute('SELECT count(*) FROM cc_public_job_snapshots').fetchone()[0]==0

def test_trial_failure_stops_without_retry_retains_other_sources(client,account,monkeypatch):
 setup_trial(client,account,monkeypatch);calls=[]
 async def fetch(*args,**kw):calls.append(1);raise ServiceError('HTTP 429 secret-url-must-not-leak')
 async def board(*args):return [posting()]
 monkeypatch.setattr(x,'fetch_json',fetch);monkeypatch.setattr(x,'board_jobs',board)
 result=run(search.discover(account['id'],SearchRequest(interests=['Data analysis','Marketing'],sources=['ashby','adzuna'])))
 assert len(calls)==1 and result['jobs']
 assert 'secret-url' not in json.dumps(result)
 assert any(s['source']=='adzuna' and s['status']=='error' for s in result['sources'])

def test_trial_cache_and_duplicate_task_submission(client,account,monkeypatch):
 setup_trial(client,account,monkeypatch);calls=[]
 async def fetch(*a,**kw):calls.append(1);return {'results':[]}
 monkeypatch.setattr(x,'fetch_json',fetch)
 body={'interests':['Data analysis'],'sources':['adzuna'],'request_token':'one-click','refresh':True}
 async def scenario():
  from app.main import search as endpoint,workers
  req=SearchRequest(**body);first=await endpoint(req,account)
  second=await endpoint(req,account);assert first['task_id']==second['task_id']
  await workers[first['task_id']]
  cached=await endpoint(SearchRequest(**{**body,'request_token':'other-click','refresh':False}),account)
  assert cached['cached'] and cached['result']['data']['adzuna_trial']['attempted_requests']==0
  # Explicit refresh with the original token still returns the original task, never consumes quota twice.
  duplicate=await endpoint(SearchRequest(**{**body,'refresh':True}),account)
  assert duplicate['task_id']==first['task_id']
 run(scenario());assert len(calls)==1

def test_daily_never_calls_manual_trial_and_new_sources_baseline(client,account,monkeypatch):
 setup_trial(client,account,monkeypatch)
 job_alerts.save(account['id'],'job_search_preferences',{'query':SearchRequest(interests=['Data analysis'],sources=['adzuna','ashby']).model_dump()})
 job_alerts.save(account['id'],'job_alert',{'enabled':True,'timezone':'America/Phoenix','time':'08:00','browser':False,'email_enabled':False})
 async def forbidden(*a,**k):raise AssertionError('No trial or AI during daily checks')
 async def board(*args):return [posting()]
 monkeypatch.setattr(search,'adzuna',forbidden);monkeypatch.setattr(x,'board_jobs',board)
 # Connection changed from regular to manual trial after the scheduler's preflight.
 original=pc.public;checks=[]
 def changed_mode(user):
  value=original(user);checks.append(1)
  return {**value,'usage':'regular'} if len(checks)==1 else value
 monkeypatch.setattr(pc,'public',changed_mode)
 run(job_alerts.run_daily(account['id'],datetime(2026,10,25,17,tzinfo=timezone.utc),force=True))
 with db.connect() as c:
  assert not c.execute('SELECT 1 FROM cc_adzuna_attempts').fetchone()
  saved=json.loads(c.execute('SELECT result FROM cc_job_alert_runs').fetchone()[0]);assert not saved['new_jobs']

def test_public_cache_dedup_selection_ttl_and_failure(client,account,monkeypatch):
 calls=[]
 async def board(b,q):calls.append(feeds.board_key(b));return [posting(company=b['company'])]
 monkeypatch.setattr(x,'board_jobs',board)
 req=SearchRequest(interests=['Data analysis'],sources=['greenhouse','ashby','lever'])
 first=run(search.discover(account['id'],req));assert len(calls)==len(feeds.CATALOG['employers']) # Starter boards merged, not duplicated.
 run(search.discover(account['id'],req));assert len(calls)==len(feeds.CATALOG['employers'])
 req.employer_boards=['ashby:notion'];filtered=run(search.discover(account['id'],req));assert {r['data']['company'] for r in filtered['jobs']}=={'Notion'}
 with db.connect() as c:c.execute('UPDATE cc_public_job_snapshots SET success_at=?,attempted_at=?',(time.time()-49*3600,time.time()-100))
 async def fail(*a):raise ServiceError('Unavailable')
 monkeypatch.setattr(x,'board_jobs',fail)
 rows,meta=run(feeds.employer({'provider':'ashby','board':'notion','company':'Notion'}))
 assert rows and meta['stale'] and meta['error'] and rows[0]['snapshot_stale']
 assert not run(search.discover(account['id'],req,execution='scheduled'))['jobs']

def test_community_provenance_stale_filter_and_no_indeed(client,account,monkeypatch):
 async def fetch(url,**kw):
  if 'summary' in url:return {'generatedAt':(datetime.now(timezone.utc)-timedelta(hours=49)).isoformat()}
  return [{'company':'Example','platform':'ashby','jobId':'one','title':'Data Analyst','locations':['Richmond, VA'],'applyUrl':'https://employer.example/jobs/one','postedAt':db.now(),'scrapedAt':db.now()},{'company':'Bad','title':'Data Analyst','locations':['US'],'applyUrl':'https://indeed.com/1'}]
 monkeypatch.setattr(x,'fetch_json',fetch)
 req=SearchRequest(interests=['Data analysis'],sources=['github'])
 result=run(search.discover(account['id'],req));assert len(result['jobs'])==1
 d=result['jobs'][0]['data'];assert d['metadata_only'] and d['snapshot_stale'] and d['community_repository']==feeds.GITHUB_REPOSITORY
 assert not run(search.discover(account['id'],req,execution='scheduled'))['jobs']

def test_all_fetched_matches_and_senior_foreign_filter(client,account,monkeypatch):
 jobs=[posting(i,'Huge') for i in range(600)]+[posting(1,'Small')]
 result=feeds.balanced(jobs);assert len(result)==500 and result[1]['company']=='Small'
 for title in ('Supervisory IT Specialist','SUPV IT SPECIALIST','CHIEF DATA SCIENTIST','Engineering Manager','Manager, Software Engineering'):
  assert not search.title_match(title,['IT and systems','Data science','Software engineering'])
 for title in ('Staff Accountant','Staff Nurse','Account Manager'):
  assert search.title_match(title,title)
 assert search.review({**posting(),'country':'','location':'Tel Aviv, Israel'},SearchRequest()) is None
 async def board(b,q):return jobs
 monkeypatch.setattr(x,'board_jobs',board)
 result=run(search.discover(account['id'],SearchRequest(interests=['Data analysis'],sources=['ashby'],employer_boards=['ashby:notion'])))
 assert not result['truncated'] and result['total_matches']==601 and len(result['jobs'])==601 and result['page_size']==25

def test_posting_locations_keep_us_secondary_and_full_state_names(client,monkeypatch):
 assert x.in_us({'location':'Richmond, Virginia'})
 assert x.in_us({'location':'Athens, Georgia'})
 assert not x.in_us({'location':'Tbilisi, Georgia'})
 assert not x.in_us({'location':'Toronto, Ontario','description':'United States headquarters'})
 async def fetch(*a,**kw):return {'jobs':[{'id':'one','title':'Data Analyst','location':'Berlin, Germany','address':{'postalAddress':{'addressCountry':'DE'}},'secondaryLocations':[{'location':'Richmond, VA','address':{'postalAddress':{'addressCountry':'US','addressRegion':'VA'}}}],'jobUrl':'https://employer.example/jobs/one'}]}
 monkeypatch.setattr(x,'fetch_json',fetch)
 rows=run(x.board_jobs({'provider':'ashby','board':'example','company':'Example'},None))
 assert rows[0]['country']=='US' and search.review(rows[0],SearchRequest(location='East Coast'))

def test_manual_trial_cannot_run_as_background_even_when_requested(client,account,monkeypatch):
 setup_trial(client,account,monkeypatch)
 async def forbidden(*a,**k):raise AssertionError('Background Adzuna call')
 monkeypatch.setattr(search,'adzuna',forbidden)
 result=run(search.discover(account['id'],SearchRequest(sources=['adzuna']),execution='scheduled'))
 assert not result['jobs'] and result['adzuna_trial']['attempted_requests']==0
 assert result['sources'][0]['status']=='disabled'
