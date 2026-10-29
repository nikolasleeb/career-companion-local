import asyncio,json,hashlib
from pathlib import Path
import pytest
from app import db,career_evidence as ev,career_wages as wage,career_reviews as review,career_explorer as ex,work_preferences as wp,credentials
from app.network import ServiceError
BASE='/api/career-explorer'
CODE='15-1243.00'
def row(text,learning=False):return {'id':'source1','record_id':'record1','title':'Project','field':'description','text':text,'learning':learning,'updated_at':'1'}
def match(name,text,learning=False):return ev.matches({'name':name},[row(text,learning)])
@pytest.mark.parametrize('name,text',[
 ('Amazon Web Services AWS software','Used AWS for cloud processing.'),('Structured query language SQL','Built SQL pipelines.'),('Microsoft Power BI','Used Power BI for reports.'),('Microsoft PowerPoint','Created a PPT presentation.'),('Apache Spark','Ran PySpark workloads.'),('Microsoft Excel','Used Excel for analysis.'),('Amazon Elastic Compute Cloud EC2','Deployed EC2 instances.')])
def test_aliases_preserve_quoted_source(name,text):
 v=match(name,text);assert v['match_status']=='found' and v['profile_references'][0]['text']==text

def test_no_broad_platform_product_false_matches_or_acronym_guesses():
 assert match('Amazon DynamoDB','Used AWS for cloud processing.')['match_status']=='unknown'
 assert match('Microsoft Office software','Prepared PPT presentations.')['match_status']=='unknown'
 assert match('Quality Control Analysis','QCA in an unrelated context.')['match_status']=='unknown'
 assert match('Installation','Business installation planning.')['match_status']=='unknown'
 assert match('Operations Monitoring','Command-center operations for robots.')['match_status']=='related'
 assert match('JavaScript','Wrote a JS note.')['match_status']=='unknown'
 assert match('Python','I have never used Python.')['match_status']=='unknown'
 assert match('Python','Python fundamentals',True)['match_status']=='related'

def test_confirmed_sources_and_learning_supporting_details_are_scoped(client,account):
 u=account['id']
 db.save(u,'experience',{'confirmed':True,'title':'Project source','category':'project','description':'Created AWS pipelines. Built SQL queries.'})
 db.save(u,'experience',{'confirmed':True,'title':'Python','category':'coursework'})
 db.save(u,'experience',{'confirmed':False,'title':'Secret draft','tools':'Docker'})
 with db.connect() as c:c.execute("INSERT INTO users VALUES(?,?,?,?,?)",('other','other-evidence','unused','{}',db.now()))
 db.save('other','experience',{'confirmed':True,'title':'Other account','tools':'Azure'})
 db.save(u,'profile_answer',{'answer_kind':'experience','status':'confirmed','text':'Used Excel for scheduling.'})
 db.save(u,'profile_answer',{'answer_kind':'motivation','status':'confirmed','text':'Want to use Docker.'})
 rows=ev.sources(u)
 assert ev.matches({'name':'Python'},rows)['match_status']=='related'
 assert ev.matches({'name':'Microsoft Excel'},rows)['match_status']=='found'
 assert all('Docker' not in r['text'] and 'Azure' not in r['text'] for r in rows)
 result=client.get(BASE+'/occupations/'+CODE).json();aws=next(x for x in result['technologies'] if x['name']=='Amazon Web Services AWS software')
 assert aws['match_status']=='found' and aws['profile_references']
 assert not db.list_entities(u,'usage_event')

def test_published_wage_integrity_and_sources():
 data=wage.data();assert data['metadata']['year']==2025 and len(data['areas'])>=500
 assert len(data['metadata']['sources'])==3
 for source in data['metadata']['sources']:
  assert source['url'].startswith('https://www.bls.gov/') and len(source['sha256'])==64
 for area,rows in data['wages'].items():
  assert area in data['areas']
  for values in rows.values():
   assert len(values)==10
   for group in (values[:5],values[5:]):
    nums=[x for x in group if isinstance(x,(float,int))]
    assert nums==sorted(nums)
 a=wage.pay('15-2051.01');assert a['shared_specialty'] and a['soc']=='15-2051'
 assert a['values']==wage.pay('15-2051.00')['values']
 assert a['values']['unit']=='year'
 assert wage.pay(CODE,'state:04')['area']['title']=='Arizona'
 assert any(x['type']=='metro' for x in wage.areas())

def test_missing_suppressed_bounds_and_units(monkeypatch):
 monkeypatch.setattr(wage,'data',lambda:{'areas':{'US':{'id':'US','title':'United States'},'state:01':{'id':'state:01','title':'Example'}},'metadata':{'year':2025,'reference':'May 2025','url':'https://www.bls.gov/oes/tables.htm','markers':{}},'titles':{'15-1243':'Database Architects'},'wages':{'US':{'15-1243':[100,200,300,400,'#',1,2,3,4,5]},'state:01':{'15-1243':['*']*5+[1,2,3,4,5]}}})
 local=wage.pay(CODE,'state:01');assert local['values']['unit']=='hour' and local['national']['p90']=='#'
 assert wage.pay('99-9999.00')['values'] is None
 assert wage.median(CODE,'state:01')==3

def test_salary_geography_and_sort(client,account):
 for area in ['US','state:04','metro:38060']:
  r=client.post(BASE+'/explore',json={'sort':'pay','salary_area':area,'limit':24});assert r.status_code==200,r.text
  rows=r.json()['results'];pay=[wage.sort_key(x['code'],area) for x in rows]
  assert pay==sorted(pay)
  assert all(x['salary']['area']['id']==area for x in rows)
 assert client.post(BASE+'/explore',json={'salary_area':'invented'}).status_code==422
 assert client.get(BASE+'/occupations/'+CODE+'?salary_area=state:04').json()['salary']['area']['id']=='state:04'
 assert not db.list_entities(account['id'],'usage_event')

def test_search_roundtrip_change_courses_stale_and_ownership(client,account):
 u=account['id'];course=db.save(u,'experience',{'category':'coursework','title':'Statistics','confirmed':True})
 c=client.get(BASE+'/options').json()['profile']['course_options'][0]
 query={'mode':'studies','major':'Data Science','profile_course_ids':[c['id']],'courses':'Databases','query':'data','industries':['54'],'preparation':'college','salary_area':'state:04','sort':'pay','limit':12,'offset':12}
 r=client.post(BASE+'/searches',json={'name':'My career search','query':query});assert r.status_code==200,r.text
 saved=r.json();id=saved['id'];q=saved['data']['query'];assert q['offset']==0 and q['salary_area']=='state:04'
 assert saved['data']['course_refs']==[{'id':c['id'],'title':'Statistics'}]
 load=client.get(BASE+'/searches/'+id+'/load').json();assert not load['unavailable_courses'] and load['data']['query']==q
 renamed=client.patch(BASE+'/searches/'+id,json={'name':'Renamed','expected_updated_at':saved['updated_at']});assert renamed.status_code==200
 assert client.put(BASE+'/searches/'+id,json={'name':'Stale','query':query,'expected_updated_at':saved['updated_at']}).status_code==409
 db.delete(u,course['id']);load=client.get(BASE+'/searches/'+id+'/load').json();assert load['unavailable_courses']==['Statistics']
 assert load['data']['query']['profile_course_ids']==[]
 other=client.post('/api/auth/register',json={'username':'searchother','password':'fictional-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
 assert client.get(BASE+'/searches').json()['searches']==[]
 assert client.get(BASE+'/searches/'+id+'/load').status_code==404
 assert client.delete(BASE+'/searches/'+id).status_code==404
 assert not db.list_entities(u,'usage_event')

def payload(client,account):
 db.save(account['id'],'experience',{'confirmed':True,'category':'project','title':'Database project','tools':'AWS; SQL; Power BI','description':'Built SQL pipelines.'})
 d=client.get(BASE+'/occupations/'+CODE).json()
 return {'profile_revision':d['profile_revision'],'work_style_revision':d['work_style']['revision'],'include_work_styles':True,'request_token':'fictional-review-request','mode':'economy'}
def response(p):
 source=next(s for s in p['profile_sources'] if 'SQL' in s['text'])
 return {'connections':[{'name':'Structured query language SQL','explanation':'This passage records SQL use; review the connection to this occupation.','references':[{'source_id':source['id'],'quote':source['text']}]}],'work_style_considerations':[],'limitations':'Does not establish proficiency.'}

def test_review_quotes_consent_staleness_and_failure_preserves_prior(client,account,monkeypatch):
 b=payload(client,account);u=account['id'];calls=[]
 value=wp.read(u);client.put('/api/profile/work-preferences',json={'expected_revision':value['revision'],'summary':'I prefer time to prepare before discussion.','reviewed':True,'use_for_ai':True})
 b['work_style_revision']=wp.read(u)['revision'];p=review.prepare(u,CODE,review.Request(**b))
 assert p['reviewed_work_style_summary'] and not any(k in p for k in ('answers','scores','report'))
 async def fake(schema,p,mode,**kw):calls.append((p,kw));return response(p),{'model':'simulated'}
 monkeypatch.setattr(review.ai,'structured',fake)
 saved=asyncio.run(review.execute(u,CODE,review.Request(**b)));assert not saved['outdated'] and calls[0][1]['retry_allowed'] is False
 old=db.get(u,review.identity(u,CODE),review.KIND)
 bad=response(p);bad['connections'][0]['references'][0]['quote']='Invented missing quote'
 with pytest.raises(ServiceError):review.validate(bad,p)
 async def failed(*args,**kwargs):raise ServiceError('Simulated output failure')
 monkeypatch.setattr(review.ai,'structured',failed)
 with pytest.raises(ServiceError):asyncio.run(review.execute(u,CODE,review.Request(**b)))
 assert db.get(u,old['id'],review.KIND)==old and len(calls)==1
 v=wp.read(u);client.put('/api/profile/work-preferences',json={'expected_revision':v['revision'],'summary':v['summary'],'reviewed':True,'use_for_ai':False})
 assert client.get(BASE+'/occupations/'+CODE+'/profile-review').json()['outdated']
 assert client.post(BASE+'/occupations/'+CODE+'/profile-review/estimate',json=b).status_code==409
 b['work_style_revision']=wp.read(u)['revision'];p=review.prepare(u,CODE,review.Request(**b));assert p['reviewed_work_style_summary']==''
 invalid={**response(p),'work_style_considerations':[{'text':'Unfounded','summary_quote':'I prefer','occupation_quote':p['occupation']['description'][:50]}]}
 with pytest.raises(ServiceError):review.validate(invalid,p)

def test_estimate_free_action_dedup_and_cancel(client,account,monkeypatch):
 b=payload(client,account);u=account['id'];credentials.put(u,'sk-fictional-not-real') if hasattr(credentials,'put') else credentials.save(u,'sk-fictional-not-real')
 calls=[]
 async def fake(schema,p,mode,**kw):
  calls.append(p);await asyncio.sleep(.05);return response(p),{'model':'simulated'}
 monkeypatch.setattr(review.ai,'structured',fake)
 before=db.list_entities(u,'usage_event');assert client.post(BASE+'/occupations/'+CODE+'/profile-review/estimate',json=b).status_code==200
 assert db.list_entities(u,'usage_event')==before and not calls
 a=client.post(BASE+'/occupations/'+CODE+'/profile-review/actions',json=b);assert a.status_code==200,a.text
 duplicate=client.post(BASE+'/occupations/'+CODE+'/profile-review/actions',json=b);assert duplicate.json()['task_id']==a.json()['task_id']
 import time
 for _ in range(50):
  result=client.get('/api/tasks/'+a.json()['task_id']).json()
  if result['status'] not in ('running','queued'):break
  time.sleep(.02)
 assert result['status']=='completed',result
 assert len(calls)==1
 other=client.post('/api/auth/register',json={'username':'reviewother','password':'fictional-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
 assert client.get(BASE+'/occupations/'+CODE+'/profile-review').json() is None
 assert client.get('/api/ai-actions/'+b['request_token']).status_code==404

def test_search_review_backup_restore_and_cleanup(client,account,monkeypatch):
 b=payload(client,account);u=account['id']
 async def fake(schema,p,mode,**kw):return response(p),{'model':'simulated'}
 monkeypatch.setattr(review.ai,'structured',fake);asyncio.run(review.execute(u,CODE,review.Request(**b)))
 r=client.post(BASE+'/searches',json={'name':'Database roles','query':{'query':'database'}});assert r.status_code==200
 backup=client.get('/api/account/export').json()
 def restore():return client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')})
 assert restore().status_code==200
 assert len(client.get(BASE+'/searches').json()['searches'])==1
 other=client.post('/api/auth/register',json={'username':'restoreexplorer','password':'fictional-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
 assert restore().status_code==200
 assert client.get(BASE+'/occupations/'+CODE+'/profile-review').json()['outdated']
 assert client.get(BASE+'/searches').json()['searches'][0]['data']['name']=='Database roles'
 preview=client.post('/api/account/cleanup/preview',json={'categories':['careers'],'action':'delete'});assert preview.status_code==200,preview.text
 p=preview.json();assert {'career_explorer_search','career_explorer_review'}<={r['kind'] for r in p['records']}
 assert client.post('/api/account/cleanup/apply',json={'preview_id':p['preview_id'],'confirmed':True}).status_code==200
 assert client.get(BASE+'/searches').json()['searches']==[] and client.get(BASE+'/occupations/'+CODE+'/profile-review').json() is None
 assert db.list_entities(u,review.KIND)

def test_review_cancelled_task_leaves_prior_result(client,account,monkeypatch):
 b=payload(client,account);u=account['id'];credentials.save(u,'sk-fictional')
 async def quick(schema,p,mode,**kw):return response(p),{'model':'simulated'}
 monkeypatch.setattr(review.ai,'structured',quick);asyncio.run(review.execute(u,CODE,review.Request(**b)));prior=db.get(u,review.identity(u,CODE),review.KIND)
 started=[]
 async def slow(*args,**kwargs):started.append(True);await asyncio.sleep(20);raise AssertionError('A cancelled request continued')
 monkeypatch.setattr(review.ai,'structured',slow)
 b['request_token']='fictional-cancel-request';r=client.post(BASE+'/occupations/'+CODE+'/profile-review/actions',json=b);assert r.status_code==200
 import time
 for _ in range(40):
  if started:break
  time.sleep(.01)
 assert started
 assert client.post('/api/tasks/'+r.json()['task_id']+'/cancel',json={}).status_code==200
 for _ in range(40):
  status=client.get('/api/tasks/'+r.json()['task_id']).json()['status']
  if status=='cancelled':break
  time.sleep(.01)
 assert status=='cancelled' and db.get(u,prior['id'],review.KIND)==prior

def test_profile_change_during_review_cannot_publish_stale_findings(client,account,monkeypatch):
 b=payload(client,account);u=account['id']
 async def changed(schema,p,mode,**kwargs):
  db.save(u,'experience',{'confirmed':True,'title':'New work','category':'project','tools':'SQL'})
  return response(p),{'model':'simulated'}
 monkeypatch.setattr(review.ai,'structured',changed)
 from fastapi import HTTPException
 with pytest.raises(HTTPException) as failure:asyncio.run(review.execute(u,CODE,review.Request(**b)))
 assert failure.value.status_code==409 and not db.list_entities(u,review.KIND)
