"""Offline Coach access and local published-table contract; all AI is simulated."""
import asyncio,json,time
import pytest
from app import db,coach_access as access,coach_bls as bls,salary_areas as areas,assistant_context as context,knowledge_assistant as coach,ai,credentials,career_coach,explicit_context,career_wages as wages
from app.network import ServiceError
CODE='15-1243.00'
def wait(client,response):
 assert response.status_code==200,response.text
 for _ in range(300):
  task=client.get('/api/tasks/'+response.json()['task_id']).json()
  if task['status'] not in ('queued','running','cancelling'):return task
  time.sleep(.01)
 raise AssertionError('Simulated task did not complete')
def test_area_aliases_and_every_cross_state_member():
 for term in ('DMV','NoVA','Northern Virginia','Washington DC','Washington D.C.'):
  assert areas.search(term)[0]['id']=='metro:47900'
 metro=next(a for a in areas.catalog() if a['id']=='metro:47900')
 assert set(metro['state_codes'])=={'DC','VA','MD','WV'}
 for state in ('Virginia','VA','MD','WV','District of Columbia'):
  assert 'metro:47900' in [a['id'] for a in areas.search(state,600)]
 assert bls.occupations('DE')['clarification_required']
 assert any(c['code']=='15-1243.00' for c in bls.occupations('data engineer')['candidates'])
 assert bls.occupations('Database Architects')['candidates'][0]['code']==CODE

def test_bls_rankings_are_local_deterministic_and_bounded():
 request={'operation':'compare_metros','occupation_code':CODE,'state':'VA'}
 a=bls.run(request);assert a==bls.run(request) and 0<len(a['rows'])<=10
 assert all('VA' in r['area']['state_codes'] for r in a['rows'])
 assert [r['published_floor'] if r['bounded'] else r['value'] for r in a['rows']]==sorted([r['published_floor'] if r['bounded'] else r['value'] for r in a['rows']],reverse=True)
 assert a['ranking_measure']=='median' and a['unit']=='year' and a['source_url'].startswith('https://www.bls.gov/')
 assert len(bls.run({**request,'limit':20})['rows'])<=20
 assert bls.run({'operation':'wages','occupation_code':CODE,'salary_area':'DMV'})['salary']['area']['id']=='metro:47900'
 assert bls.run(request,[bls.BLS_ID])['unavailable']
 assert bls.run({'operation':'wages','query':'DE'})['clarification_required']
 assert bls.run({**request,'area_ids':['state:51']})['rows']==a['rows']
 with pytest.raises(ValueError):bls.Lookup(**{**request,'limit':21})
 with pytest.raises(ValueError):bls.Lookup(operation='sql',query='select *')

def test_missing_units_bounds_and_no_national_fallback_in_rank(monkeypatch):
 catalog=[{'id':'US','type':'national','title':'United States','state_codes':[]},{'id':'metro:1','type':'metro','title':'A, VA','state_codes':['VA']},{'id':'metro:2','type':'metro','title':'B, VA','state_codes':['VA']},{'id':'metro:3','type':'metro','title':'C, VA','state_codes':['VA']}]
 values={'metro:1':[1,2,'#',4,5,1,2,30,40,50],'metro:2':[1,2,'*',4,5,1,2,20,40,50],'metro:3':None}
 monkeypatch.setattr(areas,'catalog',lambda:catalog)
 monkeypatch.setattr(wages,'data',lambda:{'areas':{a['id']:a for a in catalog},'metadata':{'reference':'May 2025','url':'https://www.bls.gov/oes/tables.htm'}})
 def pay(code,id='US'):
  v=values.get(id)
  return {'values':{'annual':v[:5],'hourly':v[5:]} if v else None,'reporting_threshold':{'year':239200,'hour':115},'occupation_title':'Database Architects','shared_specialty':False}
 monkeypatch.setattr(wages,'pay',pay)
 annual=bls.run({'operation':'compare_metros','occupation_code':CODE});assert len(annual['rows'])==1 and annual['excluded_missing_or_suppressed']==2
 assert annual['rows'][0]['bounded'] and annual['rows'][0]['value']=='#' and annual['rows'][0]['published_floor']==239200
 hourly=bls.run({'operation':'compare_metros','occupation_code':CODE,'unit':'hour'});assert [r['value'] for r in hourly['rows']]==[30,20]

def test_registry_coverage_drafts_and_account_isolation(client,account):
 u=account['id'];expected=[]
 profile=db.save(u,'experience',{'category':'certification','confirmed':True,'title':'Credential','certification_items':[{'name':'Professional exam','issuer':'Example','credential_id':'SECRET_CREDENTIAL'}]});expected.append(profile['id'])
 db.save(u,'experience',{'confirmed':False,'description':'SECRET_DRAFT'})
 db.save(u,'profile_answer',{'answer_kind':'eligibility','status':'confirmed','text':'SECRET_PRIVATE'})
 db.save(u,'profile_answer',{'answer_kind':'experience','status':'confirmed','title':'Professional','text':'Reviewed source passage'})
 fixtures={
 'resume':{'sections':[{'entries':[{'title':'Final resume','bullets':['Reviewed bullet']}]}]},
 'cover_letter':{'content':{'paragraphs':['Saved final letter']}},'application':{'title':'Tracker','status':'interviewing','private_answers':'SECRET_PRIVATE','offer_details':'SECRET_OFFER','history':[{'date':'2026-10-28','status':'applied','note':'SECRET_NOTE'}],'interviews':[{'date':'2026-11-01','type':'Technical','outcome':'SECRET_OUTCOME'}]},
 'saved_career':{'code':CODE,'title':'Database Architects'},'career_explorer_search':{'name':'My search','query':{'salary_area':'US'}},
 'analysis':{'summary':'Completed analysis'},'prep':{'priorities':['Saved skills practice']},'coach_plan':{'direction':'Reviewed saved direction','actions':[]},
 'project_analysis':{'summary':'Completed project material','findings':[]},'interview_attempt':{'feedback':{'summary':'Completed feedback','useful_details':['SECRET_PROPOSAL']}}}
 for kind,d in fixtures.items():expected.append(db.save(u,kind,d)['id'])
 db.save(u,'resume_revision',{'snapshot':fixtures['resume']})
 db.save(u,'cover_revision',fixtures['cover_letter'])
 db.save(u,'prep',{'status':'running','summary':'SECRET_RUNNING'})
 with db.connect() as c:c.execute('INSERT INTO users VALUES(?,?,?,?,?)',('other-coach','other-coach','unused','{}',db.now()))
 db.save('other-coach','resume',{'headline':'SECRET_OTHER'})
 rows=list(access.records(u));encoded=json.dumps(rows);assert all(id in encoded for id in expected)
 assert 'Professional exam' in encoded and '2026-11-01' in encoded and 'SECRET' not in encoded
 assert all(r['revision'] and r['status'] for r in rows)
 assert '2026-11-01' in json.dumps(context.sources(u))
 assert all(r['record_id'] not in expected for r in access.records('other-coach'))
 assert all(v['record_id']!=profile['id'] for v in context.retrieve(u,'credential',excluded=[profile['id']]))

def test_derived_outputs_respect_consent_exclusions_and_ownership(client,account):
 u=account['id'];p=db.save(u,'experience',{'confirmed':True,'title':'Evidence','description':'Data pipelines'})
 for key,value in [('explicit_context_snapshot',[{'kind':'explicit_offer','text':'SECRET_OFFER'}]),('source_snapshot',[{'kind':'private_answer','text':'SECRET_PRIVATE'}]),('career_goal_selection',{'goal_ids':['x']}),('source_snapshot',[{'kind':'preference','text':'SECRET_STYLE'}]),('source_snapshot',[{'record_id':'a'*32,'text':'SECRET_FOREIGN'}])]:
  r=db.save(u,'coach_plan',{'direction':'SECRET_DERIVED','actions':[],key:value});assert access.project(u,r) is None
 derived=db.save(u,'analysis',{'summary':'Derived source','source_snapshot':[{'record_id':p['id'],'kind':'reviewed_profile'}]})
 assert derived['id'] in json.dumps(context.retrieve(u,'Derived',pinned=[derived['id']]))
 assert derived['id'] not in json.dumps(context.retrieve(u,'Derived',excluded=[p['id']]))
 db.save(u,'project_snapshot',{'experience_id':p['id'],'files':[{'text':'SECRET_UNANALYZED'}]})
 assert 'SECRET' not in json.dumps(list(access.records(u)))

def fake_lookup(calls,bad=False,second_round=False):
 async def model(schema,payload,*args,**kwargs):
  calls.append(payload.copy());assert kwargs['retry_allowed'] is False
  if not payload.get('lookup_results'):return {'answer':'Checking local tables.','lookup_requests':[{'operation':'compare_metros','occupation_code':CODE,'state':'VA'}]}, {'model':'simulated'}
  source=next(s for s in payload['source_catalog'] if s['kind']=='bls_lookup');amount=payload['lookup_results'][0]['result']['rows'][0]['value']
  return {'answer':'The published median annual pay is $'+('999999999' if bad else f'{amount:,}')+'.','references':[{'source_id':source['source_id'],'quote':'compare_metros'}],'lookup_requests':[{'operation':'find_salary_areas','query':'VA'}] if second_round else []},{'model':'simulated'}
 return model

def test_coach_single_local_round_snapshot_dedupe_and_backup(client,account,monkeypatch):
 u=account['id'];credentials.save(u,'sk-fictional-not-real');calls=[]
 monkeypatch.setattr(ai,'structured',fake_lookup(calls))
 async def no_web(*args,**kwargs):raise AssertionError('Bundled salary lookup must not force web research')
 monkeypatch.setattr(career_coach,'research',no_web)
 body={'text':'Which cities pay database architects the highest salary in VA?','request_token':'local-tables-mocked'}
 first=client.post('/api/knowledge-coach/chats/new/messages',json=body);t=wait(client,first);assert t['status']=='completed',t
 assert len(calls)==2 and len(calls[1]['lookup_results'])==1
 message=t['result']['messages'][-1]['data'];assert message['local_lookup_used'] and not message['research_used']
 assert any(s['kind']=='bls_lookup' for s in message['source_snapshot'])
 assert client.post('/api/knowledge-coach/chats/new/messages',json=body).json()['task_id']==first.json()['task_id'] and len(calls)==2
 backup=client.get('/api/account/export').json();assert client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')}).status_code==200

@pytest.mark.parametrize('bad,second_round',[(True,False),(False,True)])
def test_bad_local_answer_preserves_previous_chat(client,account,monkeypatch,bad,second_round):
 u=account['id'];credentials.save(u,'sk-fictional-not-real');chat=client.post('/api/knowledge-coach/chats',json={'title':'Keep this chat'}).json()
 old=db.save(u,'assistant_message',{'chat_id':chat['id'],'role':'user','content':'Preserved prior message'})
 monkeypatch.setattr(ai,'structured',fake_lookup([],bad,second_round))
 t=wait(client,client.post('/api/knowledge-coach/chats/'+chat['id']+'/messages',json={'text':'Compare published pay','request_token':'bad-local-'+str(bad)}))
 assert t['status']=='failed' and db.list_entities(u,'assistant_message')==[old]

def test_area_handoff_and_legacy_default(client,account):
 national=explicit_context.occupation_reference(CODE);assert 'salary_area' not in national
 local=explicit_context.occupation_reference(CODE,'metro:47900');assert local['revision']!=national['revision']
 result=explicit_context.resolve(account['id'],[local])[0]['snapshot'];assert result['salary']['area']['id']=='metro:47900'
 assert explicit_context.resolve(account['id'],[national])[0]['snapshot']['salary']['area']['id']=='US'
 assert client.get('/api/career-explorer/occupations/'+CODE+'?salary_area=metro:47900').json()['context_ref']==local


def test_lookup_cap_cancellation_and_revocation(client,account,monkeypatch):
 u=account['id'];credentials.save(u,'sk-fictional-not-real')
 async def too_many(*args,**kwargs):return {'answer':'Preparing','lookup_requests':[{'operation':'find_salary_areas','query':'VA'}]*7},{'model':'simulated'}
 monkeypatch.setattr(ai,'structured',too_many)
 t=wait(client,client.post('/api/knowledge-coach/chats/new/messages',json={'text':'Read local wages','request_token':'too-many-local'}));assert t['status']=='failed' and not db.list_entities(u,'assistant_message')
 started=[]
 async def slow(*args,**kwargs):
  started.append(True);await asyncio.sleep(3);return {'answer':'Should not be saved'}, {'model':'simulated'}
 monkeypatch.setattr(ai,'structured',slow)
 r=client.post('/api/knowledge-coach/chats/new/messages',json={'text':'Read local wages','request_token':'cancel-local-test'})
 for _ in range(50):
  if started:break
  time.sleep(.01)
 assert started
 client.post('/api/tasks/'+r.json()['task_id']+'/cancel',json={})
 t=wait(client,r);assert t['status']=='cancelled' and not db.list_entities(u,'assistant_message')
 # Sharing can change while a provider is preparing its answer.
 value=client.put('/api/profile/work-preferences',json={'summary':'I prefer focused preparation.','reviewed':True,'use_for_ai':True,'expected_revision':0});assert value.status_code==200
 from app import work_preferences
 async def revoke(schema,payload,*args,**kwargs):
  source=next(s for s in payload['source_catalog'] if s['kind']=='preference')
  db.save(u,'work_preferences',{**work_preferences.read(u),'revision':2,'use_for_ai':False},work_preferences.identity(u))
  return {'answer':'Previously shared preference','references':[{'source_id':source['source_id'],'quote':source['text']}]},{'model':'simulated'}
 monkeypatch.setattr(ai,'structured',revoke)
 t=wait(client,client.post('/api/knowledge-coach/chats/new/messages',json={'text':'Explain my work preference','request_token':'revocation-local'}));assert t['status']=='failed' and not db.list_entities(u,'assistant_message')

def test_salary_ambiguity_does_not_force_research(client,account,monkeypatch):
 u=account['id'];credentials.save(u,'sk-fictional-not-real')
 async def clarify(*args,**kwargs):return {'answer':'Does DE mean data engineering or Delaware?'},{'model':'simulated'}
 async def forbidden(*args,**kwargs):raise AssertionError('Ambiguity must not force web research')
 monkeypatch.setattr(ai,'structured',clarify);monkeypatch.setattr(career_coach,'research',forbidden)
 t=wait(client,client.post('/api/knowledge-coach/chats/new/messages',json={'text':'Current DE salary','request_token':'salary-clarification'}));assert t['status']=='completed',t


def test_derived_reference_chains_cannot_reintroduce_restricted_sources(client,account):
 u=account['id']
 private=db.save(u,'private_application_answer',{'answer':'PRIVATE'})
 upstream=db.save(u,'coach_plan',{'direction':'Restricted plan','source_snapshot':[{'kind':'profile','record_id':private['id'],'text':'PRIVATE'}]})
 downstream=db.save(u,'analysis',{'summary':'Indirect restricted output','source_snapshot':[{'record_id':upstream['id'],'kind':'coach_plan'}]})
 assert access.project(u,downstream) is None
 good=db.save(u,'experience',{'confirmed':True,'description':'SQL pipeline'})
 upstream=db.save(u,'analysis',{'summary':'Allowed generated output','source_snapshot':[{'record_id':good['id'],'kind':'profile'}]})
 downstream=db.save(u,'prep',{'summary':'Related saved plan','source_snapshot':[{'record_id':upstream['id'],'kind':'analysis'}]})
 assert access.project(u,downstream)
 assert downstream['id'] not in json.dumps(context.retrieve(u,'Related saved plan',excluded=[good['id']]))


def test_tracking_dates_survive_sensitive_text_scrubbing():
 assert context.clean('Interview 2026-11-01')=='Interview 2026-11-01'
 assert '2026-11-01' not in context.clean('Date of birth 2026-11-01')
 assert '555-123-4567' not in context.clean('Call 555-123-4567')
