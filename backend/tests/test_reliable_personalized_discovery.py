"""Exercise the real feed orchestration, not a mocked discover() boundary."""
import asyncio,copy,json
import pytest
from app import ai,config,db,integrations,job_search,personalized_jobs,provider_connections,public_job_feeds as feeds
from app.models import SearchRequest
from app.network import ServiceError

@pytest.mark.parametrize('broken_source',['employer','community'])
def test_one_malformed_source_keeps_healthy_postings_without_adzuna(client,account,monkeypatch,broken_source):
 boards=[{'provider':'greenhouse','board':'healthy','company':'Fictional Lab'},{'provider':'greenhouse','board':'broken','company':'Fictional Broken'}]
 monkeypatch.setattr(feeds,'catalog_boards',lambda u:boards)
 monkeypatch.setattr(provider_connections,'public',lambda u:{'configured':False})
 async def employer(board,**kw):
  if board['board']=='broken':raise AttributeError('private response must not be exposed')
  row=integrations.normalize_job('greenhouse','Data analyst','Fictional Lab','United States','Analyze data using SQL.','https://example.org/jobs/analyst',country='US',published_at=db.now(),publication_source='Employer')
  return [row],{'stale':False,'last_success':1,'revision':'fixture','cached':True,'error':''}
 async def community(**kw):
  if broken_source=='community':raise TypeError('untrusted malformed item')
  return [],{'stale':False,'last_success':1,'snapshot_at':db.now(),'error':''}
 monkeypatch.setattr(feeds,'employer',employer);monkeypatch.setattr(feeds,'community',community)
 request=SearchRequest(title='Data analyst',interests=['Data analyst'],location='United States',sources=['adzuna','greenhouse','github'])
 result=asyncio.run(job_search.discover(account['id'],request))
 assert len(result['jobs'])==1
 assert any(s['source']=='adzuna' and s['status']=='setup' for s in result['sources'])
 assert any(s['source']=='greenhouse:broken' and s['status']=='error' for s in result['sources'])
 assert 'private response' not in json.dumps(result)
 assert db.list_entities(account['id'],'job')[0]['id']==result['jobs'][0]['id']

def test_stage_failure_is_actionable_preserves_previous_run_and_never_retries(client,account,monkeypatch):
 old=db.save(account['id'],'personalized_search',{'matches':[],'checked_at':db.now(),'search_id':'old'})
 calls=[]
 async def model(schema,payload,*a,**kw):
  calls.append(payload);assert kw['retry_allowed'] is False
  return {'roles':['Data analyst'],'explanation':'Reviewed education direction.'},{}
 async def broken(*a,**kw):raise RuntimeError('SECRET integration response')
 monkeypatch.setattr(ai,'structured',model);monkeypatch.setattr(job_search,'discover',broken)
 with pytest.raises(ServiceError,match='searching selected public feeds') as exc:
  asyncio.run(personalized_jobs.execute(account['id'],personalized_jobs.Request(request_token='fictional-no-retry')))
 assert 'SECRET' not in str(exc.value) and 'no paid request was repeated' in str(exc.value)
 assert len(calls)==1 and db.get(account['id'],old['id'],'personalized_search')==old

def test_empty_search_is_saved_with_coverage_and_no_screening_calls(client,account,monkeypatch):
 calls=[]
 async def model(schema,payload,*a,**kw):
  calls.append(schema.__name__);return {'roles':['Data analyst'],'explanation':'Reviewed education direction.'},{}
 async def empty(*a,**kw):return {'jobs':[],'sources':[{'source':'adzuna','status':'setup','message':'Not configured; skipped.'}],'checked_at':db.now(),'query':{},'ai_calls':[]}
 monkeypatch.setattr(ai,'structured',model);monkeypatch.setattr(job_search,'discover',empty);monkeypatch.setattr(config,'ENABLE_WEB_SEARCH',False)
 result=asyncio.run(personalized_jobs.execute(account['id'],personalized_jobs.Request(request_token='fictional-empty-search')))
 assert calls==['Criteria'] and result['run']['data']['returned_count']==0
 assert result['run']['data']['source_statuses'][0]['status']=='setup'
 assert result['run']['data']['web_status']=='unavailable'
