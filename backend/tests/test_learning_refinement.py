import copy,json
import pytest
from app import db,skills,learning_topics,ai,credentials,career_coach,plan_progress
from test_career_coach import make,act,model,wait

def record(user,**extra):return db.save(user,'experience',{'category':'skills','title':'Technical skills','confirmed':True,'skill_items':[{'name':'Python','level':'intermediate'},{'name':'PowerBI','level':'unknown'}],**extra})

def test_concrete_topics_sources_aliases_and_no_narrative_inference(client,account):
 u=account['id'];record(u);record(u,confirmed=False,skill_items=[{'name':'Secret draft','level':'unknown'}])
 db.save(u,'experience',{'title':'Narrative only','category':'project','confirmed':True,'description':'Used Linux and Azure.'})
 client.put('/api/profile/career-goals',json={'text':'Education, projects, certifications, engineering and science. Learn SQL and Python.','expected_revision':0})
 job=db.save(u,'job',{'title':'Analyst','description':'Use SQL and statistics. Citizenship and disability status are private. Must hold a degree.'})
 value=client.get('/api/skills/options?job_id='+job['id']).json();topics=value['suggested_topics'];labels={v['label'] for v in topics}
 assert {'SQL','Statistics','Python','Power BI'}<=labels
 assert not {'education','projects','certifications','engineering','science','Linux','Azure','Secret draft'}&labels
 python=next(t for t in topics if t['label']=='Python');assert {s['kind'] for s in python['sources']}=={'goal','profile'}
 assert topics[0]['sources'][0]['kind']=='posting'
 assert 'Secret' not in json.dumps(value) and not db.list_entities(u,'usage_event')
 assert len({t['id'] for t in topics})==len(topics)

def test_field_filter_empty_profile_and_isolation(client,account):
 record(account['id']);value=client.get('/api/skills/options?field=Arts%20%26%20Communication').json()
 assert not {'Python','Power BI'}&set(value['suggestions'])
 assert client.get('/api/skills/options?field=invented').status_code==422
 job=db.save(account['id'],'job',{'title':'Private job','description':'Python'})
 other=client.post('/api/auth/register',json={'username':'learningother','password':'fictional-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
 assert not client.get('/api/skills/options').json()['suggestions']
 assert client.get('/api/skills/options?job_id='+job['id']).status_code==404

def test_catalog_titles_classification_and_unique_resource_ids():
 rows=skills.library();by={r['id']:r for r in rows}
 assert len(rows)==len(by)
 assert by['practice']['title']=='University of Arizona — Center for Career Readiness'
 assert by['practice']['resource_type']=='career_support'
 assert by['git']['title']=='GitHub Learn'
 for id in ('codecademy-python','codecademy-sql','datacamp-python','datacamp-sql'):
  assert by[id]['resource_type']=='learning' and by[id]['learning_topics'] and by[id]['access']
 assert 'subscription' in by['datacamp-python']['access']
 assert all(r['learning_topics']==[] or all(learning_topics.clean([t]) for t in r['learning_topics']) for r in rows)

def test_focused_ai_uses_neutral_topics_valid_resource_ids_and_no_retry(client,account,monkeypatch):
 credentials.save(account['id'],'sk-fictional-learning-key');calls=[]
 async def fake(schema,payload,mode,**kw):
  calls.append(payload);assert kw['retry_allowed'] is False
  assert payload['selected_topics']==['Python'] and 'confirmed_gaps' not in payload
  assert 'timeline' in payload['task'] and 'never confirmed weaknesses' in payload['task']
  return {'priorities':['Write a loop and test its result.'],'resource_ids':['datacamp-python'],'questions':[]},{'model':'fictional'}
 monkeypatch.setattr(ai,'structured',fake)
 for body in ({'selected_topics':['Python']},{'confirmed_gaps':['Python']}):
  response=client.post('/api/preparation',json=body);assert response.status_code==200,response.text
  result=wait(client,response.json());assert result['status']=='completed',result
  data=result['result']['data'];assert data['selected_topics']==['Python'] and data['resources'][0]['id']=='datacamp-python'
 assert len(calls)==2
 assert not db.list_entities(account['id'],'coach_plan')
 async def invalid(*a,**kw):return {'priorities':['Exercise'],'resource_ids':['invented'],'questions':[]},{}
 monkeypatch.setattr(ai,'structured',invalid)
 result=wait(client,client.post('/api/preparation',json={'selected_topics':['Python']}).json());assert result['status']=='failed'
 assert len(db.list_entities(account['id'],'prep'))==2

def test_plan_learning_links_preserve_versions_progress_and_account_ownership(client,account,model):
 u=account['id'];chat=make(client);result=act(client,chat['id']);assert result['status']=='completed'
 plan=db.list_entities(u,'coach_plan')[0];action=plan['data']['actions'][0];action['learning_topics']=['SQL','Python']
 db.save(u,'coach_plan',plan['data'],plan['id'])
 path='/api/career-coach/plans/'+plan['id']+'/progress';progress=client.get(path).json()
 progress=client.patch(path,json={'milestone_id':action['id'],'completed':True,'expected_revision':progress['revision']}).json();assert progress['completed']>0
 before=copy.deepcopy(db.get(u,plan['id'],'coach_plan'));saved_progress=db.list_entities(u,'coach_plan_progress')
 link=client.get('/api/skills/plan-link',params={'plan_id':plan['id'],'milestone_id':action['id']});assert link.status_code==200
 assert link.json()['learning_topics']==['SQL','Python'] and link.json()['chat_id']==chat['id']
 assert client.get('/api/skills/plan-link',params={'plan_id':plan['id'],'milestone_id':'missing'}).status_code==404
 assert db.get(u,plan['id'],'coach_plan')==before and db.list_entities(u,'coach_plan_progress')==saved_progress
 other=client.post('/api/auth/register',json={'username':'planlinkother','password':'fictional-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
 assert client.get('/api/skills/plan-link',params={'plan_id':plan['id'],'milestone_id':action['id']}).status_code==404

def test_legacy_links_read_without_mutation_and_reviewed_metadata_backup(client,account,model):
 u=account['id'];chat=make(client);result=act(client,chat['id']);plan=db.list_entities(u,'coach_plan')[0]

 for progress in db.list_entities(u,'coach_plan_progress'):db.delete(u,progress['id'])
 message=db.get(u,plan['data']['message_id'],'coach_message');a=message['data']['reply']['recommendations'][0]
 a.pop('learning_topics',None);a['steps'][0]='Practice SQL joins'
 message=db.save(u,'coach_message',message['data'],message['id'])
 plan['data']['actions']=copy.deepcopy(message['data']['reply']['recommendations']);plan['data']['user_reviewed_edits']=True
 db.save(u,'coach_plan',plan['data'],plan['id']);before=db.list_entities(u,'coach_plan')
 loaded=client.get('/api/career-coach/chats/'+chat['id']).json()['plans'][0]
 assert loaded['data']['actions'][0]['learning_topics']==['SQL']
 assert db.list_entities(u,'coach_plan')==before
 backup=client.get('/api/account/export').json();imported=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')});assert imported.status_code==200,imported.text
 assert plan_progress.step_ids(plan)==plan_progress.step_ids({**plan,'data':{**plan['data'],'actions':[{**a,'learning_topics':['Python']}]}})
 assert learning_topics.milestone({'title':'SQL practice','steps':[],'learning_topics':[]})==[]
