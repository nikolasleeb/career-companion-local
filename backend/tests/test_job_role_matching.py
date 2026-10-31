"""Role relevance for new searches and retained history; no live providers."""
import asyncio
import copy
import json
import pytest
from app import ai,db,integrations,job_ai,job_results,job_search,job_role_matching,network,public_job_feeds
from app.models import SearchRequest
from conftest import onboard_test_account

THERMAL='Thermal & Mechanical Engineer, Annapurna Labs - AI Silicon Packaging'
ROLES=['Cloud infrastructure','Data science','Data engineering','Data analysis']

@pytest.mark.parametrize('title',[
 THERMAL,'Mechanical Engineer - AI','AI Silicon Packaging Mechanical Engineer',
 'Sensing HW & Data Collection Systems - Mechanical Engineer',
 'Mechanical Engineer, Data Center Cooling','Sales Analyst, Product Marketing',
 'Software Licensing Sales Engineer',
])
def test_unrelated_words_do_not_create_a_role(title):
 roles=['Software engineering',*ROLES] if 'Software' in title else ROLES
 assert not job_search.title_match(title,roles,['early_career'])

@pytest.mark.parametrize('title,role',[
 ('AI Engineer','Data science'),('AI/ML Engineer','Data science'),
 ('AI Solutions Engineer with Security Clearance','Data science'),
 ('AI Research Engineer','Data science'),('Artificial Intelligence Engineer','Data science'),
 ('Software Engineer, Applied AI Solutions','Data science'),
 ('Software Engineer - AI','Data science'),('Machine-Learning Engineer','Data science'),
 ('Engineer, Machine Learning','Data science'),('Data Scientist I','Data science'),
 ('Data-Engineer','Data engineering'),('Data Platform Engineer','Data engineering'),
 ('Analytics Engineer','Data engineering'),('ETL Developer','Data engineering'),
 ('GIS - Data Analyst / Tooling Specialist','Data analysis'),
 ('Business Intelligence Engineer II','Data analysis'),('Data Analytics Intern','data analyst'),
 ('Cloud Engineer','Cloud infrastructure'),('Infrastructure Security Engineer','Cloud infrastructure'),
 ('DevOps Engineer','Cloud infrastructure'),('Site Reliability Engineer','Cloud infrastructure'),
 ('Software Engineering Intern','Software engineering'),('IT Support Specialist','IT and systems'),
 ('Registered Nurse - New Graduate','Nursing'),('Thermal & Mechanical Engineer','Mechanical engineering'),
 ('Data Analyst Intern','Data Analyst Intern'),('DATA\u2011SCIENCE INTERN','Data science'),
])
def test_compound_roles_punctuation_and_custom_roles(title,role):
 assert job_search.title_match(title,role,['internship','early_career'])

def test_level_filters_and_empty_queries_stay_safe():
 assert not job_search.title_match('Senior AI Engineer','Data science',['early_career'])
 assert not job_search.title_match('Staff Software Engineer','Software engineering',['mid_career'])
 assert not job_search.title_match('Data Analyst Manager','Data analysis',['early_career'])
 assert job_search.title_match('Data Analyst Manager','Data analysis',['mid_career'])
 for query in ('','internship','entry level',[],['  ']):
  assert not job_search.title_match(THERMAL,query)
 assert job_search.title_match(THERMAL,'Mechanical engineering')

def posting(title,index=0,**extra):
 return {'title':title,'company':'Fictional Employer','country':'US','location':'Austin, TX',
 'url':'https://employer.example/jobs/'+str(index),'description':'Full-time role. No experience required. Bachelor degree required.',
 'published_at':db.now(),'employment_type':'fulltime','workplace':'onsite','hard_filter_status':'matches',**extra}

@pytest.mark.parametrize('ai_search',[False,True])
def test_existing_results_rechecked_before_paging_without_mutating_history(client,account,monkeypatch,ai_search):
 u=account['id']
 records=[db.save(u,'job',posting(title,i)) for i,title in enumerate([THERMAL,*['AI/ML Engineer '+str(i) for i in range(28)]])]
 request=SearchRequest(interests=ROLES,career_levels=['early_career'])
 search=job_results.save_search(u,{'jobs':records,'sources':[],'query':request.model_dump(),**({'discovery_kind':'ai','ai_brief':{'roles':ROLES}} if ai_search else {})})
 wrong=records[0];db.save(u,'job',{**wrong['data'],'interest_state':'saved'},wrong['id'])
 application=db.save(u,'application',{'job_id':wrong['id'],'status':'preparing','notes':'Preserve my choice'})
 review=db.save(u,'ai_job_match',{'search_id':search['id'],'state':'completed','assessments':{wrong['id']:{'fit':'stretch'}}})
 protected=[db.get(u,r['id'],r['kind']) for r in [search,wrong,application,review]]
 with db.connect() as c:
  before=[tuple(r) for r in c.execute('SELECT * FROM cc_search_rows WHERE search_id=?',(search['id'],))]
  snapshots=[tuple(r) for r in c.execute("SELECT * FROM entities WHERE user_id=? AND kind='job_snapshot' ORDER BY id",(u,))]
 async def forbidden(*a,**k):raise AssertionError('Saved-result reads cannot call providers or AI')
 for obj,name in [(ai,'structured'),(job_search,'discover'),(network,'public_fetch'),(integrations,'fetch_json')]:monkeypatch.setattr(obj,name,forbidden)
 # Today's form is independent of the original search scope.
 db.update_settings(u,{'job_search':{'query':{'interests':['Mechanical engineering']}}})
 for sort in ('balanced','recent','best'):
  result=client.get(f"/api/job-search/searches/{search['id']}/results?view=all&sort={sort}&page=2&page_size=25").json()
  assert result['total']==28 and len(result['jobs'])==3 and result['pages']==2
  assert result['counts']['matches']==28
  assert wrong['id'] not in [r['id'] for r in result['jobs']]
 assert client.get(f"/api/job-search/searches/{search['id']}/results?view=all&q=Thermal").json()['total']==0
 assert len(job_results.all_rows(u,search['id']))==28
 estimate=job_ai.estimate(u,job_ai.Match(search_id=search['id'],depth='quick',use_profile=False,request_token='fictional-estimate'))
 assert estimate['candidate_count']==28
 assert len(job_results.public_search(u,search)['data']['jobs'])==28
 assert job_results.public_search(u,search)['data']['archived_count']==0
 assert client.get('/api/job-search/searches/saved/results?view=all').json()['jobs'][0]['id']==wrong['id']
 assert client.get(f"/api/job-search/searches/{search['id']}/results?view=saved").json()['total']==1
 assert client.get(f"/api/job-search/searches/{search['id']}/jobs/{wrong['id']}").status_code==200
 assert [db.get(u,r['id'],r['kind']) for r in [search,wrong,application,review]]==protected
 with db.connect() as c:
  assert [tuple(r) for r in c.execute('SELECT * FROM cc_search_rows WHERE search_id=?',(search['id'],))]==before
  assert [tuple(r) for r in c.execute("SELECT * FROM entities WHERE user_id=? AND kind='job_snapshot' ORDER BY id",(u,))]==snapshots
 other=client.post('/api/auth/register',json={'username':'other-role-search','password':'fictional-password'}).json();onboard_test_account(other)
 assert client.get(f"/api/job-search/searches/{search['id']}/results").status_code==404
 assert client.get(f"/api/job-search/searches/{search['id']}/jobs/{wrong['id']}").status_code==404
 assert client.get('/api/job-search/searches/saved/results?view=all').json()['total']==0

def test_immutable_snapshot_scope_archives_and_unknown_legacy_scope(client,account):
 u=account['id'];wrong=db.save(u,'job',posting(THERMAL));right=db.save(u,'job',posting('AI Engineer',1));expired=db.save(u,'job',posting(THERMAL,2,deadline='2000-01-01'))
 query=SearchRequest(interests=ROLES).model_dump()
 search=job_results.save_search(u,{'jobs':[wrong,right,expired],'query':query})
 db.save(u,'job',{**right['data'],'title':'Mechanical Engineer'},right['id'])
 assert client.get(f"/api/job-search/searches/{search['id']}/results?view=all").json()['jobs'][0]['data']['title']=='AI Engineer'
 assert client.get(f"/api/job-search/searches/{search['id']}/results?view=archived").json()['jobs'][0]['data']['title']==THERMAL
 for scope in ({},{'discovery_kind':'for_you','query':query}):
  retained=job_results.save_search(u,{'jobs':[wrong],**scope})
  assert client.get(f"/api/job-search/searches/{retained['id']}/results?view=all").json()['total']==1
  assert len(job_results.all_rows(u,retained['id']))==1
 only_wrong=job_results.save_search(u,{'jobs':[wrong],'query':query})
 empty=client.get(f"/api/job-search/searches/{only_wrong['id']}/results?view=all&page=8").json()
 assert empty['total']==0 and empty['jobs']==[] and empty['page']==1 and empty['pages']==1

def test_new_searches_filter_all_source_results_locally(client,account,monkeypatch):
 board={'provider':'ashby','board':'fictional','company':'Fictional Employer'}
 monkeypatch.setattr(public_job_feeds,'catalog_boards',lambda user:[board])
 async def feed(*a,**k):
  return [posting(THERMAL),posting('AI/ML Engineer',1),posting('Data Platform Engineer',2)],{'stale':False,'cached':True,'last_success':db.now(),'revision':'fictional','error':''}
 monkeypatch.setattr(public_job_feeds,'employer',feed)
 result=asyncio.run(job_search.discover(account['id'],SearchRequest(interests=ROLES,sources=['ashby'],employer_boards=['ashby:fictional'])))
 assert {r['data']['title'] for r in result['jobs']}=={'AI/ML Engineer','Data Platform Engineer'}
 assert not result['ai_calls']
