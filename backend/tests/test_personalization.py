"""Fictional accounts only. These tests never call a provider or production storage."""
import asyncio,copy,json
import pytest
from fastapi import HTTPException
from app import db,personalization as sharing,profile_context as context,profile_answers,work_preferences,career_goals,career_coach,career_evidence,coach_access,assistant_context,interview_practice,ai,optimization,resume_builder

def save(client,enabled=True,revision=0):
 r=client.put('/api/profile/personalization',json={'enabled':enabled,'expected_revision':revision})
 assert r.status_code==200,r.text
 return r.json()

def graph(user):
 def record(category,title,**data):return db.save(user,'experience',{'category':category,'title':title,'confirmed':True,**data})
 degree=record('education','Fictional MS',organization='Example University',degree='MS',relevant_courses='Internship; Databases')
 first=record('employment','Summer intern',organization='Example Agency',linked_courses=[{'education_id':degree['id'],'course':'Internship'}])
 second=record('employment','Research contractor',organization='Example Research Center')
 project=record('project','Scenario Workbench',description='• Automated scenario setup.\n  Preserved original files.\n• Integrated output processing.',linked_employment_ids=[first['id'],second['id']],linked_education_ids=[degree['id']])
 detail=db.save(user,'profile_answer',{'version':1,'status':'confirmed','answer_kind':'experience','title':'Stakeholder improvements','text':'Used stakeholder feedback to improve scenario management.','experience_id':project['id'],'experience_ids':[project['id'],first['id']],'sources':[{'builder':'interview','attempt_id':'fictional-attempt','excerpts':['Used stakeholder feedback to improve scenario management.'],'questions':[]}]})
 return degree,first,second,project,detail

def preferences(user):
 db.save(user,'work_preferences',{'revision':3,'summary':'You may prefer clear goals and time to prepare.','preferences':[],'reviewed':True,'use_for_ai':False,'coach_report_access':True,'assessment_id':'private-assessment'},work_preferences.identity(user))
 db.save(user,'work_style',{'status':'completed','answers':{'a':'PRIVATE_RAW_RESPONSE'},'report':{'domains':[{'name':'PRIVATE_SCORE','mean':4.8}]}},'private-assessment')
 career_goals.save(user,career_goals.Change(text='Explore data engineering leadership',expected_revision=0,use_for_ai=False))

def test_central_choice_preserves_legacy_until_saved_and_never_rewrites_records(client,account):
 u=account['id'];preferences(u);old=copy.deepcopy(db.list_entities(u,'work_preferences'))
 assert client.get('/api/profile/personalization').json()=={'revision':0,'enabled':True,'explicit':False,'summary_shared':False,'goals_shared':False}
 assert not work_preferences.context(u)['preferences'] and not career_goals.context(u)['text']
 save(client)
 assert work_preferences.context(u)['preferences']==['You may prefer clear goals and time to prepare.']
 assert career_goals.context(u)['text']=='Explore data engineering leadership'
 assert db.list_entities(u,'work_preferences')==old
 assert client.put('/api/profile/personalization',json={'enabled':False,'expected_revision':0}).status_code==409
 save(client,False,1)
 assert not context.profile(u)['sources'] and not work_preferences.context(u)['preferences'] and not career_goals.context(u)['text']

def test_graph_and_bullets_reach_all_shared_consumers_without_duplicate_detail(client,account):
 u=account['id'];degree,first,second,project,detail=graph(u)
 p=context.profile(u,'scenario stakeholder',30000);wire=json.dumps(p,ensure_ascii=False)
 assert 'Summer intern' in wire and 'Research contractor' in wire and 'Fictional MS' in wire
 assert any('• Automated scenario setup.\n  Preserved original files.' in s['text'] for s in p['sources'])
 facts=[s for s in p['sources'] if s['field']=='answer']
 assert len(facts)==1 and facts[0]['record_id']==detail['id'] and facts[0]['experience_ids']==[project['id'],first['id']]
 assert facts[0]['provenance'][0]['attempt_id']=='fictional-attempt'
 for module in (career_coach,__import__('app.job_ai',fromlist=['profile'])):
  assert any(s['field']=='context' for s in module.profile(u)['sources'])
 assert any(s.get('relationships') for s in career_evidence.sources(u) if s['record_id']==project['id'])
 assert any('Research contractor' in s['text'] for s in assistant_context.sources(u) if s['kind']=='reviewed_profile')
 rows=context.records(u);linked=next(r for r in rows if r['id']==degree['id'])['data']['relationship_context']
 assert any(r.get('course')=='Internship' and r['id']==first['id'] for r in linked)

def test_only_links_changed_invalidates_revision_and_resume_fingerprint(client,account):
 u=account['id'];degree,first,second,project,_=graph(u);before=context.profile(u)['revision']
 raw=copy.deepcopy(project['data']);raw['linked_employment_ids']=[first['id']];db.save(u,'experience',raw,project['id'])
 assert context.profile(u)['revision']!=before
 entry={'source_id':project['id'],'title':'Scenario Workbench','details':'','bullets':['Automated scenario setup.'],'content_items':[{'item_id':'b','original':'Automated scenario setup.'}],'relationship_context':[{'id':first['id']}]}
 snapshot={'sections':[{'entries':[entry]}]};old=optimization.fingerprint(snapshot)
 entry['relationship_context'].append({'id':second['id']});assert optimization.fingerprint(snapshot)!=old

def test_long_profiles_select_relevant_tail_and_count_serialized_budget(client,account):
 u=account['id']
 for n in range(15):db.save(u,'experience',{'category':'project','title':f'Unrelated pottery {n}','description':('Prepared ceramic glazing. '*100),'confirmed':True})
 rare=db.save(u,'experience',{'category':'project','title':'Telemetry validation','description':('Prepared logs. '*900)+' Investigated zirconium telemetry drift.','confirmed':True})
 p=context.profile(u,'zirconium telemetry',7000)
 assert any('zirconium telemetry drift' in s['text'] for s in p['sources'])
 assert any(s['record_id']==rare['id'] and s['field']=='context' for s in p['sources'])
 assert p['context_characters']<=7000 and p['context_limited']

def test_raw_assessments_and_reports_never_reach_ordinary_context_even_legacy_shared(client,account):
 u=account['id'];preferences(u);save(client)
 assert work_preferences.coach_context(u) is None
 assert work_preferences.resume_context(u)['preferences']
 payload=json.dumps(list(assistant_context.sources(u)))
 assert 'You may prefer clear goals' in payload and 'PRIVATE_RAW_RESPONSE' not in payload and 'PRIVATE_SCORE' not in payload
 assert not coach_access.source_allowed(u,{'kind':'work_style_report','record_id':'private-assessment'})
 assert not coach_access.source_allowed(u,{'assessment_report':{'domains':[{'mean':4.8}]}})

def test_interview_uses_central_summary_without_session_prompt_but_coding_omits_it(client,account):
 from test_interview_practice import create
 u=account['id'];preferences(u);graph(u);save(client)
 session=create(client,kind='behavioral');before=copy.deepcopy(session)
 _,catalog=interview_practice.context(u,session,'stakeholder scenario')
 assert any(s['kind']=='work_summary' for s in catalog) and session==before
 code=create(client,kind='coding');_,catalog=interview_practice.context(u,code,'scenario')
 assert not any(s['kind']=='work_summary' for s in catalog)

def test_unlinked_orphaned_and_foreign_records_excluded(client,account):
 u=account['id'];_,_,_,project,_=graph(u)
 db.save(u,'profile_answer',{'version':1,'status':'confirmed','answer_kind':'experience','title':'Unlinked','text':'UNLINKED_SENTINEL','experience_id':'','experience_ids':[],'sources':[]})
 job=db.save(u,'experience',{'category':'employment','title':'Temporary destination','confirmed':True})
 orphan=db.save(u,'experience',{'category':'project','title':'ORPHAN_SENTINEL','confirmed':True,'linked_employment_ids':[job['id']]})
 db.delete(u,job['id'])
 other=client.post('/api/auth/register',json={'username':'foreign-owner','password':'fictional-test-password'}).json()
 db.save(other['id'],'experience',{'category':'project','title':'FOREIGN_SENTINEL','confirmed':True})
 for value in (context.profile(u),career_evidence.sources(u),list(coach_access.records(u))):
  wire=json.dumps(value);assert all(v not in wire for v in ('UNLINKED_SENTINEL','ORPHAN_SENTINEL','FOREIGN_SENTINEL'))
 assert db.get(u,orphan['id'],'experience') and db.get(u,project['id'],'experience')

def test_revocation_during_provider_wait_detected_with_saved_drafts_unchanged(client,account):
 u=account['id'];graph(u);save(client);version=sharing.request_version(u)
 saved=db.save(u,'resume_revision',{'snapshot':{'text':'HISTORICAL_RESUME'}})
 save(client,False,1)
 with pytest.raises(HTTPException) as e:sharing.check_request(u,version)
 assert e.value.status_code==409 and db.get(u,saved['id'],'resume_revision')==saved
 assert not any(s['kind']=='reviewed_profile' for s in assistant_context.sources(u))

def test_backup_restores_links_but_does_not_enable_sharing_or_cross_accounts(client,account):
 u=account['id'];graph(u);preferences(u);save(client)
 backup=client.get('/api/account/export').json()
 assert any(r['kind']==sharing.KIND for r in backup['records'])
 other=client.post('/api/auth/register',json={'username':'restore-context','password':'fictional-test-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
 backup['records']=[r for r in backup['records'] if r['kind'] not in ('profile_answer','work_style','work_preferences')]
 restored=client.post('/api/account/import',files={'file':('context.json',json.dumps(backup).encode(),'application/json')})
 assert restored.status_code==200,restored.text
 assert sharing.read(other['id'])=={'revision':1,'enabled':False,'explicit':True}
 assert sharing.read(u)['enabled'] is True
 project=next(r for r in profile_answers.records(other['id']) if r['data']['category']=='project')
 assert len(project['data']['related_jobs'])==2
 assert all(db.get(other['id'],r['id'],'experience') for r in project['data']['related_jobs'])

def test_coach_field_source_ids_unique_and_stable_and_writing_scope_follows_central_choice(client,account):
 from app import knowledge_assistant as coach
 u=account['id'];graph(u);preferences(u)
 before=assistant_context.sources(u);assert len({s['source_id'] for s in before})==len(before)
 assert before==assistant_context.sources(u)
 if 'context_scope' not in coach.Action.model_fields:return # Local edition has no bundled writing-guide mode.
 action=coach.Action(text='Explain scenario project bullets',request_token='fictional-writing',context_scope='writing')
 assert coach.validate_context(u,'new',action)==[] # Legacy guide opt-out remains.
 save(client)
 rows=coach.validate_context(u,'new',action)
 assert any(s['kind']=='reviewed_profile' for s in rows)
 assert any(s['kind']=='preference' for s in rows)
 assert any(s['kind']=='aspiration' for s in rows)
 save(client,False,1)
 assert coach.validate_context(u,'new',action)==[]

def test_simulated_skills_and_legacy_interview_payloads_share_current_graph_without_private_data(client,account,monkeypatch):
 u=account['id'];graph(u);preferences(u);save(client);calls=[]
 async def model(schema,payload,*a,**k):
  calls.append(payload)
  if schema==ai.PrepOutput:return {'priorities':[],'steps':[],'resource_ids':[],'questions':[]},{'model':'simulated'}
  return {'summary':'Fictional feedback','strengths':[],'improvements':[],'follow_up':'What happened?','evidence':[]},{'model':'simulated'}
 monkeypatch.setattr(ai,'structured',model)
 asyncio.run(ai.prepare(u,{},['Python'],'economy'))
 asyncio.run(ai.interview(u,{},'Describe the scenario project','I improved the workflow.','economy'))
 for payload in calls:
  wire=json.dumps(payload)
  assert 'Scenario Workbench' in wire and 'Research contractor' in wire
  assert 'PRIVATE_RAW_RESPONSE' not in wire and 'PRIVATE_SCORE' not in wire


def test_personalization_available_before_education_setup(client):
 user=client.post('/api/auth/register',json={'username':'no-setup','password':'fictional-no-setup-password'}).json()
 client.headers['X-CSRF-Token']=user['csrf']
 assert client.get('/api/profile/personalization').status_code==200
 assert client.put('/api/profile/personalization',json={'enabled':False,'expected_revision':0}).status_code==200


def test_application_drafts_respect_legacy_goals_and_central_permission(client,account):
 from app import assistant_ai
 u=account['id'];preferences(u)
 run={'unresolved':[{'id':'q','label':'Why do you want this job?','control':'textarea','private':False,'options':[]}]}
 body=assistant_ai.Assistance(request_token='x'*32,question_id='q',action='draft_short_answer',approved_cost_usd=.01,consent=True)
 with pytest.raises(HTTPException) as error:assistant_ai.build_payload(u,run,body)
 assert error.value.status_code==422
 save(client)
 assert assistant_ai.build_payload(u,run,body)['career_goals_as_aspirations']['text']=='Explore data engineering leadership'
 save(client,False,1)
 with pytest.raises(HTTPException):assistant_ai.build_payload(u,run,body.model_copy(update={'use_career_goals':True}))
 assert 'career_goals_as_aspirations' not in assistant_ai.build_payload(u,run,body.model_copy(update={'action':'interpret'}))


def test_application_help_discards_result_after_permission_change(client,account,monkeypatch):
 from app import assistant_ai
 from test_application_agent import run,scan,field
 u=account['id'];save(client);r,c,_=run(client,u);r=scan(client,r,c,[field(label='Why this role?')]).json()['run']
 token='v'*32;payload={'action':'interpret','question_id':'f0'};version=sharing.request_version(u)
 with db.connect() as conn:conn.execute('INSERT INTO cc_ai_requests VALUES(?,?,?,?,?,?,?,?,?,?)',(token,u,r['id'],'fictional-hash','dispatching',.01,None,db.now()[:10],'{}',db.now()))
 async def model(*a,**k):
  sharing.put(sharing.Change(enabled=False,expected_revision=1),{'id':u})
  return {'usage':{'input_tokens':100,'output_tokens':50},'output':[{'content':[{'type':'output_text','text':json.dumps({'explanation':'Fictional interpretation','excerpts':[]})}]}]}
 monkeypatch.setattr(ai,'call_api',model)
 asyncio.run(assistant_ai.dispatch(u,token,r['id'],payload,{},version))
 with db.connect() as conn:row=conn.execute('SELECT * FROM cc_ai_requests WHERE id=?',(token,)).fetchone()
 value=assistant_ai.public(row)
 assert value['state']=='rejected' and value['result'] is None and 'personalization changed' in value['error']
 assert row['actual'] is not None
