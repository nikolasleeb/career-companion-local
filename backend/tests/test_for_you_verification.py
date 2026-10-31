"""Availability, filter uncertainty and supported fit are separate decisions."""
import asyncio,copy,json,time
from datetime import datetime,timezone,timedelta
import pytest
from app import personalized_jobs as jobs,db,job_results
from app.models import SearchRequest
from app.network import ServiceError

REQUEST=SearchRequest(title='Data analyst',location='United States',job_types=['early_career'],days=30)
def row(**changes):
 d={'title':'Data Analyst','company':'Example Labs','description':'Analyze data and document findings with SQL. Collaborate with the research team. '*4,'url':'https://example.org/jobs/123','location':'Boston, MA, US','country':'US','workplace':'unknown','employment_type':'fulltime','published_at':db.now(),'_last_verified_epoch':time.time()}
 d.update(changes);return {'id':'fictional-job','data':d}
def fetch(monkeypatch,page=None,error=None):
 async def get(*a,**k):
  if error:raise error
  return page or {'status':403,'content_type':'text/html','content':b'Blocked'}
 monkeypatch.setattr(jobs,'public_fetch',get)
def check(r):
 outcomes=[];value=asyncio.run(jobs.verify(r,REQUEST,outcomes));return value,outcomes[0]

def test_unknown_level_is_reviewable_and_original_unchanged(monkeypatch):
 fetch(monkeypatch);r=row();before=copy.deepcopy(r);value,out=check(r)
 assert value['data']['recommendation_status']=='needs_review'
 assert 'Career level not stated' in value['data']['recommendation_caveats']
 assert value['data']['availability_basis']=='recent complete public feed'
 assert out['outcome']=='verified' and r==before

def test_unknown_date_remains_unknown(monkeypatch):
 fetch(monkeypatch);value,out=check(row(published_at=None))
 assert any('30-day filter could not be confirmed' in s for s in value['data']['recommendation_caveats'])
 assert value['data'].get('published_at') is None

@pytest.mark.parametrize('changes',[{'title':'Senior Data Analyst'},{'country':'CA','location':'Toronto, Canada'},{'published_at':(datetime.now(timezone.utc)-timedelta(days=60)).isoformat()},{'valid_through':(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()}])
def test_confirmed_conflicts_and_expiration_excluded(monkeypatch,changes):
 fetch(monkeypatch);value,out=check(row(**changes));assert value is None and out['outcome']=='rejected'

@pytest.mark.parametrize('changes',[{'_last_verified_epoch':time.time()-7*3600},{'metadata_only':True},{'description_incomplete':True},{'snapshot_stale':True}])
def test_blocked_page_cannot_rescue_stale_or_incomplete_feed(monkeypatch,changes):
 fetch(monkeypatch,error=ServiceError('blocked'));value,out=check(row(**changes));assert value is None and 'No current complete feed' in out['reason']

@pytest.mark.parametrize('content',[b'<html><title>Careers at Example Labs</title><main>'+b'Open opportunities here. '*20+b'</main></html>',json.dumps({'@type':'JobPosting','title':'Accountant','hiringOrganization':{'name':'Other Company'},'description':'Different job. '*40}).encode()])
def test_generic_or_unrelated_page_is_not_availability_evidence(monkeypatch,content):
 fetch(monkeypatch,{'status':200,'content_type':'text/html','content':content});assert check(row(metadata_only=True))[0] is None

def test_structured_specific_page_enriches_missing_date_and_retains_feed_values(monkeypatch):
 structured={'@type':'JobPosting','title':'Data Analyst','hiringOrganization':{'name':'Example Labs'},'description':'No experience required. Analyze SQL data and document research findings. '*3,'datePosted':db.now()}
 fetch(monkeypatch,{'status':200,'content_type':'text/html','content':('<script type="application/ld+json">'+json.dumps(structured)+'</script>').encode()})
 value,out=check(row(published_at=None,description_incomplete=True));d=value['data']
 assert d['published_at']==structured['datePosted'] and d['country']=='US' and d['location']=='Boston, MA, US'
 assert d['recommendation_status']=='confirmed_filters' and out['page_check']=='specific posting confirmed'

@pytest.mark.parametrize('status',[404,410])
def test_explicit_closed_response_overrides_fresh_feed(monkeypatch,status):
 fetch(monkeypatch,{'status':status});assert check(row())[0] is None

def test_confirmed_filters_prioritized_with_employer_diversity():
 rows=[{**row(),'id':str(i),'data':{**row()['data'],'company':company,'hard_filter_status':status}} for i,(company,status) in enumerate([('A','uncertain'),('A','matches'),('A','matches'),('B','matches'),('B','uncertain')])]
 pool=jobs.screening_pool(rows);assert [r['id'] for r in pool]==['1','3','2','0','4']

def test_saved_review_status_and_diagnostics_are_account_owned(client,account,monkeypatch):
 key=account['id'];fetch(monkeypatch);value,out=check(row());record=db.save(key,'job',value['data']);value['id']=record['id']
 saved=job_results.save_search(key,{'jobs':[value],'sources':[],'personalized_diagnostics':{'version':1,'verification_outcomes':[out]}})
 page=client.get('/api/job-search/searches/'+saved['id']+'/results?view=all').json()
 assert page['counts']['review']==1 and page['counts']['matches']==0
 assert page['jobs'][0]['data']['recommendation_status']=='needs_review'
 assert db.get(key,saved['id'],'search')['data']['personalized_diagnostics']['version']==1
 assert db.get('another-account',saved['id'],'search') is None

@pytest.mark.parametrize('available',[True,False])
def test_real_pipeline_diagnostics_privacy_and_no_retries(client,account,monkeypatch,available):
 from app import ai,career_coach,config,job_search,job_alerts
 uid=account['id'];other_user=client.post('/api/auth/register',json={'username':'anotherstudent','password':'fictional-test-password'}).json();other=db.save(other_user['id'],'experience',{'title':'Other account secret','confirmed':True})
 profile=career_coach.profile(uid)['sources'][0];r=db.save(uid,'job',row()['data']);calls=[]
 before=copy.deepcopy(job_alerts.preferences(uid))
 async def discover(user,request):
  assert user==uid
  return {'jobs':[r],'sources':[{'source':'adzuna','status':'setup','message':'Unconfigured; skipped'}],'query':request.model_dump()}
 async def model(schema,payload,*a,**kw):
  calls.append((schema.__name__,payload));assert kw['retry_allowed'] is False
  if schema==jobs.Criteria:return {'roles':['Data analyst'],'explanation':'Raw '+profile['id']},{}
  if schema==jobs.Screen:return {'job_ids':[r['id']]},{}
  return {'jobs':[{'job_id':r['id'],'summary':'An opportunity to use reviewed education.','evidence':[{'profile_source_id':profile['id'],'profile_quote':profile['text'],'posting_quote':'Analyze data'}],'suitable':True,'goal_alignment':'','preference_alignment':'','requirements_to_check':['Confirm career level']}]},{}
 monkeypatch.setattr(job_search,'discover',discover);monkeypatch.setattr(ai,'structured',model);monkeypatch.setattr(config,'ENABLE_WEB_SEARCH',False)
 fetch(monkeypatch,{'status':403,'content_type':'text/html','content':b'blocked'})
 if not available:db.save(uid,'job',{**r['data'],'_last_verified_epoch':time.time()-8*3600},r['id']);r['data']['_last_verified_epoch']=time.time()-8*3600
 result=asyncio.run(jobs.execute(uid,jobs.Request(request_token='fictional-pipeline-unique')));run=result['run']['data'];d=run['diagnostics']
 assert d['shortlisted_ids']==[r['id']] and d['stage_counts']['verification_attempts']==1
 assert run['returned_count']==int(available) and d['stage_counts']['needs_review']==int(available)
 assert len(calls)==(3 if available else 2) and 'Raw' not in run['explanation']
 assert other['id'] not in json.dumps(calls) and 'Other account secret' not in json.dumps(calls)
 assert job_alerts.preferences(uid)==before
 assert run['evidence_sources'][profile['id']]=='Test setup education'

@pytest.mark.parametrize('country',['Canada',''])
def test_employer_location_overrides_conflicting_us_feed(monkeypatch,country):
 structured={'@type':'JobPosting','title':'Data Analyst','hiringOrganization':{'name':'Example Labs'},'description':'Analyze data with SQL. '*20,'jobLocation':{'address':{'addressLocality':'Toronto, Canada','addressCountry':country}}}
 fetch(monkeypatch,{'status':200,'content_type':'text/html','content':('<script type="application/ld+json">'+json.dumps(structured)+'</script>').encode()})
 assert check(row())[0] is None

def test_provider_added_date_is_not_assumed_employer_publication_date(monkeypatch):
 fetch(monkeypatch);value,out=check(row(title='Junior Data Analyst',published_at=None,source_added_at=db.now()))
 assert value['data']['hard_filter_status']=='uncertain'
 assert any('30-day filter' in s for s in value['data']['recommendation_caveats'])
