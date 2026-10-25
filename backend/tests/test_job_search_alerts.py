import asyncio,base64,copy,json,re
from datetime import datetime,timedelta,timezone
import pytest
from app import db,config,ai,integrations as x,job_search as search,job_alerts as alerts,applications
from app.models import SearchRequest,Board
from conftest import onboard_test_account

def run(coro):return asyncio.run(coro)
def job(title='Data Analytics Intern',identity='j1',**kwargs):
    return x.normalize_job('ashby',title,'Fictional Employer','Phoenix, AZ','Enrolled students use SQL and Python. No prior experience required.','https://example.com/jobs/'+identity,country='US',source_identity='ashby:example:'+identity,origin_key='ashby:example',published_at=db.now(),publication_source='Ashby last publishedAt',**kwargs)

def test_role_aliases_boundaries_nontech_and_location():
    assert search.title_match('Data Analytics Intern','data analyst')
    assert search.title_match('IT Support Specialist','IT and systems')
    assert not search.title_match('Auditor','IT and systems')
    assert search.title_match('Registered Nurse - New Graduate','registered nurse')
    assert search.title_match('Staff Nurse','nurse')
    assert search.title_match('Staff Accountant','accountant')
    assert search.title_match('Lead Generation Specialist','lead generation')
    assert not search.title_match('Staff Software Engineer','software engineering')
    assert not x.in_us({'location':'London, United Kingdom','description':'Our offices include the United States.'})
    req=SearchRequest(interests=['registered nurse'])
    assert search.review(job(title='Registered Nurse',identity='nurse'),req)
    assert search.review({**job(),'country':'GB','location':'London, United Kingdom'},req) is None
    unknown=search.review({**job(),'country':'','location':''},req)
    assert 'US work location not established' in unknown['review_reasons']
    assert search.review({**job(),'description':'Minimum 5 years of experience required.'},req) is None
    assert search.review({**job(),'description':'5 years of experience preferred.'},req)

@pytest.mark.parametrize('url,provider,board',[('https://jobs.lever.co/example/123','lever','example'),('https://jobs.ashbyhq.com/example','ashby','example'),('https://job-boards.greenhouse.io/example','greenhouse','example')])
def test_board_urls(url,provider,board):
    value=Board(career_url=url,company='Example')
    assert value.provider==provider and value.board==board
    for bad in ('http://127.0.0.1','https://jobs.lever.co.evil.invalid/example','https://user:pass@jobs.lever.co/example'):
        with pytest.raises(ValueError):Board(career_url=bad,company='Example')


def test_search_partial_failure_keeps_decisions_and_distinct_requisitions(client,account,monkeypatch):
    async def board(b,q):return [job(identity='one'),job(identity='two'),{**job(identity='blocked'),'url':'https://www.indeed.com/viewjob?jk=1'}]
    monkeypatch.setattr(x,'board_jobs',board)
    req=SearchRequest(interests=['Data analysis'],sources=['ashby','adzuna','jobspy'])
    result=run(search.discover(account['id'],req));assert len(result['jobs'])==2
    assert any(v['status']=='setup' for v in result['sources'])
    assert any(v['source']=='jobspy' and v['status']=='disabled' for v in result['sources'])
    id=result['jobs'][0]['id'];assert client.put('/api/job-search/jobs/'+id+'/interest',json={'state':'saved'}).status_code==200
    assert run(search.discover(account['id'],req))['jobs'][0]['data']['interest_state']=='saved'
    assert not search.blocked_url('https://example.com/indeed-help')
    assert search.blocked_url('https://www.indeed.co.uk/viewjob')
    assert search.blocked_url('https://indeedjobs.com/viewjob')


def test_providers_map_dates_ids_and_never_expose_keys(client,account,monkeypatch):
    calls=[]
    async def fetch(url,params=None,headers=None):
        calls.append((url,params,headers))
        if 'adzuna' in url:return {'results':[{'id':'1','title':'Data Analyst','company':{'display_name':'Example'},'location':{'display_name':'Phoenix, AZ'},'description':'A description snippet','redirect_url':'https://www.adzuna.com/land/ad/1?tracking=retain-this-token','created':db.now(),'salary_min':50000,'salary_max':60000}]}
        return {'SearchResult':{'SearchResultItems':[{'MatchedObjectId':'f1','MatchedObjectDescriptor':{'PositionTitle':'IT Specialist','OrganizationName':'Example agency','PositionLocation':[{'CountryCode':'United States'}],'PositionLocationDisplay':'Phoenix, AZ','PositionURI':'https://www.usajobs.gov/job/f1','PublicationStartDate':db.now(),'QualificationSummary':'One year specialized experience.','UserArea':{'Details':{'Education':'Current students may apply.','HiringPath':['student']}}}}]}}
    monkeypatch.setattr(x,'fetch_json',fetch);monkeypatch.setattr(config,'ADZUNA_ID','private-id');monkeypatch.setattr(config,'ADZUNA_KEY','private-key');monkeypatch.setattr(config,'USAJOBS_KEY','federal-key');monkeypatch.setattr(config,'USAJOBS_EMAIL','api-owner@example.com')
    a=run(search.adzuna('analyst','United States'))[0];u=run(search.usajobs('IT specialist','United States'))[0]
    assert a['source_added_at'] and not a['published_at'] and a['description_incomplete']
    assert a['url']=='https://www.adzuna.com/land/ad/1?tracking=retain-this-token'
    assert u['published_at'] and u['source_identity']=='usajobs:f1'
    assert calls[-1][2]['Authorization-Key']=='federal-key'
    assert not any(secret in json.dumps([a,u]) for secret in ('private-key','federal-key','api-owner@example.com'))


def test_preferences_schedule_validation_ownership_and_backup(client,account):
    prefs={'query':SearchRequest(interests=['Nursing','Marketing'],sources=['ashby']).model_dump()}
    assert client.put('/api/job-search/preferences',json=prefs).status_code==200
    assert client.put('/api/job-search/schedule',json={'enabled':True,'timezone':'Not/AZone'}).status_code==422
    assert client.put('/api/job-search/schedule',json={'enabled':True,'timezone':'America/Phoenix'}).status_code==200
    backup=client.get('/api/account/export').json()
    assert any(r['kind']=='job_alert' for r in backup['records'])
    other=client.post('/api/auth/register',json={'username':'another','password':'fictional-other-password'}).json();onboard_test_account(other);client.headers['X-CSRF-Token']=other['csrf']
    assert client.get('/api/job-search/preferences').json()['schedule']['data']['enabled'] is False
    assert client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup))}).status_code==200
    restored=client.get('/api/job-search/preferences').json()
    assert restored['schedule']['data']['enabled'] is False
    assert restored['preferences']['data']['query']['interests']==['Nursing','Marketing']
    owned=db.save(account['id'],'job',job())
    assert client.put('/api/job-search/jobs/'+owned['id']+'/interest',json={'state':'saved'}).status_code==404


def test_daily_baseline_dedup_restart_and_no_ai(client,account,monkeypatch):
    user=account['id'];alerts.save(user,'job_alert',alerts.Schedule(enabled=True,browser=True).model_dump())
    rows=[job()];count=[]
    async def discover(uid,request):
        assert 'web' not in request.sources and 'jobspy' not in request.sources
        count.append(1);return {'jobs':[db.save(uid,'job',v,v['source_identity']) for v in rows],'sources':[{'source':'ashby:example','status':'ok','message':'Fixture'}]}
    async def deliver(uid,day,batch):count.append(list(batch['new_jobs']))
    async def forbidden(*a,**kw):raise AssertionError('Scheduled scans must not use AI')
    monkeypatch.setattr(search,'discover',discover);monkeypatch.setattr(alerts,'deliver',deliver);monkeypatch.setattr(ai,'web_jobs',forbidden)
    now=datetime(2026,10,25,16,tzinfo=timezone.utc)
    run(alerts.run_daily(user,now));assert count[-1]==[]
    rows.append(job(identity='new'));run(alerts.run_daily(user,now));assert len(count)==2
    run(alerts.run_daily(user,now+timedelta(days=1)));assert count[-1]==['ashby:example:new']
    run(alerts.run_daily(user,now+timedelta(days=4)));assert count[-1]==[]
    # Claimed runs are not duplicated; expired leases recover persisted results.
    assert alerts.claim(user,'2099-01-01',100)=={}
    assert alerts.claim(user,'2099-01-01',101) is None
    assert alerts.claim(user,'2099-01-01',1100)=={}


def test_dst_schedule_runs_once_per_local_date(client,account,monkeypatch):
    user=account['id'];alerts.save(user,'job_alert',alerts.Schedule(enabled=True,time='01:30',timezone='America/New_York').model_dump())
    calls=[]
    async def discover(*args):calls.append(1);return {'jobs':[],'sources':[]}
    monkeypatch.setattr(search,'discover',discover)
    for hour in (5,6,7):run(alerts.run_daily(user,datetime(2026,11,1,hour,45,tzinfo=timezone.utc)))
    assert len(calls)==1


def test_push_endpoints_and_account_binding(client,account):
    body={'endpoint':'https://fcm.googleapis.com/fcm/send/fictional','keys':{'p256dh':base64.urlsafe_b64encode(alerts.ec.generate_private_key(alerts.ec.SECP256R1()).public_key().public_bytes(alerts.serialization.Encoding.X962,alerts.serialization.PublicFormat.UncompressedPoint)).rstrip(b'=').decode(),'auth':base64.urlsafe_b64encode(b'a'*16).rstrip(b'=').decode()}}
    assert client.post('/api/job-search/push',json=body).status_code==200
    for endpoint in ['http://127.0.0.1','https://localhost/test','https://fcm.googleapis.com.evil.invalid/test']:
        assert client.post('/api/job-search/push',json={**body,'endpoint':endpoint}).status_code==422
    other=client.post('/api/auth/register',json={'username':'pushother','password':'fictional-other-password'}).json();onboard_test_account(other);client.headers['X-CSRF-Token']=other['csrf']
    assert client.post('/api/job-search/push',json=body).status_code==409
    assert client.request('DELETE','/api/job-search/push',json=body).status_code==200
    with db.connect() as c:assert c.execute('SELECT user_id FROM cc_job_push').fetchone()[0]==account['id']


def test_delivery_intent_prevents_duplicate_send(client,account,monkeypatch):
    user=account['id'];alerts.save(user,'job_alert',alerts.Schedule(enabled=True,email_enabled=True,email='recipient@example.com').model_dump())
    with db.connect() as c:c.execute('INSERT INTO cc_job_email_verifications VALUES(?,?,?,?,?,?)',(user,'recipient@example.com','irrelevant',0,0,1))
    calls=[]
    async def verified(*a):return True
    async def email(method,path,payload=None):calls.append(payload);return {'queued':['recipient@example.com']}
    monkeypatch.setattr(alerts,'verified_recipient',verified);monkeypatch.setattr(alerts,'email_api',email)
    row=db.save(user,'job',job());batch={'new_jobs':[row['id']]}
    run(alerts.deliver(user,'2026-10-25',batch));run(alerts.deliver(user,'2026-10-25',batch));assert len(calls)==1
    assert calls[0]['to']=='recipient@example.com' and 'text' in calls[0] and 'html' in calls[0]
    assert 'cc' not in calls[0] and 'bcc' not in calls[0]


def test_snippet_blocks_comparison_but_can_be_tracked(client,account,monkeypatch):
    row=db.save(account['id'],'job',job(description_incomplete=True))
    monkeypatch.setattr(config,'OPENAI_KEY','fictional-test-key')
    result=client.post('/api/analyses',json={'job_id':row['id']})
    assert result.status_code==400 and 'snippet' in result.text
    assert applications.start(account['id'],row['id'])['data']['status']=='preparing'


def test_email_code_belongs_to_recipient_and_account(client,account,monkeypatch):
    calls=[]
    async def verified(address):return True
    async def email(method,path,payload=None):calls.append(payload);return {'queued':[payload['to']]}
    monkeypatch.setattr(alerts,'verified_recipient',verified);monkeypatch.setattr(alerts,'email_api',email)
    response=client.post('/api/job-search/email/verify',json={'email':'recipient@example.com'})
    assert response.status_code==200
    code=re.search(r'code is (\d{6})',calls[0]['text'])[1]
    assert client.put('/api/job-search/schedule',json={'email_enabled':True,'email':'recipient@example.com'}).status_code==400
    assert client.post('/api/job-search/email/confirm',json={'email':'elsewhere@example.com','code':code}).status_code==400
    assert client.post('/api/job-search/email/confirm',json={'email':'recipient@example.com','code':code}).status_code==200
    assert client.put('/api/job-search/schedule',json={'email_enabled':True,'email':'recipient@example.com'}).status_code==200
    other=client.post('/api/auth/register',json={'username':'emailother','password':'fictional-other-password'}).json();onboard_test_account(other);client.headers['X-CSRF-Token']=other['csrf']
    assert client.put('/api/job-search/schedule',json={'email_enabled':True,'email':'recipient@example.com'}).status_code==400


def test_failed_source_establishes_baseline_only_after_recovery(client,account,monkeypatch):
    user=account['id'];alerts.save(user,'job_alert',alerts.Schedule(enabled=True).model_dump());day=datetime(2026,10,25,16,tzinfo=timezone.utc);failed=[True]
    async def discover(uid,request):return {'jobs':[] if failed[0] else [db.save(uid,'job',job(),'found')],'sources':[{'source':'ashby:example','status':'error' if failed[0] else 'ok','message':'Unavailable' if failed[0] else 'Recovered'}]}
    monkeypatch.setattr(search,'discover',discover)
    run(alerts.run_daily(user,day));failed[0]=False;run(alerts.run_daily(user,day+timedelta(days=1)))
    with db.connect() as c:result=json.loads(c.execute('SELECT result FROM cc_job_alert_runs WHERE user_id=? AND day=?',(user,'2026-10-26')).fetchone()[0])
    assert result['new_jobs']==[] and result['baseline_established']


def test_expired_delivery_intent_is_not_blindly_replayed(client,account):
    user=account['id'];alerts.claim(user,'2099-01-01',100)
    with db.connect() as c:c.execute('INSERT INTO cc_job_deliveries VALUES(?,?,?,?,?)',(user,'2099-01-01','email','sending','Pending'))
    alerts.claim(user,'2099-01-01',1100)
    with db.connect() as c:assert c.execute('SELECT state FROM cc_job_deliveries WHERE user_id=?',(user,)).fetchone()[0]=='unconfirmed'


def test_duplicate_schedule_claims_are_atomic(client,account):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(4) as pool:claims=list(pool.map(lambda _:alerts.claim(account['id'],'2099-01-01',100),range(4)))
    assert sum(r is not None for r in claims)==1


def test_dates_distinguish_provider_listing_from_employer_publication():
    req=SearchRequest()
    v=job();v['published_at']=None;v['source_added_at']=db.now()
    assert search.review(v,req)['date_kind']=='aggregator_added'
    assert search.review({**job(),'published_at':'2000-01-01T00:00:00Z'},req) is None
    v=job();v['published_at']=None
    assert search.review(v,req)['date_kind']=='unknown'
    assert 'Listing date not verified' in v['review_reasons']


def test_existing_application_url_is_reused_and_status_not_changed(client,account):
    one=db.save(account['id'],'job',job());application=applications.start(account['id'],one['id'])
    data={**application['data'],'status':'applied','submitted_resume_id':'','notes':'Preserve this account note'}
    db.save(account['id'],'application',data,application['id'])
    duplicate=db.save(account['id'],'job',{**job(),'url':one['data']['url']+'?utm_source=other'})
    reused=applications.start(account['id'],duplicate['id'])
    assert reused['id']==application['id'] and reused['data']['status']=='applied' and reused['data']['notes']=='Preserve this account note'


def test_lever_partial_data_and_timeouts(client,account,monkeypatch):
    async def fetch(url,params=None,headers=None):return [{'id':'1','text':'Marketing Intern','categories':{'location':'Phoenix, AZ','commitment':'Intern'},'hostedUrl':'https://jobs.lever.co/example/1','descriptionPlain':'Enrollment required.','lists':[]}]
    monkeypatch.setattr(x,'fetch_json',fetch)
    rows=run(x.board_jobs({'provider':'lever','board':'example','company':'Example'},['marketing']))
    assert rows[0]['source_identity']=='lever:example:1' and rows[0]['published_at'] is None
    async def fail(*a):raise search.ServiceError('Source timeout; retry later.')
    monkeypatch.setattr(x,'board_jobs',fail)
    result=run(search.discover(account['id'],SearchRequest(sources=['ashby'])))
    assert result['jobs']==[] and result['sources'][0]['status']=='error'


def test_check_now_uses_existing_task_api_without_orphaning_a_run(client,account,monkeypatch):
    from test_app import wait
    async def discover(*args):return {'jobs':[],'sources':[],'query':{},'checked_at':db.now(),'ai_calls':[]}
    monkeypatch.setattr(search,'discover',discover)
    assert client.post('/api/job-search/check-now',json={}).status_code==400
    alerts.save(account['id'],'job_alert',alerts.Schedule(enabled=True).model_dump())
    start=client.post('/api/job-search/check-now',json={})
    assert start.status_code==200,start.text
    finished=wait(client,start.json()['task_id'])
    assert finished['status']=='completed',finished
    assert client.get('/api/job-search/notifications').json()['runs'][0]['result']['baseline_pending']


def test_daily_cross_source_url_dedup(client,account,monkeypatch):
    user=account['id'];alerts.save(user,'job_alert',alerts.Schedule(enabled=True).model_dump())
    rows=[job()];sources=[{'source':'ashby:example','status':'ok'},{'source':'adzuna','status':'ok'}]
    async def discover(uid,request):return {'jobs':[db.save(uid,'job',v,v['source_identity']) for v in rows],'sources':sources}
    monkeypatch.setattr(search,'discover',discover)
    now=datetime(2026,10,25,16,tzinfo=timezone.utc);run(alerts.run_daily(user,now))
    rows[0]={**rows[0],'source_identity':'adzuna:new-id','origin_key':'adzuna'}
    run(alerts.run_daily(user,now+timedelta(days=1)))
    with db.connect() as c:result=json.loads(c.execute('SELECT result FROM cc_job_alert_runs WHERE day=?',('2026-10-26',)).fetchone()[0])
    assert result['new_jobs']==[]


def test_salary_summaries_and_missing_metadata_are_visible():
    value=search.review(job(salary={'scrapeableCompensationSalarySummary':'$60K – $75K'}),SearchRequest())
    assert value['salary']=='$60K – $75K'
    unknown=search.review(job(),SearchRequest())
    assert unknown['salary']=='Not stated'
    assert 'Salary not stated' in unknown['review_reasons'] and 'Work arrangement not stated' in unknown['review_reasons']
