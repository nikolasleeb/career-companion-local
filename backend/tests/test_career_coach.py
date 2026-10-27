"""Career Coach verified with fictional users and mocked providers only."""
import asyncio,copy,json,time
from datetime import datetime,timezone,timedelta
from concurrent.futures import ThreadPoolExecutor
import pytest
from app import db,config,credentials,career_coach as coach,coach_knowledge as knowledge,ai,cost_history
from app.network import ServiceError
from conftest import onboard_test_account

def run(value):return asyncio.run(value)
def make(client,**extra):
 response=client.post('/api/career-coach/chats',json={'goal':'Explore data science and Python projects',**extra});assert response.status_code==200,response.text;return response.json()
def reply(payload,**extra):
 source=payload['retrieved_chunks'][0];p=payload['profile']['sources'][0]
 evidence=[{'source_id':p['id'],'quote':p['text'][:80]}]
 citation=[{'chunk_id':source['chunk_id'],'quote':source['text'][:100]}]
 action={'kind':'project','title':'Build a small documented analysis','why':'Explore the goal through a concrete artifact.','steps':['Choose a fictional dataset','Write and test the analysis','Document decisions and limitations'],'horizon':'30','effort':'Estimate: 4–8 hours','prerequisites':'A willingness to practice','cost':'$999','uncertainty':'Review the resource and choose the right level.','evidence':evidence,'citations':citation}
 return {'answer':'Start with a small project tied to your goal.','direction':'Build practical experience, then explore relevant roles.','recommendations':[action],'questions':[],'needs_fresh_research':False,'citations':citation,'profile_evidence':evidence,**extra}
@pytest.fixture
def model(client,account,monkeypatch):
 credentials.save(account['id'],'sk-fictional-coach-key-never-sent');monkeypatch.setattr(config,'ENABLE_WEB_SEARCH',False);calls=[]
 async def structured(schema,payload,mode='economy',**kwargs):calls.append(copy.deepcopy(payload));assert kwargs['retry_allowed'] is False;return reply(payload),{'model':'fictional-coach','reasoning_effort':'low','mode':mode,'generated_at':db.now()}
 monkeypatch.setattr(ai,'structured',structured)
 return calls

def wait(client,task):
 for _ in range(150):
  response=client.get('/api/tasks/'+task['task_id']);assert response.status_code==200,response.text;value=response.json()
  if value['status'] not in ('queued','running'):return value
  time.sleep(.01)
 raise AssertionError('Fictional task did not finish')
def act(client,id,operation='plan',text='',token='fictional-request-0001'):
 response=client.post('/api/career-coach/chats/'+id+'/actions',json={'operation':operation,'text':text,'request_token':token});assert response.status_code==200,response.text;return wait(client,response.json())

def test_navigation_and_goal_saving_are_free_and_scoped(client,account,model):
 a=make(client);b=make(client,goal='Explore nursing and public health',title='Healthcare direction')
 assert len(client.get('/api/career-coach/chats').json()['chats'])==2
 assert len(client.get('/api/career-coach/chats?q=healthcare').json()['chats'])==1
 assert client.get('/api/career-coach/chats/'+a['id']).json()['messages']==[]
 edited=client.patch('/api/career-coach/chats/'+a['id'],json={'title':'A new title','goal':'Cloud engineering','expected_updated_at':a['updated_at']});assert edited.status_code==200
 assert client.patch('/api/career-coach/chats/'+a['id'],json={'title':'Stale edit','expected_updated_at':a['updated_at']}).status_code==409
 assert model==[]
 other=client.post('/api/auth/register',json={'username':'other-coach','password':'fictional-password'}).json();onboard_test_account(other);client.headers['X-CSRF-Token']=other['csrf']
 assert client.get('/api/career-coach/chats').json()['chats']==[]
 assert client.get('/api/career-coach/chats/'+a['id']).status_code==404
 assert client.post('/api/career-coach/chats/'+a['id']+'/roadmap',json={'message_id':'none'}).status_code==404


def test_education_and_account_key_required(client,account,monkeypatch):
 credentials.remove(account['id']);c=make(client)
 response=client.post('/api/career-coach/chats/'+c['id']+'/actions',json={'request_token':'no-key-request'})
 assert response.status_code in (422,503)
 fresh=client.post('/api/auth/register',json={'username':'no-education-coach','password':'fictional-password'}).json()
 assert client.get('/api/career-coach/chats').status_code==403


def test_rag_retrieval_across_disciplines_and_private_chat_index(client,account):
 u=account['id']
 assert len(knowledge.catalog())>=28
 for term,expected in [('Python','python'),('accounting','accounting'),('nursing','nursing'),('mechanical engineering','engineering'),('journalism','journalism'),('public health','public-health'),('research biology','research-methods')]:
  rows=knowledge.retrieve(u,'chat',term);assert expected in [v.get('id') for v in rows],(term,[r['title'] for r in rows])
 rows=knowledge.retrieve(u,'chat','');assert len(rows)>=3
 chunk={'chunk_id':'private:one','title':'Private research','url':'https://www.bls.gov/fictional','topics':['unicorn'],'text':'Unicorn molecular laboratory methods are a fictional private resource.','kind':'fetched','checked_at':db.now()}
 knowledge.index_chat(u,'first',[chunk]);assert any(s['chunk_id']=='private:one' for s in knowledge.retrieve(u,'first','unicorn'))
 assert not any(s['chunk_id']=='private:one' for s in knowledge.retrieve(u,'second','unicorn'))
 assert not any(s['chunk_id']=='private:one' for s in knowledge.retrieve('another-user','first','unicorn'))
 with db.connect() as c:assert not c.execute("SELECT 1 FROM cc_coach_knowledge WHERE scope='public' AND id='private:one'").fetchone()


def test_plan_progress_revisions_and_profile_not_mutated(client,account,model):
 u=account['id'];c=make(client);before=db.list_entities(u,'experience');result=act(client,c['id']);assert result['status']=='completed',result
 detail=client.get('/api/career-coach/chats/'+c['id']).json();assert len(detail['messages'])==2 and len(detail['plans'])==1
 plan=detail['plans'][0];a=plan['data']['actions'][0];assert a['cost']=='Not verified — check provider'
 assert plan['data']['sources'] and plan['data']['profile_snapshot']['sources']
 assert client.patch('/api/career-coach/chats/'+c['id']+'/actions/'+a['id'],json={'state':'completed'}).status_code==200
 assert db.list_entities(u,'experience')==before
 result=act(client,c['id'],'message','Could you make the next step clearer?','follow-up-0001');assert result['status']=='completed'
 detail=client.get('/api/career-coach/chats/'+c['id']).json();assert len(detail['plans'])==1 # Chat proposals need explicit acceptance.
 response=client.post('/api/career-coach/chats/'+c['id']+'/roadmap',json={'message_id':detail['messages'][-1]['id']});assert response.status_code==200,response.text
 detail=client.get('/api/career-coach/chats/'+c['id']).json();assert len(detail['plans'])==2
 assert detail['chat']['data']['progress'][a['id']]['state']=='completed'
 assert detail['plans'][0]['data']==plan['data']
 assert client.post('/api/career-coach/chats/'+c['id']+'/roadmap',json={'message_id':detail['messages'][-1]['id']}).json()['id']==response.json()['id']
 assert len(model)==2
 db.save(u,'experience',{'category':'skills','title':'New reviewed SQL skill','confirmed':True,'tools':'SQL'})
 assert client.get('/api/career-coach/chats/'+c['id']).json()['chat']['profile_revision']!=plan['data']['profile_revision']


def test_invalid_profile_or_source_reference_rejected(client,account,model):
 p=coach.profile(account['id']);sources=knowledge.retrieve(account['id'],'none','Python');payload={'profile':p,'retrieved_chunks':sources};value=reply(payload)
 value['recommendations'][0]['citations'][0]['quote']='Invented source claim'
 with pytest.raises(ServiceError):coach.validate_reply(value,p,sources)
 value=reply(payload);value['profile_evidence'][0]['source_id']='another-user:private'
 with pytest.raises(ServiceError):coach.validate_reply(value,p,sources)
 value=reply(payload);value['recommendations'][0]['evidence'][0]['quote']='I earned a credential that is not in Profile.'
 with pytest.raises(ServiceError):coach.validate_reply(value,p,sources)


def test_private_and_draft_profile_exclusion_and_research_topics(client,account):
 u=account['id']
 db.save(u,'experience',{'category':'employment','title':'Unreviewed secret employer','description':'UNREVIEWEDSECRET','confirmed':False})
 db.save(u,'experience',{'category':'education','title':'MSc Data Science','degree':'MS','major':'Data science','description':'Alice Example alice@example.com citizenship PRIVATESECRET\nPython and SQL coursework','confirmed':True})
 db.update_settings(u,{'name':'Alice Example','contact':'alice@example.com','authorized_us':'yes'})
 from app import private_profile
 # A deliberately marked encrypted fixture must never enter professional evidence.
 cipher=private_profile.seal(u,'authorization',{'authorized_us':'PRIVATESETTINGS'})
 with db.connect() as c:private_profile.store(c,u,'authorization',cipher)
 db.save(u,'work_style',{'private':'PRIVATEPERSONALITY'})
 p=coach.profile(u);raw=json.dumps(p)
 assert all(v not in raw for v in ('UNREVIEWEDSECRET','PRIVATESECRET','PRIVATESETTINGS','PRIVATEPERSONALITY','alice@example.com'))
 topics=knowledge.topics('Alice Example wants to work at PRIVATEEMPLOYER as a data scientist',p)
 assert 'Data science' in topics or 'data science' in topics
 assert all(v not in json.dumps(topics) for v in ('Alice','PRIVATEEMPLOYER','Example'))


def test_research_limits_citations_fetches_and_followup_reuse(client,account,model,monkeypatch):
 monkeypatch.setattr(config,'ENABLE_WEB_SEARCH',True);requests=[];fetches=[]
 async def web(body,**kwargs):
  requests.append(body);assert kwargs['retry_allowed'] is False
  return {'output':[{'content':[{'annotations':[{'type':'url_citation','url':'https://www.bls.gov/fictional/'+str(i)} for i in range(9)]+[{'type':'url_citation','url':'https://evil.example/claim'}]}]}],'usage':{'input_tokens':10,'output_tokens':10},'model':'fictional'}
 async def page(url,max_bytes):
  fetches.append(url);return {'status':200,'url':url,'content_type':'text/html','content':b'<html><title>Fictional BLS resource</title><main>Python data science learning opportunities. Practice careful analysis, assumptions and reproducibility. Official prerequisite and cost information must be checked on each provider page.</main></html>'}
 monkeypatch.setattr(ai,'call_api',web);monkeypatch.setattr(coach,'public_fetch',page)
 c=make(client,goal='Alice PRIVATECOMPANY data science');r=act(client,c['id']);assert r['status']=='completed',r
 assert len(requests)==1 and len(fetches)==6 and requests[0]['max_tool_calls']==4
 assert 'Alice' not in requests[0]['input'] and 'PRIVATECOMPANY' not in requests[0]['input']
 detail=client.get('/api/career-coach/chats/'+c['id']).json();old=detail['research'];assert old['data']['status']=='checked'
 assert all(s['kind']=='fetched' for s in old['data']['chunks'])
 r=act(client,c['id'],'message','Please suggest a smaller first step.','follow-up-0002');assert r['status']=='completed'
 assert len(requests)==1 and len(fetches)==6
 assert client.get('/api/career-coach/chats/'+c['id']).json()['research']['id']==old['id']
 r=act(client,c['id'],'research',token='refresh-0002');assert r['status']=='completed'
 assert len(requests)==2 and len(fetches)==12


def test_outages_and_invalid_sources_leave_previous_plan(client,account,model,monkeypatch):
 c=make(client);assert act(client,c['id'])['status']=='completed';before=client.get('/api/career-coach/chats/'+c['id']).json()
 async def broken(*a,**k):raise ServiceError('Fictional provider failure; outcome may be unknown.')
 monkeypatch.setattr(ai,'structured',broken)
 r=act(client,c['id'],'message','A saved question before the outage','outage-request');assert r['status']=='failed'
 after=client.get('/api/career-coach/chats/'+c['id']).json();assert after['plans']==before['plans'];assert after['messages']==before['messages']
 assert 'outage-request' in json.dumps(r)


def test_deduplication_token_conflicts_and_restart_no_automatic_calls(client,account,model,monkeypatch):
 c=make(client);body={'operation':'plan','request_token':'same-request-001'}
 first=client.post('/api/career-coach/chats/'+c['id']+'/actions',json=body).json();wait(client,first)
 second=client.post('/api/career-coach/chats/'+c['id']+'/actions',json=body).json();assert first['task_id']==second['task_id'];assert len(model)==1
 assert client.get('/api/career-coach/actions/same-request-001').json()['task_id']==first['task_id']
 assert client.post('/api/career-coach/chats/'+c['id']+'/actions',json={**body,'text':'different'}).status_code==409
 with db.connect() as con:con.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',('interrupted-coach',account['id'],'career_coach','running',json.dumps({'inputs':{'chat_id':c['id'],'request_token':'restart-request'}}),None,db.now(),db.now()))
 db.init();assert client.get('/api/tasks/interrupted-coach').json()['status']=='interrupted';assert len(model)==1


def test_backup_restoration_history_progress_and_private_index(client,account,model):
 u=account['id'];c=make(client);assert act(client,c['id'])['status']=='completed';detail=client.get('/api/career-coach/chats/'+c['id']).json();step=detail['plans'][0]['data']['actions'][0]['id']
 client.patch('/api/career-coach/chats/'+c['id']+'/actions/'+step,json={'state':'in_progress'})
 payload=client.get('/api/account/export').json();assert 'sk-fictional-coach-key' not in json.dumps(payload)
 assert {'coach_chat','coach_plan','coach_message','coach_research'}<={r['kind'] for r in payload['records']}
 other=client.post('/api/auth/register',json={'username':'restored-coach','password':'fictional-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
 before=knowledge.version();response=client.post('/api/account/import',files={'file':('backup.json',json.dumps(payload).encode(),'application/json')});assert response.status_code==200,response.text
 imported=client.get('/api/career-coach/chats').json()['chats'][0];assert imported['id']!=c['id']
 value=client.get('/api/career-coach/chats/'+imported['id']).json();assert len(value['messages'])==2 and len(value['plans'])==1
 assert value['plans'][0]['data']['chat_id']==imported['id'] and value['plans'][0]['data']['message_id']==value['messages'][-1]['id']
 assert value['chat']['data']['progress'][step]['state']=='in_progress'
 assert value['messages'][0]['created_at']==detail['messages'][0]['created_at']
 with db.connect() as con:assert not con.execute('SELECT 1 FROM cc_coach_knowledge WHERE scope=?',(other['id'],)).fetchone()
 assert knowledge.version()==before


def test_ledger_process_is_named_career_coach(client,account):
 context={'user_id':account['id'],'process':'career_coach','operation':'Coaching test'}
 id=cost_history.begin(context,{'model':'gpt-6-luna','service_tier':'default'})
 assert id
 with db.connect() as c:
  row=c.execute("SELECT payload FROM entities WHERE id=?",(id['id'],)).fetchone();assert json.loads(row[0])['process']=='career_coach'


def test_cross_chat_proposals_and_progress_cannot_mix(client,account,model):
 a=make(client);b=make(client,goal='Explore healthcare');assert act(client,a['id'])['status']=='completed'
 value=client.get('/api/career-coach/chats/'+a['id']).json();message=value['messages'][-1];step=value['plans'][0]['data']['actions'][0]['id']
 assert client.post('/api/career-coach/chats/'+b['id']+'/roadmap',json={'message_id':message['id']}).status_code==404
 assert client.patch('/api/career-coach/chats/'+b['id']+'/actions/'+step,json={'state':'completed'}).status_code==404
 assert not client.get('/api/career-coach/chats/'+b['id']).json()['plans']


def test_research_outage_no_retries_and_stale_source_flags(client,account,model,monkeypatch):
 monkeypatch.setattr(config,'ENABLE_WEB_SEARCH',True);calls=[]
 async def unavailable(*a,**kwargs):calls.append(kwargs);raise ServiceError('Fictional network outage')
 monkeypatch.setattr(ai,'call_api',unavailable)
 chat=make(client);assert act(client,chat['id'])['status']=='failed'
 assert calls==[{'retry_allowed':False}]
 value=client.get('/api/career-coach/chats/'+chat['id']).json();assert value['research'] is None and not value['messages']
 p=coach.profile(account['id']);source=knowledge.retrieve(account['id'],chat['id'],'Python')[0]
 stale={**source,'kind':'fetched','checked_at':(datetime.now(timezone.utc)-timedelta(days=31)).isoformat(),'stale':True}
 result=coach.validate_reply(reply({'profile':p,'retrieved_chunks':[stale]}),p,[stale])
 assert result['needs_fresh_research'] and result['recommendations'][0]['cost']=='Not verified — check provider'


def test_bounded_history_keeps_all_saved_turns(client,account,model):
 chat=make(client)
 for i in range(23):db.save(account['id'],'coach_message',{'chat_id':chat['id'],'role':'user','content':'Earlier discussion '+str(i)})
 assert act(client,chat['id'],'message','What is a useful next step?')['status']=='completed'
 assert len(model[-1]['conversation'])<=16
 value=client.get('/api/career-coach/chats/'+chat['id']).json();assert len(value['messages'])==25 and value['messages'][-1]['data']['context_limited']


def test_concurrent_duplicate_posts_only_dispatch_once(client,account,model,monkeypatch):
 calls=[]
 async def slow(schema,payload,mode='economy',**kwargs):
  calls.append(payload);await asyncio.sleep(.1);return reply(payload),{'model':'fictional','mode':mode}
 monkeypatch.setattr(ai,'structured',slow);chat=make(client)
 body={'operation':'plan','request_token':'parallel-same-token'}
 with ThreadPoolExecutor(max_workers=2) as pool:
  responses=list(pool.map(lambda _:client.post('/api/career-coach/chats/'+chat['id']+'/actions',json=body),range(2)))
 assert all(r.status_code==200 for r in responses),[r.text for r in responses]
 assert responses[0].json()['task_id']==responses[1].json()['task_id']
 assert wait(client,responses[0].json())['status']=='completed' and len(calls)==1


def test_account_deletion_removes_private_knowledge_and_chats(client,account,model):
 chat=make(client);assert act(client,chat['id'])['status']=='completed'
 knowledge.index_chat(account['id'],chat['id'],[{'chunk_id':'private:delete','title':'Private fictional resource','url':'https://www.bls.gov/example','kind':'fetched','text':'Fictional private learning resource for SQL practice.'}])
 response=client.request('DELETE','/api/account',json={'username':'student','password':'fictional-test-password'});assert response.status_code==200,response.text
 with db.connect() as c:
  assert not c.execute('SELECT 1 FROM cc_coach_knowledge WHERE scope=?',(account['id'],)).fetchone()
  assert not c.execute('SELECT 1 FROM entities WHERE user_id=?',(account['id'],)).fetchone()
  assert c.execute("SELECT count(*) FROM cc_coach_knowledge WHERE scope='public'").fetchone()[0]>=28


def test_multiple_majors_and_credential_names_without_identifiers(client,account):
 db.save(account['id'],'experience',{'category':'education','title':'Interdisciplinary degree','degree':'BS','majors':['Biology','Environmental science'],'confirmed':True})
 db.save(account['id'],'experience',{'category':'skills','title':'Certifications','confirmed':True,'certification_items':[{'name':'Fictional data credential','issuer':'Fictional Provider','credential_id':'PRIVATE-CREDENTIAL-IDENTIFIER','document_id':'private-document'}]})
 value=json.dumps(coach.profile(account['id']))
 assert 'Biology' in value and 'Environmental science' in value and 'Fictional data credential' in value
 assert 'PRIVATE-CREDENTIAL-IDENTIFIER' not in value and 'private-document' not in value


def test_import_rejects_altered_displayed_citations_and_roadmaps(client,account,model):
 chat=make(client);assert act(client,chat['id'])['status']=='completed'
 original=client.get('/api/account/export').json()
 for change in ('url','quote','plan'):
  payload=copy.deepcopy(original)
  message=next(r for r in payload['records'] if r['kind']=='coach_message' and r['data']['role']=='assistant')
  if change=='url':message['data']['reply']['citations'][0]['url']='javascript:alert(1)'
  elif change=='quote':message['data']['reply']['profile_evidence'][0]['quote']='Invented reviewed accomplishment'
  else:next(r for r in payload['records'] if r['kind']=='coach_plan')['data']['actions'][0]['title']='Altered unsupported action'
  response=client.post('/api/account/import',files={'file':('backup.json',json.dumps(payload).encode(),'application/json')})
  assert response.status_code==400,response.text
 assert len(client.get('/api/career-coach/chats').json()['chats'])==1
