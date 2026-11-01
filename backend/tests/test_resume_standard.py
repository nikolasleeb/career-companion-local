"""Fictional provider tests: bounded two/four-call pipeline and durable recovery."""
import asyncio,copy,json,time
import httpx,pytest
from app import ai,db,resume_conversation as guided,resume_runs as runs,task_atomic,job_parser
from app.models import ExperienceItem,ConversationStart,GuidedBuild
from resume_strategy_fixtures import composition,strategy as fake_strategy

@pytest.fixture
def setup(client,account,monkeypatch):
 user=account['id'];pair={r:{'model':'gpt-6.1-sol','reasoning_effort':'medium','speed':'standard'} for r in ('writer','reviewer')};db.update_settings(user,{'document_models':pair})
 db.save(user,'experience',ExperienceItem(category='project',title='Fictional analytical project',description='Built a Python data cleaning prototype. Documented checks for collaborators.',confirmed=True).model_dump())
 job=db.save(user,'job',{'title':'Analyst','company':'Fictional Co','description':'Required qualifications\nA relevant degree.\nPreferred qualifications\nPython and SQL.\nResponsibilities\nAnalyze data and explain checks.'})
 analysis=db.save(user,'analysis',{'job_id':job['id'],'schema_version':3,'posting_hash':job_parser.posting_hash(job['data']),'requirements':[],'keywords':[],'duty_assessments':[]})
 session=guided.start(user,ConversationStart(job_id=job['id'],analysis_id=analysis['id']))
 calls=[];behavior={'material':False,'cosmetic':False,'factual':False,'timeout_review':False};pending=[]
 class FakeClient:
  def __init__(self,*a,**k):pass
  async def __aenter__(self):return self
  async def __aexit__(self,*a):pass
  async def post(self,url,headers,json):
   body=json;payload=__import__('json').loads(body['input']);name=body['text']['format']['name'];calls.append((name,copy.deepcopy(payload)))
   if name=='ResumeStrategy':value=fake_strategy(payload)
   elif name=='ResumeQualityReview':
    if behavior['timeout_review']:raise httpx.ReadTimeout('Fictional Thorough disconnect')
    value={'strengths':['Clear supported evidence.'],'findings':[],'next_actions':[]}
   elif name=='DraftAudit':value={'approved':True,'issues':[],'coverage':[{'priority_id':p['id'],'demonstrated':p['included'],'explanation':'Confirmed final evidence.'} for p in payload.get('final_coverage',[])]}
   elif name=='OptimizationOutput':value=payload['proposal']
   elif name=='ResumeComposition':
    if 'previous_composition' in payload:value=copy.deepcopy(payload['previous_composition'])
    else:value=composition(payload)
   else:
    if behavior['timeout_review']:raise httpx.ReadTimeout('Fictional disconnect')
    first=sum(c[0]=='ResumeCombinedReview' for c in calls)==1
    material=behavior['material'] and first
    quote=payload['resume']['text'].splitlines()[0]
    value={'audit':{'approved':not behavior['factual'],'issues':['Unsupported claim.'] if behavior['factual'] else [],'coverage':[{'priority_id':p['id'],'demonstrated':p['included'],'explanation':'Confirmed exact document evidence.'} for p in payload['final_coverage']]},'quality':{'strengths':['Clear contributions.'],'findings':[{'kind':'writing','material':material,'issue':'Clarify the contribution.' if material else 'Minor wording preference.','resume_quote':quote,'posting_quote':'','action':'Keep concise.'}] if material or behavior['cosmetic'] else [],'next_actions':[]},'affected_record_ids':[payload['professional_evidence']['records'][-1]['record_id']] if material or behavior['factual'] else [],'headline_change':False}
   response={'id':'fictional-'+str(len(calls)),'model':body['model'],'status':'completed','output':[{'content':[{'type':'output_text','text':__import__('json').dumps(value)}]}],'usage':{'input_tokens':100,'output_tokens':50,'total_tokens':150}}
   return httpx.Response(200,json=response)
 monkeypatch.setattr(ai.httpx,'AsyncClient',FakeClient)
 def build(**kwargs):
  nonlocal session
  session=guided.state(user,session['id']);guided.persist_skips(user,session['id'],session['data']['version']);session=guided.state(user,session['id']);stamp=db.now();task=db.uid()
  with db.connect() as c:c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',(task,user,'resume_guided','running','{}',None,stamp,stamp))
  context=ai.set_user_context(user,task,'resume_guided','build');ai._context.get()['key']='fictional-test-no-network';atomic=task_atomic.bind(user,task)
  body=GuidedBuild(expected_version=session['data']['version'],skip_questions=True,**kwargs)
  try:
   result=asyncio.run(guided.build(user,session['id'],body.expected_version,body.mode,body.decisions,body.template,feedback={'refresh_linked_evidence':True} if body.refresh_linked_evidence else None,preparation=body.preparation,skip_questions=True,run_body=body))
  finally:task_atomic.reset(atomic);ai.reset_user_context(context)
  with db.connect() as c:
   task_atomic.publish(c,user,task);c.execute("UPDATE tasks SET status='completed' WHERE id=?",(task,))
  session=guided.state(user,session['id']);return session
 return user,session,behavior,calls,build

@pytest.mark.parametrize('cosmetic',[False,True])
def test_standard_passes_in_two_requests_no_cosmetic_rewrite(setup,cosmetic):
 user,session,behavior,calls,build=setup;behavior['cosmetic']=cosmetic;state=build()
 assert len(calls)==2 and [n for n,p in calls]==['ResumeComposition','ResumeCombinedReview']
 assert state['current'] and state['current']['data']['snapshot']['optimization']['source_checked']
 run=state['optimization_run'];assert run['status']=='completed' and run['requests_used']==2
 assert runs.read(user,run['id'])['data']['preview']
 reviewer=calls[1][1];assert not any(k in reviewer for k in ('messages','user_messages','strategy','previous_composition','independent_feedback'))
 known={f['id'] for f in reviewer['professional_evidence']['facts']}
 assert all(ref in known for s in reviewer['rendered_attribution']['sections'] for e in s['entries'] for i in e['items'] for ref in i['source_ids'])
 assert all('text' not in detail for f in reviewer['professional_evidence']['facts'] for detail in f.get('supporting_details',[]))

def test_material_findings_allow_one_correction_and_final_review(setup):
 user,session,behavior,calls,build=setup;behavior['material']=True;state=build()
 assert [n for n,p in calls]==['ResumeComposition','ResumeCombinedReview','ResumeComposition','ResumeCombinedReview']
 assert state['optimization_run']['requests_used']==4 and state['current']
 assert 'material_feedback' not in calls[-1][1]

def test_rejected_facts_never_become_a_final_revision(setup):
 user,session,behavior,calls,build=setup;behavior['factual']=True;state=build()
 assert len(calls)==4 and not state['current']
 assert state['optimization_run']['status']=='needs_changes'
 assert state['optimization_run']['preview_id'] and not db.list_entities(user,'resume_revision')

def test_disconnect_preserves_first_draft_and_known_writer_response(setup):
 user,session,behavior,calls,build=setup;behavior['timeout_review']=True;state=build()
 assert not state['current'] and state['optimization_run']['preview_id']
 assert state['optimization_run']['status']=='unknown' and len(calls)==2
 assert all(q['status'] in ('skipped','superseded','answered','reviewed') for q in state['data'].get('asked_questions',[]))
 behavior['timeout_review']=False
 state=build(continue_run_id=state['optimization_run']['id'],acknowledge_unknown_usage=True)
 assert state['current'] and len(calls)==3 # known Writer replays locally
 assert state['optimization_run']['requests_used']==3

def test_legacy_pair_save_keeps_thorough_mode(client,account):
 pair={r:{'model':'gpt-6.1-sol','reasoning_effort':'medium','speed':'standard'} for r in ('writer','reviewer')}
 assert client.put('/api/document-models',json={**pair,'resume_review_mode':'thorough'}).status_code==200
 assert client.put('/api/document-models',json=pair).json()['resume_review_mode']=='thorough'
 before=db.settings(account['id'])
 assert client.put('/api/document-models',json={**pair,'resume_review_mode':'unknown'}).status_code==422
 assert db.settings(account['id'])==before

def test_original_custom_preparation_survives_pause_projection_and_replay(setup):
 from app.models import ResumeRequest
 user,session,behavior,calls,build=setup
 prep=ResumeRequest(job_id=session['data']['job_id'],analysis_id=session['data']['analysis_id'],experience_ids=[],content={},template='experience',headline='Analytical Projects')
 behavior['timeout_review']=True;state=build(preparation=prep,template='experience')
 saved=state['optimization_run'];assert saved['continue_inputs']['preparation']['headline']=='Analytical Projects'
 assert saved['continue_inputs']['template']=='experience'
 behavior['timeout_review']=False
 state=build(**saved['continue_inputs'],continue_run_id=saved['id'],acknowledge_unknown_usage=True)
 assert len(calls)==3 and state['current']['data']['snapshot']['headline']=='Analytical Projects'
 assert state['current']['data']['snapshot']['template']=='experience'

def test_selected_certification_survives_local_overflow_fit(setup,monkeypatch):
 from app import resume_strategy as strategy,resume_layout
 user,session,behavior,calls,build=setup;fits=[];original=resume_layout.fit
 def fitted(*args,**kwargs):fits.append(True);return original(*args,**kwargs)
 monkeypatch.setattr(resume_layout,'fit',fitted)
 cert=db.save(user,'experience',ExperienceItem(category='skills',title='Certifications',certification_items=[{'name':'Fictional Data Credential','issuer':'Example Institute'}],confirmed=True).model_dump())
 for n in range(18):
  db.save(user,'experience',ExperienceItem(category='project',title='Fictional additional study '+chr(65+n),description='Designed an analytical workflow for stakeholders and documented the data preparation choices. '+('Compared source records carefully and explained the methodology to collaborators. '*9),confirmed=True).model_dump())
 state=build();assert state['current']
 snapshot=state['current']['data']['snapshot'];assert snapshot['layout']['pages']==1
 selected=strategy.entries(snapshot)
 assert cert['id'] in selected and any(i['field']=='certification' and 'Fictional Data Credential' in i['text'] for i in selected[cert['id']]['content_items'])
 assert fits, 'Fixture must exercise actual local overflow fitting'

def test_thorough_uses_same_durable_response_and_preview_recovery(setup):
 user,session,behavior,calls,build=setup;behavior['timeout_review']=True
 state=build(optimization_mode='thorough');saved=state['optimization_run']
 assert saved['status']=='unknown' and saved['preview_id'] and not state['current']
 assert [s['status'] for s in runs.read(user,saved['id'])['data']['stages'][:2]]==['validated','validated']
 initial=len(calls);behavior['timeout_review']=False
 state=build(optimization_mode='thorough',continue_run_id=saved['id'],acknowledge_unknown_usage=True)
 assert state['current'] and state['optimization_run']['requests_used']<=8
 assert sum(name=='ResumeStrategy' for name,payload in calls)==1
 assert len(calls)>initial and state['optimization_run']['status']=='completed'

def test_authenticated_bulk_skip_recovers_same_start_token_without_second_run(setup,client):
 from test_applications_workflow import wait_task
 user,session,behavior,calls,build=setup
 client.put('/api/settings/openai-key',json={'api_key':'sk-fictional-skip-api-never-sent-1234567890'})
 path='/api/resume-conversations/'+session['id']+'/build'
 body={'expected_version':session['data']['version'],'skip_questions':True,'request_token':'fictional-bulk-skip-start'}
 first=client.post(path,json=body);duplicate=client.post(path,json=body)
 assert first.status_code==200 and duplicate.status_code==200
 assert first.json()['task_id']==duplicate.json()['task_id']
 task=wait_task(client,first);assert task['status']=='completed',task
 assert len(calls)==2 and guided.state(user,session['id'])['current']
 after=client.post(path,json=body);assert after.json()['task_id']==first.json()['task_id'] and len(calls)==2
