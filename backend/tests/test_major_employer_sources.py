import asyncio,json,re
import pytest
from app import db,integrations as x,employer_sources as sources,public_job_feeds as feeds,job_search,job_cache
from app.models import SearchRequest
from app.network import ServiceError

def test_amazon_us_pagination_fields_and_partial_inventory(monkeypatch):
 calls=[]
 async def fetch(url,params,**kw):
  calls.append(params);return {'jobs':[{'id_icims':'12345','title':'Cloud Engineer','country_code':'USA','city':'Richmond','state':'VA','job_path':'/en/jobs/12345/cloud-engineer','description':'Build data pipelines.','basic_qualifications':'Degree or equivalent.','preferred_qualifications':'SQL.','business_category':'aws','posted_date':'October  8, 2026'}]}
 monkeypatch.setattr(x,'fetch_json',fetch);rows=asyncio.run(sources.amazon(SearchRequest(interests=['Cloud infrastructure'])))
 assert len(calls)==1 and calls[0]['normalized_country_code[]']=='USA' and calls[0]['result_limit']==100
 assert rows[0]['division']=='aws' and rows[0]['country']=='USA' and rows[0]['published_at']=='2026-10-08T00:00:00+00:00' and not rows.complete
 assert 'Degree or equivalent.' in rows[0]['description'] and 'SQL.' in rows[0]['description']
 assert x.posting_key('https://amazon.jobs/en/jobs/12345/different-slug')==x.posting_key(rows[0]['url'])=='amazon:12345'

def test_apple_embedded_data_no_script_execution_missing_requirements(monkeypatch):
 from app import network
 data={'loaderData':{'search':{'totalRecords':1,'searchResults':[{'id':'200123-0157','postingTitle':'Data Engineer','jobSummary':'Work with data.','locations':[{'countryID':'iso-country-USA','countryName':'United States','name':'Austin'}],'postDateInGMT':'2026-10-28T01:00:00Z'}]}}}
 raw='window.__staticRouterHydrationData = JSON.parse('+json.dumps(json.dumps(data))+');do_not_execute_anything();'
 async def fetch(*a,**k):return {'status':200,'content':raw.encode()}
 monkeypatch.setattr(network,'public_fetch',fetch);rows=asyncio.run(sources.apple(SearchRequest(interests=['Data engineering'])))
 assert len(rows)==1 and rows[0]['country']=='US' and rows[0]['description_incomplete'] and not rows.complete
 assert x.posting_key(rows[0]['url']+'?team=data')!='' and rows[0]['employer_id']=='apple'
 async def bad(*a,**k):return {'status':200,'content':b'<html>changed</html>'}
 monkeypatch.setattr(network,'public_fetch',bad)
 with pytest.raises(ServiceError):asyncio.run(sources.apple(SearchRequest()))

def test_official_cache_is_query_scoped_and_partial_cannot_close(client,account,monkeypatch):
 calls=[]
 async def fetch(board,query):
  calls.append(query.title)
  return x.BoardRows([x.normalize_job('official','Data Analyst','Amazon','United States','Full-time role.','https://www.amazon.jobs/en/jobs/12345/example',country='US',employment_type='fulltime',published_at=db.now(),publication_source='Amazon date')],complete=False)
 monkeypatch.setattr(x,'board_jobs',fetch);board=next(b for b in feeds.CATALOG['employers'] if b['board']=='amazon' and b['provider']=='official')
 one=SearchRequest(title='data analyst',sources=['official']);two=SearchRequest(title='accountant',sources=['official'])
 first=asyncio.run(feeds.employer(board,request=one));asyncio.run(feeds.employer(board,request=one));asyncio.run(feeds.employer(board,request=two))
 assert calls==['data analyst','accountant'] and first[1]['partial']
 with db.connect() as c:assert c.execute('SELECT count(*) FROM cc_public_job_snapshots').fetchone()[0]==2;assert not c.execute('SELECT 1 FROM cc_job_observations WHERE closed_at IS NOT NULL').fetchone()
 assert sources.query_key(board,one)!=sources.query_key(board,two)

def test_preserve_explicit_source_off_and_upgrade_legacy_all(client,account):
 assert 'official' in SearchRequest(sources=['greenhouse','ashby','lever']).sources
 assert 'official' not in SearchRequest(sources=['greenhouse','ashby','lever'],employer_source_version=1).sources
 assert SearchRequest(sources=['lever']).sources==['lever']
 body=client.get('/api/job-search/preferences').json()['preferences']['data'];body['query']['sources']=['greenhouse','ashby','lever'];body['query']['employer_source_version']=1
 assert client.put('/api/job-search/preferences',json=body).status_code==200
 assert 'official' not in client.get('/api/job-search/preferences').json()['preferences']['data']['query']['sources']

def test_external_sites_not_selected_counted_or_fetched(client,account,monkeypatch):
 result=client.get('/api/settings/employer-sources').json();external=result['external_employers'];assert {'Microsoft','IBM','Wells Fargo'}<={r['company'] for r in external};assert all(r['coverage_status']=='external' for r in external)
 assert all(r['provider']!='external' for r in result['employers'])
 assert next(r for r in result['employers'] if r['key']=='official:amazon')['aliases']==['Amazon','AWS','Amazon Web Services']
 async def forbidden(*a,**k):raise AssertionError('Unknown source must never fall through')
 monkeypatch.setattr(x,'fetch_json',forbidden)
 with pytest.raises(ServiceError):asyncio.run(x.board_jobs({'provider':'unknown','board':'any','company':'Unknown'},None))
 with pytest.raises(ServiceError):asyncio.run(sources.jobs({'provider':'official','board':'unknown'},SearchRequest()))

def test_later_page_failure_preserves_completed_results(monkeypatch):
 calls=[]
 async def fetch(url,params,**kw):
  calls.append(params)
  if len(calls)>1:raise ServiceError('Temporary failure')
  return {'jobs':[{'id_icims':str(i),'title':'Cloud Engineer','country_code':'USA','description':'Build infrastructure.'} for i in range(1,101)]}
 monkeypatch.setattr(x,'fetch_json',fetch);rows=asyncio.run(sources.amazon(SearchRequest()))
 assert len(rows)==100 and len(calls)==2 and not rows.complete

def test_sitemap_uses_allowed_job_details_never_search_pages(monkeypatch):
 from app import network
 calls=[]
 async def fetch(url,*a):
  calls.append(url)
  if url.endswith('robots.txt'):return {'status':200,'content':b'User-agent: *\nDisallow: /search-jobs/\n'}
  if url.endswith('jobs_sitemap.xml'):return {'status':200,'content':b'<urlset><url><loc>https://www.capitalonecareers.com/job/richmond/data-engineer/1732/123</loc></url><url><loc>https://foreign.example/job/data-engineer</loc></url></urlset>'}
  return {'status':200,'url':url,'content':('<script type="application/ld+json">'+json.dumps({'@type':'JobPosting','title':'Data Engineer','description':'Build data pipelines.','datePosted':'2026-10-28','jobLocation':{'address':{'addressLocality':'Richmond','addressRegion':'VA','addressCountry':'US'}}})+'</script>').encode()}
 monkeypatch.setattr(network,'public_fetch',fetch);rows=asyncio.run(sources.sitemap_jobs('capitalone',SearchRequest(interests=['Data engineering'])))
 assert len(rows)==1 and rows[0]['country']=='US' and not rows.complete
 assert len(calls)==3 and not any('/search-jobs' in u for u in calls) and all('capitalonecareers.com' in u for u in calls)

def test_sitemap_policy_blocks_automation(monkeypatch):
 from app import network
 calls=[]
 async def fetch(url,*a):calls.append(url);return {'status':200,'content':b'User-agent: *\nDisallow: /\n'}
 monkeypatch.setattr(network,'public_fetch',fetch)
 with pytest.raises(ServiceError,match='restricts'):asyncio.run(sources.sitemap_jobs('intuit',SearchRequest()))
 assert len(calls)==1
