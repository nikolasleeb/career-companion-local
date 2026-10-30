import collections,copy,json
import pytest
from app import db,skills,skill_catalog,ai,credentials
from test_career_coach import wait

def test_reviewed_catalog_coverage_unique_destinations_aliases_and_metadata():
 catalog=skill_catalog.data();topics=catalog['skills'];resources=catalog['resources'];assert len(topics)>=300 and len(resources)>=400
 sc=collections.Counter(s['field'] for s in topics);rc=collections.Counter(r['field'] for r in resources)
 assert sc['Tech & Data']>=180 and rc['Tech & Data']>=220
 for f in skills.FIELDS:
  assert sc[f]>=(180 if f=='Tech & Data' else 20) and rc[f]>=(220 if f=='Tech & Data' else 30)
 assert len({s['id'] for s in topics})==len(topics);assert len({r['id'] for r in resources})==len(resources)
 assert len({r['url'].removeprefix('https://').removeprefix('www.').rstrip('/') for r in resources})==len(resources)
 for s in topics:
  assert any(s['id'] in r['topic_ids'] for r in skills.library() if r['resource_type']=='learning')
  assert all(t in skill_catalog.index() for t in s['related']) and s['description']
 for r in resources:
  assert r['provider'] and r['description'] and r['reviewed_at'] and r['source_title'] and r['review_method']
  assert r['level'] in ('beginner','intermediate','advanced','all','unspecified')
  assert r['access_kind'] in ('free','freemium','paid','unknown')
 assert skill_catalog.resolve('Apache Spark')==skill_catalog.resolve('Spark')
 assert skill_catalog.resolve('Spark')!=skill_catalog.resolve('PySpark')
 for topic in ('Spark','PySpark','Spark SQL','Structured Streaming'):
  assert any(skill_catalog.resolve(topic) in r['topic_ids'] for r in skills.library())
 urls={r['url'] for r in resources};assert 'https://spark.apache.org/docs/latest/quick-start.html' in urls and 'https://spark.apache.org/docs/latest/api/python/getting_started/index.html' in urls
 assert len({r['id'] for r in skills.library()})==len(skills.library())

def test_pagination_sort_facets_source_filter_and_direct_related(client,account):
 original=db.list_entities(account['id'],'experience')
 params={'sort':'title'};first=client.get('/api/skills/topics',params=params).json();second=client.get('/api/skills/topics',params={**params,'offset':24}).json()
 assert len(first['topics'])==len(second['topics'])==24 and not {t['id'] for t in first['topics']}&{t['id'] for t in second['topics']}
 assert first==client.get('/api/skills/topics',params=params).json()
 assert [t['label'].casefold() for t in first['topics']]==sorted(t['label'].casefold() for t in first['topics'])
 assert client.get('/api/skills/topics?source=profile').json()['total']==0
 names=['Python','SQL','Git','AWS','Linux','PySpark','Spark SQL','Structured Streaming','Python logging','Python unit testing','Python CSV processing','Python JSON processing']
 db.save(account['id'],'experience',{'category':'skills','confirmed':True,'title':'Reviewed skills','skill_items':[{'name':n} for n in names]})
 sourced=client.get('/api/skills/topics?source=profile').json();assert sourced['total']==len(names)
 assert client.get('/api/skills/topics?source=posting').json()['total']==0
 for field in skills.FIELDS:
  v=client.get('/api/skills/topics',params={'field':field,'sort':'resources'}).json();assert all(t['field']==field for t in v['topics']);assert [t['resource_count'] for t in v['topics']]==sorted([t['resource_count'] for t in v['topics']],reverse=True)
 value=client.get('/api/skills/resources',params={'topics':'Spark','sort':'relevance'}).json();assert value['direct_count'] and value['related_count'];assert len(value['resources'])<=12
 assert value['resources'][0]['match_kind']=='direct'
 for provider in value['providers']:
  rows=client.get('/api/skills/resources',params={'topics':'Spark','provider':provider,'access':'free','level':'unspecified','sort':'provider'}).json();assert all(r['provider']==provider and r['level']=='unspecified' and r['access_kind']=='free' for r in rows['resources'])
 assert client.get('/api/skills/resources?access=invented').status_code==422
 assert client.get('/api/skills/topics?group=invented').status_code==422
 assert not db.list_entities(account['id'],'usage_event') and db.list_entities(account['id'],'experience')[-1]==original[-1]

def save(user,topics,job=''):
 return db.save(user,'prep',{'job_id':job,'selected_topics':topics,'priorities':['Fictional practice task'],'resources':[]})
def test_relevant_sets_legacy_aliases_target_history_and_no_mutation(client,account):
 u=account['id'];old=save(u,['Git','Python']);spark=save(u,['Apache Spark','SQL']);job=db.save(u,'job',{'title':'Specific opportunity'});target=save(u,['Spark'],job['id'])
 before=db.list_entities(u,'prep');rows=client.get('/api/skills/practice?topics=Spark').json();assert rows['matching']['id']==spark['id'];assert old['id'] in {r['id'] for r in rows['history']};assert rows['matching']['topic_refs'][0]['id']=='spark'
 assert client.get('/api/skills/practice?topics=Spark|Python').json()['matching'] is None
 assert client.get('/api/skills/practice',params={'topics':'Spark','job_id':job['id']}).json()['matching']['id']==target['id']
 assert client.get('/api/skills/practice?topics=PySpark').json()['matching'] is None
 assert client.get('/api/skills/practice?topics=PySpark&q=Specific').json()['total']==1
 assert db.list_entities(u,'prep')==before
 legacy=db.save(u,'prep',{'confirmed_gaps':['Apache Spark'],'job_id':None,'priorities':['Original text']});assert client.get('/api/skills/practice?topics=Spark').json()['matching']['id']==legacy['id']
 backup=client.get('/api/account/export').json();assert client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')}).status_code==200
 assert any(r['data'].get('confirmed_gaps')==['Apache Spark'] for r in db.list_entities(u,'prep'))

def taskrow(user,id,status,result):
 with db.connect() as c:c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',(id,user,'preparation',status,json.dumps(result),'',db.now(),db.now()))
@pytest.mark.parametrize('status',['queued','running','cancelling'])
def test_deletion_blocked_for_active_preparation(client,account,status):
 row=save(account['id'],['Python']);taskrow(account['id'],'active',status,{'inputs':{}})
 assert client.delete('/api/skills/practice/'+row['id']).status_code==409;assert db.get(account['id'],row['id'])

def test_account_owned_delete_redacts_cached_task_keeps_other_data(client,account):
 u=account['id'];row=save(u,['Python']);other=save(u,['SQL']);taskrow(u,'finished','completed',{'_task_result':row,'_task_progress':{'label':'Fictional practice task'}})
 usage=db.save(u,'usage_event',{'event_key':'kept','estimated_cost_usd':.01});plan=db.save(u,'coach_plan',{'snapshot':'Fictional practice task'});profile=copy.deepcopy(db.list_entities(u,'experience'))
 foreign=client.post('/api/auth/register',json={'username':'catalogother','password':'fictional-password'}).json();client.headers['X-CSRF-Token']=foreign['csrf']
 assert client.delete('/api/skills/practice/'+row['id']).status_code==404
 assert client.get('/api/skills/practice').json()['matching'] is None
 assert client.get('/api/skills/plan-link?plan_id='+plan['id']+'&milestone_id=x').status_code==404
 logged=client.post('/api/auth/login',json={'username':'student','password':'fictional-test-password'}).json();client.headers['X-CSRF-Token']=logged['csrf']
 assert client.delete('/api/skills/practice/'+row['id']).status_code==200
 assert not db.get(u,row['id']);assert db.get(u,other['id']) and db.get(u,usage['id']) and db.get(u,plan['id'])
 assert db.list_entities(u,'experience')==profile
 assert client.get('/api/tasks/finished').status_code==410
 with db.connect() as c:assert 'Fictional practice task' not in c.execute('SELECT result FROM tasks WHERE id=?',('finished',)).fetchone()[0]

def test_ai_candidates_bounded_failure_preserves_sets_and_legacy_strings(client,account,monkeypatch):
 u=account['id'];old=save(u,['Git']);credentials.save(u,'sk-fictional-key');calls=[]
 async def fake(schema,payload,mode,**kwargs):
  calls.append(payload);assert len(payload['resource_catalog'])<=24;assert kwargs['retry_allowed'] is False
  assert payload['selected_topics']==['Apache Spark','Python','SQL'];assert 'skills' not in payload and 'topic_catalog' not in payload
  return {'priorities':['One focused activity'],'resource_ids':[r['id'] for r in payload['resource_catalog'][:5]],'questions':[]},{}
 monkeypatch.setattr(ai,'structured',fake)
 v=wait(client,client.post('/api/preparation',json={'selected_topics':['Apache Spark','Python','SQL']}).json());assert v['status']=='completed',v
 record=v['result'];assert record['data']['topic_refs'][0]['id']=='spark' and len(record['data']['resources'])<=5
 async def failure(*a,**kw):raise ai.ServiceError('Simulated provider failure')
 monkeypatch.setattr(ai,'structured',failure)
 v=wait(client,client.post('/api/preparation',json={'selected_topics':['Spark']}).json());assert v['status']=='failed';assert len(calls)==1
 assert db.get(u,old['id']) and db.get(u,record['id'])
