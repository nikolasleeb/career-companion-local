import asyncio,copy
from datetime import datetime,timedelta,timezone
import pytest
from pydantic import ValidationError
from app import ai,db,job_ai,job_alerts,job_search,job_cache,personalized_jobs,assistant_context
from app.models import SearchRequest,ApplicationInput
from app.network import ServiceError

@pytest.mark.parametrize('days',[30,60,90])
def test_posting_age_boundaries_keep_expiry_and_unknown_date_rules(client,monkeypatch,days):
 anchor=datetime(2026,10,27,16,tzinfo=timezone.utc)
 class Fixed(datetime):
  @classmethod
  def now(cls,tz=None):return anchor
 monkeypatch.setattr(job_search,'datetime',Fixed)
 req=SearchRequest(title='data analyst',days=days)
 base={'title':'Data Analyst','company':'Example','country':'US','location':'Boston, MA','description':'New graduate role. SQL and research methods.','employment_type':'fulltime','workplace':'hybrid'}
 for age,expected in [(days-1,True),(days,True),(days+1,False)]:
  assert bool(job_search.review({**base,'published_at':(anchor-timedelta(days=age)).isoformat()},req)) is expected
 undated=job_search.review(base.copy(),req)
 assert undated['hard_filter_status']=='uncertain' and 'Posting date not confirmed' in undated['filter_reasons']
 assert job_search.review({**base,'deadline':'2000-01-01'},req) is None
 assert job_cache.days()==30

def test_ninety_day_preferences_roundtrip_and_daily_inheritance(client,account,monkeypatch):
 assert SearchRequest().days==30
 with pytest.raises(ValidationError):SearchRequest(days=91)
 query=SearchRequest(title='research assistant',days=90,sources=['ashby']).model_dump()
 assert client.put('/api/job-search/preferences',json={'query':query}).status_code==200
 seen=[]
 async def discover(user,request,**kw):
  seen.append(request.days);return {'jobs':[],'sources':[{'source':'ashby:example','status':'empty'}],'query':request.model_dump()}
 monkeypatch.setattr(job_search,'discover',discover)
 job_alerts.save(account['id'],'job_alert',job_alerts.Schedule(enabled=True,time='00:00',timezone='UTC').model_dump())
 asyncio.run(job_alerts.run_daily(account['id'],datetime.now(timezone.utc),force=True));assert seen==[90]
 backup=client.get('/api/account/export').json()
 assert client.post('/api/account/import',files={'file':('backup.json',__import__('json').dumps(backup))}).status_code==200
 assert client.get('/api/job-search/preferences').json()['preferences']['data']['query']['days']==90

def test_ai_briefs_and_for_you_inherit_extended_window(client,account,monkeypatch):
 job_alerts.put_preferences(job_alerts.Preferences(query=job_alerts.SavedSearch(title='research assistant',days=90,sources=['ashby'])),account['id'])
 calls=[]
 async def model(schema,payload,*args,**kw):
  if schema==job_ai.Brief:
   value={'roles':['research assistant'],'locations':['United States'],'workplace':'any','career_levels':['early_career'],'days':90,'minimum_salary':None,'pay_period':'year','summary':'Fictional search','clarification':''}
   assert job_ai.Brief.model_validate({**value,'days':60}).days==60
   return job_ai.Brief.model_validate(value).model_dump(),{'model':'mock'}
  return {'roles':['research assistant'],'explanation':'Reviewed education.'},{'model':'mock'}
 async def discover(user,request,**kw):calls.append(request.days);raise ServiceError('captured search request')
 monkeypatch.setattr(ai,'structured',model);monkeypatch.setattr(job_search,'discover',discover)
 with pytest.raises(ServiceError,match='captured search request'):asyncio.run(job_ai.find(account['id'],job_ai.Discover(prompt='Past 90 days',request_token='mock-90-days')))
 with pytest.raises(ServiceError,match='captured search request'):asyncio.run(personalized_jobs.execute(account['id'],personalized_jobs.Request(request_token='mock-for-you')))
 assert calls==[90,90]

def test_archive_removes_chart_cohort_but_keeps_historical_coach_context(client,account):
 r=client.post('/api/applications',json=ApplicationInput(title='Research assistant',company='Example Lab',status='applied',applied_date='2026-10-20').model_dump());assert r.status_code==200,r.text
 app=r.json();before=copy.deepcopy(app['data'])
 archived=client.put('/api/applications/'+app['id'],json={**before,'archived':True});assert archived.status_code==200,archived.text
 for flag in ('true','false'):
  result=client.get('/api/applications/dashboard?start=2026-01-01&end=2026-12-31&include_archived='+flag).json()
  assert result['cohort_count']==0 and not result['paths'] and not result['chart_dates'] and not result['nodes'] and not result['links']
  assert not any(result['counts'].values()) and not result['missing_date_ids']
 sources=assistant_context.retrieve(account['id'],'Example Lab research',pinned=[app['id']]);item=next(s for s in sources if s['record_id']==app['id'])
 assert item['label'].startswith('Archived application · historical record') and 'Not a current application' in item['text']
 assert 'applied' in item['text']
 restored=client.put('/api/applications/'+app['id'],json={**archived.json()['data'],'archived':False});assert restored.status_code==200
 assert client.get('/api/applications/dashboard?start=2026-01-01&end=2026-12-31').json()['cohort_count']==1
 item=next(s for s in assistant_context.sources(account['id']) if s['record_id']==app['id']);assert item['label'].startswith('Application · ') and 'historical record' not in item['text']
 assert db.get(account['id'],app['id'],'application')['data']['applied_date']==before['applied_date']
