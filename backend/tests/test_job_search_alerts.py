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
    from app import provider_connections as pc
    pc.store(account['id'],pc.Adzuna(app_id='private-id',app_key='private-key',usage='regular'))
    a=run(search.adzuna(account['id'],'analyst','United States'))[0];u=run(search.usajobs('IT specialist','United States'))[0]
    assert a['source_added_at'] and not a['published_at'] and a['description_incomplete']
    assert a['url']=='https://www.adzuna.com/land/ad/1?tracking=retain-this-token'
    assert u['published_at'] and u['source_identity']=='usajobs:f1'
    assert calls[-1][2]['Authorization-Key']=='federal-key'
    assert not any(secret in json.dumps([a,u]) for secret in ('private-key','federal-key','api-owner@example.com'))












def test_snippet_blocks_comparison_but_can_be_tracked(client,account,monkeypatch):
    row=db.save(account['id'],'job',job(description_incomplete=True))
    monkeypatch.setattr(config,'OPENAI_KEY','fictional-test-key')
    result=client.post('/api/analyses',json={'job_id':row['id']})
    assert result.status_code==400 and 'snippet' in result.text
    assert applications.start(account['id'],row['id'])['data']['status']=='preparing'










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






def test_salary_summaries_and_missing_metadata_are_visible():
    value=search.review(job(salary={'scrapeableCompensationSalarySummary':'$60K – $75K'}),SearchRequest())
    assert value['salary']=='$60K – $75K'
    unknown=search.review(job(),SearchRequest())
    assert unknown['salary']=='Not stated'
    assert 'Salary not stated' in unknown['review_reasons'] and 'Work arrangement not stated' in unknown['review_reasons']


def test_role_preferences_remember_custom_choices_and_guard_account_changes(client,account):
    assert alerts.Preferences(query={'interests':['Nursing']}).query.title=='Nursing'
    body={'account_id':account['id'],'query':{**SearchRequest().model_dump(),'title':'Museum education','interests':['Museum education']},'recent_interests':['Museum education',' museum   EDUCATION ','Nursing']}
    assert client.put('/api/job-search/preferences',json=body).status_code==200
    row=client.get('/api/job-search/preferences').json()['preferences']['data']
    assert row['recent_interests']==['Museum education','Nursing'] and 'account_id' not in row
    assert client.put('/api/job-search/preferences',json={**body,'account_id':'someone-else'}).status_code==409
    # Clearing all selected roles remains saved; remembered custom choices are retained.
    assert client.put('/api/job-search/preferences',json={'query':{**body['query'],'title':'','interests':[]}}).status_code==200
    assert client.get('/api/job-search/preferences').json()['preferences']['data']['recent_interests']==row['recent_interests']
    backup=client.get('/api/account/export').json()
    other=client.post('/api/auth/register',json={'username':'pickerother','password':'fictional-other-password'}).json();onboard_test_account(other);client.headers['X-CSRF-Token']=other['csrf']
    assert not client.get('/api/job-search/preferences').json()['preferences']['data'].get('recent_interests')
    assert client.put('/api/job-search/preferences',json=body).status_code==409
    assert client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup))}).status_code==200
    assert client.get('/api/job-search/preferences').json()['preferences']['data']['recent_interests']==row['recent_interests']


def test_cities_states_regions_and_unknown_locations():
    from app import job_locations as loc
    assert loc.matches({'location':'Richmond, VA'},'Virginia') is True
    assert loc.matches({'location':'Richmond, Virginia'},'Richmond, VA') is True
    assert loc.matches({'location':'Charleston, West Virginia'},'Virginia') is False
    assert loc.matches({'location':'Washington, DC'},'West Coast') is False
    assert loc.matches({'location':'Washington, District of Columbia'},'East Coast') is True
    assert loc.matches({'location':'California, MD'},'California') is False
    assert loc.matches({'location':'Tucson, AZ','description':'Our offices include Boston.'},'East Coast') is False
    assert loc.matches({'location':'Boston, MA'},'East Coast') is True
    assert loc.matches({'location':'Remote, United States'},'East Coast') is None
    assert loc.matches({'location':'Virginia'},'Richmond, VA') is None
    request=SearchRequest(location='East Coast')
    assert search.review({**job(),'location':'Phoenix, AZ'},request) is None
    assert 'Requested location needs review' in search.review({**job(),'location':'Remote, US'},request)['review_reasons']
    assert 'Virginia' in loc.provider_location('East Coast').split(';')
    assert loc.provider_location('Richmond, VA')=='Richmond, Virginia'


def test_region_is_expanded_for_usajobs_without_extra_calls(client,account,monkeypatch):
    calls=[]
    async def fetch(url,params=None,headers=None):calls.append(params);return {'SearchResult':{'SearchResultItems':[]}}
    monkeypatch.setattr(x,'fetch_json',fetch);monkeypatch.setattr(config,'USAJOBS_KEY','fictional');monkeypatch.setattr(config,'USAJOBS_EMAIL','api@example.com')
    assert run(search.usajobs('analyst','East Coast'))==[]
    assert len(calls)==1 and 'Virginia' in calls[0]['LocationName'].split(';') and 'California' not in calls[0]['LocationName']


def test_location_history_account_scope_merge_and_restore(client,account):
    body={'query':SearchRequest(interests=['Nursing'],sources=['ashby'],location='East Coast').model_dump()}
    assert client.put('/api/job-search/preferences',json=body).status_code==200
    db.save(account['id'],'search',{'query':{'location':'Richmond, VA'},'jobs':[]})
    history=client.get('/api/job-search/preferences').json()['preferences']['data']['location_history']
    assert history==['East Coast','Richmond, VA']
    r=client.post('/api/job-search/locations',json={'value':'  Boston,   MA ','history':history});assert r.status_code==200
    assert r.json()['locations']==['Boston, MA','East Coast','Richmond, VA']
    # An older ordinary autosave must not remove committed history or alter the saved query.
    assert client.put('/api/job-search/preferences',json=body).status_code==200
    assert client.post('/api/job-search/locations',json={'value':'boston, ma','history':[]}).status_code==200
    p=client.get('/api/job-search/preferences').json()['preferences']['data']
    assert p['location_history']==['boston, ma','East Coast','Richmond, VA']
    assert p['query']['location']=='East Coast'
    assert client.post('/api/job-search/locations',json={'value':'Other City','account_id':'another-account'}).status_code==409
    assert client.post('/api/job-search/locations',json={'value':' '}).status_code==422
    assert client.post('/api/job-search/locations',json={'value':'x'*121}).status_code==422
    backup=client.get('/api/account/export').json()
    other=client.post('/api/auth/register',json={'username':'location_other','password':'fictional-location-password'}).json();onboard_test_account(other);client.headers['X-CSRF-Token']=other['csrf']
    assert client.get('/api/job-search/preferences').json()['preferences']['data']['location_history']==['United States']
    assert client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup))}).status_code==200
    assert client.get('/api/job-search/preferences').json()['preferences']['data']['location_history']==p['location_history']


def test_location_history_keeps_all_entries_and_empty_roles(client,account):
    values=['Fictional City '+str(i) for i in range(80)]
    assert client.post('/api/job-search/locations',json={'value':values[0],'history':values}).status_code==200
    body={'query':{'title':'','interests':[],'sources':['ashby']},'location_history':['Another City']}
    assert client.put('/api/job-search/preferences',json=body).status_code==200
    p=client.get('/api/job-search/preferences').json()['preferences']['data']
    assert len(p['location_history'])==82 # all 81 explicit entries plus current United States
    assert p['query']['title']=='' and p['query']['interests']==[]
    assert set(values)<=set(p['location_history'])
