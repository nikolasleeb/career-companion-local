import json,asyncio
import pytest
from app import db,public_job_feeds as feeds,employer_industries as industries
from app.models import SearchRequest

def test_catalog_adds_43_verified_nontech_employers_across_eight_fields():
 rows=feeds.CATALOG['employers'];assert len(rows)>=143 and len({feeds.board_key(b) for b in rows})==len(rows)
 additions=[b for b in rows if b.get('verified_at','').startswith('2026-10-28')];assert len(additions)>=40
 for b in additions:assert b.get('feed_url') and b.get('identity_url') and b.get('identity_label') and isinstance(b['verified_job_count'],int)
 for field in set(industries.INDUSTRIES)-{'technology'}:assert sum(field in b.get('industries',[]) for b in additions)>=3

def test_all_legacy_custom_and_overlapping_presets_resolve_dynamically(client,account):
 rows=feeds.catalog_boards(account['id']);one=feeds.board_key(rows[0])
 assert industries.resolve(rows,{})==rows
 assert industries.resolve(rows,{'employer_boards':[one]})==[rows[0]]
 assert industries.resolve(rows,{'employer_boards':[]})==[]
 query={'employer_selection_mode':'industries','employer_industries':['science','healthcare']}
 expected=[b for b in rows if {'science','healthcare'}&set(b.get('industries',[]))];assert industries.resolve(rows,query)==expected
 new={'provider':'lever','board':'fictional-added','company':'Fictional Science','industries':['science']};assert industries.resolve(rows+[new],query)[-1]==new
 assert len({feeds.board_key(b) for b in expected})==len(expected)
 assert industries.resolve(rows,{'employer_selection_mode':'all','employer_boards':[one]})==rows

def test_saved_choices_merge_preferences_and_account_additions_are_private(client,account):
 before=client.get('/api/job-search/preferences').json()['preferences']['data'];query={'employer_selection_mode':'industries','employer_industries':['science'],'employer_boards':None}
 r=client.put('/api/settings/employer-sources',json=query);assert r.status_code==200,r.text
 after=client.get('/api/job-search/preferences').json()['preferences']['data'];assert after['query']['title']==before['query']['title'];assert after['query']['employer_industries']==['science']
 added=client.post('/api/settings/employer-sources/boards',json={'company':'Fictional Employer','career_url':'https://jobs.lever.co/fictional'});assert added.status_code==200,added.text
 other=client.post('/api/auth/register',json={'username':'other-industry','password':'fictional-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
 public=client.get('/api/settings/employer-sources').json();assert public['selection']['employer_selection_mode']=='all' and not any(r['id']==added.json()['id'] for r in public['added_boards'])
 assert client.delete('/api/settings/employer-sources/boards/'+added.json()['id']).status_code==404

def test_industry_validation_and_empty_custom_selection(client,account):
 assert client.put('/api/settings/employer-sources',json={'employer_selection_mode':'industries','employer_industries':[]}).status_code==422
 assert client.put('/api/settings/employer-sources',json={'employer_selection_mode':'industries','employer_industries':['unknown']}).status_code==422
 with pytest.raises(ValueError):SearchRequest(employer_industries=['unknown'])
 assert client.put('/api/settings/employer-sources',json={'employer_selection_mode':'custom','employer_boards':[]}).status_code==200

def test_nontech_manual_and_scheduled_searches_use_same_presets(client,account,monkeypatch):
 from app import job_search,integrations
 calls=[]
 async def board(value,query):
  calls.append(feeds.board_key(value))
  return [integrations.normalize_job(value['provider'],'Research Assistant',value['company'],'United States','New graduate role. Full-time research assistant; no experience required.','https://employer.example/'+value['board'],country='US',employment_type='fulltime',published_at=db.now())]
 monkeypatch.setattr(integrations,'board_jobs',board)
 query=SearchRequest(title='research assistant',interests=['research assistant'],sources=['greenhouse','ashby','lever'],employer_selection_mode='industries',employer_industries=['science'])
 expected={feeds.board_key(b) for b in industries.resolve(feeds.catalog_boards(account['id']),query.model_dump())}
 manual=asyncio.run(job_search.discover(account['id'],query));assert manual['jobs'] and set(calls)==expected
 scheduled=asyncio.run(job_search.discover(account['id'],query,execution='scheduled'));assert scheduled['jobs'] and set(calls)==expected and len(calls)==len(expected)

def test_daily_and_for_you_inherit_source_choices(client,account,monkeypatch):
 from app import job_alerts,job_search,personalized_jobs,ai
 from app.network import ServiceError
 from datetime import datetime,timezone
 query=SearchRequest(title='research assistant',interests=['research assistant'],sources=['greenhouse','ashby'],employer_selection_mode='industries',employer_industries=['science','healthcare']).model_dump()
 job_alerts.put_preferences(job_alerts.Preferences(query=job_alerts.SavedSearch.model_validate(query)),account['id'])
 calls=[]
 async def discover(user,request,**kwargs):calls.append(request.model_dump());return {'jobs':[],'sources':[{'source':'greenhouse:fictional','status':'empty'}],'query':request.model_dump()}
 monkeypatch.setattr(job_search,'discover',discover)
 job_alerts.save(account['id'],'job_alert',job_alerts.Schedule(enabled=True,time='00:00',timezone='UTC').model_dump());asyncio.run(job_alerts.run_daily(account['id'],datetime.now(timezone.utc),force=True))
 async def text(*args,**kwargs):return {'roles':['research assistant'],'explanation':'Reviewed education.'},{'model':'fictional'}
 monkeypatch.setattr(ai,'structured',text)
 async def capture(user,request,**kwargs):calls.append(request.model_dump());raise ServiceError('Captured For You request')
 monkeypatch.setattr(job_search,'discover',capture)
 with pytest.raises(ServiceError,match='Captured'):asyncio.run(personalized_jobs.execute(account['id'],personalized_jobs.Request(request_token='fictional-for-you')))
 assert len(calls)==2
 for request in calls:assert request['employer_selection_mode']=='industries' and request['employer_industries']==['science','healthcare'] and request['employer_boards'] is None
