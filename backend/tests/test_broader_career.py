import asyncio,base64,copy,io,json,time
import pytest
from PIL import Image
from app import db,ai,credentials,career_goals,work_preferences,assistant_context,knowledge_assistant as coach,personalized_jobs as jobs,chat_visuals,skills,career_coach,work_style_neo as neo,work_style
from app.network import ServiceError

def wait(client,response):
 assert response.status_code==200,response.text
 for _ in range(1000):
  r=client.get('/api/tasks/'+response.json()['task_id']).json()
  if r['status'] not in ('queued','running','cancelling'):return r
  time.sleep(.005)
 raise AssertionError('Mocked task timed out')
def turn(client,id,text='Explain my reviewed education',**kw):return client.post('/api/knowledge-coach/chats/'+id+'/messages',json={'text':text,'request_token':'mock-'+db.uid(),**kw})
@pytest.fixture
def key(account):credentials.save(account['id'],'sk-fictional-career-not-real');return account['id']

def test_goals_cards_legacy_revision_and_backup(client,account):
 assert client.put('/api/profile/career-goals',json={'text':'Explore laboratory research','expected_revision':0}).status_code==200
 goal={'id':'cert-target','category':'certification','text':'Explore a laboratory certification','target':'End of 2027','priority':'high','progress':'planned'}
 r=client.put('/api/profile/career-goals',json={'text':'Long-term science work','items':[goal],'expected_revision':1});assert r.status_code==200,r.text
 assert r.json()['items'][1:]==[goal] and r.json()['items'][0]['category']=='general_statement' and 'aspirations' not in r.json()['note'] and 'certification' in r.json()['text']
 assert client.put('/api/profile/career-goals',json={'text':'Stale edit','items':[],'expected_revision':1}).status_code==409
 backup=client.get('/api/account/export').json();assert next(x for x in backup['records'] if x['kind']=='career_goals')['data']['items'][1:]==[goal]
 # Existing goals are not overwritten by an additive restore.
 assert client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')}).status_code==200
 assert client.get('/api/profile/career-goals').json()['items'][1:]==[goal]

def test_work_preference_consent_revocation_and_private_answers(client,account):
 u=account['id'];assert work_preferences.context(u)['preferences']==[]
 bad=client.put('/api/profile/work-preferences',json={'preferences':['Uninterrupted focus'],'use_for_ai':True,'reviewed':False,'expected_revision':0});assert bad.status_code==422
 r=client.put('/api/profile/work-preferences',json={'preferences':['Uninterrupted focus'],'use_for_ai':True,'reviewed':True,'expected_revision':0});assert r.status_code==200,r.text
 assert work_preferences.context(u)['preferences']==['Uninterrupted focus']
 db.save(u,'work_style',{'status':'completed','answers':{'political':'SECRET_POLITICS'},'report':{'domains':[{'private':'SECRET_DOMAIN'}],'preferences':[{'selected':'I prefer written project updates.'}]}})
 assert 'SECRET' not in json.dumps(client.get('/api/profile/work-preferences').json())
 assert client.put('/api/profile/work-preferences',json={'preferences':['Uninterrupted focus'],'use_for_ai':False,'reviewed':True,'expected_revision':1}).status_code==200
 assert not work_preferences.context(u)['preferences']

def test_versioned_work_measure_keeps_legacy_reports():
 old=neo.catalog_for(neo.LEGACY_VERSION);new=neo.catalog()
 assert old['items']==new['items'] and old['facets']==new['facets'] and old['version']!=new['version']
 answers={x['id']:3 for x in old['items']};a=neo.score(answers,{'p1':'left'},old);b=neo.score(answers,{'p1':'left'},new)
 assert a['domains'][0]['total']==b['domains'][0]['total'] and a['version']!=b['version']
 work_style.validate_backup({'catalog_version':neo.LEGACY_VERSION,'catalog':old,'version':2,'answers':answers,'comparison_answers':{'p1':'left'},'status':'completed','scores':a['domains'],'report':a,'page':0})

def test_private_fts_retrieval_excludes_raw_drafts_and_honors_sources(client,account):
 u=account['id'];good=db.save(u,'experience',{'category':'project','title':'Laboratory research notebook','description':'Documented sample preparation and microscope observations.','confirmed':True})
 db.save(u,'experience',{'title':'SECRET_DRAFT','confirmed':False});db.save(u,'work_style',{'answers':'SECRET_ANSWERS'});db.save(u,'profile_answer',{'answer_kind':'eligibility','answer':'SECRET_PRIVATE','confirmed':True})
 app=db.save(u,'application',{'title':'Research assistant','company':'Example Lab','status':'interviewing','private_answers':'SECRET_DISCLOSURE'})
 out=assistant_context.retrieve(u,'laboratory observations',pinned=[app['id']]);text=json.dumps(out)
 assert good['id'] in text and app['id'] in text and 'SECRET' not in text
 assert not any(s['record_id']==app['id'] for s in assistant_context.retrieve(u,'research',excluded=[app['id']]))
 with pytest.raises(Exception):assistant_context.retrieve(u,'research',pinned=['another-account-record'])
 db.delete(u,good['id']);assert good['id'] not in json.dumps(assistant_context.retrieve(u,'laboratory observations'))

def test_readonly_coach_sources_dedupe_history_and_no_profile_mutation(client,account,key,monkeypatch):
 before=copy.deepcopy(db.list_entities(key,'experience'));calls=[]
 async def model(schema,payload,mode='economy',**kw):
  calls.append(payload);s=payload['source_catalog'][0]
  return {'answer':'This saved education is a useful starting point. I cannot edit your Profile.','references':[{'source_id':s['source_id'],'quote':s['text'][:60]}],'needs_research':False,'research_topics':[],'visuals':[]},{'model':'fictional','usage':{}}
 monkeypatch.setattr(ai,'structured',model)
 body={'text':'Explain my reviewed education and change my Profile','request_token':'same-mock-token'}
 first=client.post('/api/knowledge-coach/chats/new/messages',json=body);r=wait(client,first);assert r['status']=='completed',r
 again=client.post('/api/knowledge-coach/chats/new/messages',json=body);assert again.json()['task_id']==first.json()['task_id'];assert len(calls)==1
 id=r['result']['chat']['id'];assert len(client.get('/api/knowledge-coach/chats/'+id).json()['messages'])==2
 assert db.list_entities(key,'experience')==before
 assert client.get('/api/ai-actions/same-mock-token').json()['task_id']==first.json()['task_id']
 assert client.patch('/api/knowledge-coach/chats/'+id,json={'title':'Education discussion'}).status_code==200
 backup=client.get('/api/account/export').json();assert client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')}).status_code==200
 assert len(db.list_entities(key,'assistant_chat'))==2


def test_bad_coach_citation_discards_new_chat(client,account,key,monkeypatch):
 async def model(*a,**kw):return {'answer':'Unsupported','references':[{'source_id':'invented','quote':'Not in sources'}],'needs_research':False,'research_topics':[],'visuals':[]},{'model':'mock'}
 monkeypatch.setattr(ai,'structured',model)
 r=wait(client,turn(client,'new'));assert r['status']=='failed' and not db.list_entities(key,'assistant_chat')

def test_current_coach_research_three_call_bound(client,account,key,monkeypatch):
 calls=[]
 async def model(schema,payload,*a,**kw):
  calls.append('model');web=next((s for s in payload['source_catalog'] if s['kind']=='web'),None)
  return {'answer':'Check the organizer source for the current schedule.' if web else 'Research needed','references':[{'source_id':web['source_id'],'quote':web['text']}] if web else [],'needs_research':not bool(web),'research_topics':['Example Conference'],'visuals':[]},{'model':'mock'}
 async def research(user,chat,p,token,mode,**kw):
  calls.append('research');assert all('Test setup education' not in x for x in kw['public_topics'])
  return db.save(user,'assistant_research',{'chat_id':chat['id'],'chunks':[{'chunk_id':'official','source_id':'web-source','title':'Example Conference official event','url':'https://example.org/conference','text':'The event provides workshops and a published schedule.','topics':['conference'],'checked_at':db.now(),'kind':'fetched','catalog_version':'test'}],'status':'checked','checked_at':db.now(),'warnings':[]})
 monkeypatch.setattr(ai,'structured',model);monkeypatch.setattr(career_coach,'research',research)
 r=wait(client,turn(client,'new','What is the latest schedule for Example Conference?'));assert r['status']=='completed',r
 assert calls==['model','research','model'] and r['result']['messages'][-1]['data']['research_used']


def test_skills_across_disciplines_and_no_eligibility_topics(client,account):
 u=account['id'];job=db.save(u,'job',{'title':'Clinical research assistant','description':'Clinical research and statistics. COVID-19 vaccination required. Eligible without visa sponsorship. Bachelor degree required.'})
 db.save(u,'analysis',{'job_id':job['id'],'requirements':[{'keyword':'COVID-19 vaccination'},{'keyword':'Visa sponsorship'},{'keyword':'Statistics'}]})
 r=client.get('/api/skills/options?job_id='+job['id']);assert r.status_code==200
 d=r.json();assert 'statistics' in [v.lower() for v in d['suggestions']] and not any(skills.BLOCK.search(v) for v in d['suggestions'])
 assert set(skills.FIELDS)<=set(v['field'] for v in d['resources'])
 assert not skills.learnable('Eligible to work without visa sponsorship')


def test_skill_plan_does_not_require_job(client,account,key,monkeypatch):
 async def prepare(user,job,gaps,mode):return {'priorities':['Practice writing a research protocol'],'resource_ids':[],'questions':[],'confirmed_gaps':gaps,'ai':{}}
 monkeypatch.setattr(ai,'prepare',prepare)
 r=wait(client,client.post('/api/preparation',json={'job_id':None,'confirmed_gaps':['research methods']}));assert r['status']=='completed',r
 assert r['result']['data']['job_id'] is None


def test_personalized_search_limit_evidence_and_normal_preferences(client,account,key,monkeypatch):
 from app import job_search,job_alerts
 before=copy.deepcopy(job_alerts.preferences(key));source=career_coach.profile(key)['sources'][0];records=[db.save(key,'job',{'title':'Research assistant '+str(i),'company':'Example Lab','description':'Research documentation and careful observation.','location':'Boston, MA','url':'https://example.org/jobs/'+str(i),'hard_filter_status':'matches'}) for i in range(65)];calls=[];verified=[]
 from app import job_results
 job_results.save_search(key,{'jobs':[{**r,'data':{**r['data'],'_last_verified_epoch':time.time()}} for r in records],'sources':[],'query':{},'ai_calls':[]})
 async def discover(user,request):assert 'web' not in request.sources;return {'jobs':records,'sources':[],'query':request.model_dump(),'ai_calls':[]}
 async def web(*a,**kw):calls.extend(['web','extract']);assert kw['retry_allowed'] is False;return [],[{'model':'mock'},{'model':'mock'}]
 async def verify(row,req):verified.append(row['id']);return row if len(verified)<=7 else None
 async def model(schema,payload,*a,**kw):
  calls.append(schema.__name__);assert kw['retry_allowed'] is False
  if schema==jobs.Criteria:return {'roles':['Research assistant'],'explanation':'Explore a related professional direction.'},{'model':'mock'}
  if schema==jobs.Screen:assert len(payload['jobs'])==50;return {'job_ids':[r['id'] for r in records[:10]]},{'model':'mock'}
  return {'jobs':[{'job_id':r['id'],'summary':'Reviewed education supports exploring this role.','evidence':[{'profile_source_id':source['id'],'profile_quote':source['text'],'posting_quote':'Research documentation'}],'goal_alignment':'Exploration','preference_alignment':'Not established','requirements_to_check':['Check requirements'],'suitable':True} for r in records[:5]]},{'model':'mock'}
 monkeypatch.setattr(job_search,'discover',discover);monkeypatch.setattr(ai,'web_jobs',web);monkeypatch.setattr(jobs,'verify',verify);monkeypatch.setattr(ai,'structured',model)
 body={'scope':'broad','request_token':'five-mock-token'};first=client.post('/api/job-search/for-you/discover',json=body);r=wait(client,first);assert r['status']=='completed',r
 assert r['result']['run']['data']['returned_count']==5 and len(calls)==5 and len(verified)==10
 again=client.post('/api/job-search/for-you/discover',json=body);assert again.json()['task_id']==first.json()['task_id'] and len(calls)==5
 assert job_alerts.preferences(key)==before
 assert client.post('/api/job-search/for-you/discover',json={'scope':'targeted','roles':[],'request_token':'no-target-token'}).status_code==422


def test_unverified_or_closed_jobs_do_not_fill_shortlist(client,account,monkeypatch):
 from app.models import SearchRequest
 async def fetch(*a,**k):return {'status':200,'content_type':'text/html','content':b'<html>This job is no longer available.</html>','url':a[0]}
 monkeypatch.setattr(jobs,'public_fetch',fetch)
 r={'id':'job','data':{'title':'Analyst','url':'https://example.org/job','description':'Detailed role','_last_verified_epoch':time.time()}}
 assert asyncio.run(jobs.verify(r,SearchRequest(title='analyst'))) is None


def test_visual_values_sources_and_safe_image_validation():
 source={'source_id':'s','text':'The example has 12 tasks.','url':'https://example.org/guide'}
 v={'kind':'bar','title':'Tasks','items':[{'label':'Tasks','value':12}],'source_ids':['s'],'illustrative':False}
 assert chat_visuals.validate([v],[source])[0]['items'][0]['value']==12
 with pytest.raises(ServiceError):chat_visuals.validate([{**v,'items':[{'label':'Invented','value':99}]}],[source])
 with pytest.raises(ServiceError):chat_visuals.validate([{**v,'source_ids':['private-other-account']}],[source])
 with pytest.raises(ServiceError):chat_visuals.validate([{'kind':'sourced_image','title':'Bad','url':'javascript:alert(1)'}],[source])
 out=io.BytesIO();Image.new('RGB',(1024,1024)).save(out,format='PNG');assert chat_visuals.checked_image(out.getvalue())
 with pytest.raises(ServiceError):chat_visuals.checked_image(b'not a png')


def test_interview_modes_and_followup_conversation(client,account,key,monkeypatch):
 from app import interview_practice as practice
 for kind in ('behavioral','star','coding','case','domain','presentation','other'):
  r=client.post('/api/interview-practice/sessions',json={'kind':kind});assert r.status_code==200,r.text
 s=r.json()
 async def model(schema,payload,*a,**kw):
  source=payload['source_catalog'][0];return {'answer':'Explain your reasoning and identify assumptions.','next_question':'What evidence would you check first?','references':[{'source_id':source['source_id'],'quote':source['text']}],'visuals':[]},{'model':'mock'}
 monkeypatch.setattr(ai,'structured',model)
 r=wait(client,client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json={'operation':'message','text':'How should I approach this type of interview?','expected_updated_at':s['updated_at'],'request_token':'domain-chat-mock'}));assert r['status']=='completed',r
 assert len(r['result']['messages'])==2 and r['result']['messages'][1]['data']['reply']['next_question']
 backup=client.get('/api/account/export').json();assert client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')}).status_code==200


def test_image_generation_private_costs_dedupe_and_backup(client,account,key,monkeypatch):
 parent=client.post('/api/knowledge-coach/chats',json={'title':'Visual learning'}).json()
 out=io.BytesIO();Image.new('RGB',(1024,1024),(40,90,120)).save(out,format='PNG');raw=out.getvalue();calls=[]
 class Response:
  status_code=200
  def json(self):return {'data':[{'b64_json':base64.b64encode(raw).decode()}],'usage':{'input_tokens':20,'output_tokens':100,'input_tokens_details':{'text_tokens':20,'image_tokens':0}}}
 class Provider:
  def __init__(self,*a,**k):pass
  async def __aenter__(self):return self
  async def __aexit__(self,*a):pass
  async def post(self,url,**kw):calls.append((url,kw['json']));return Response()
 monkeypatch.setattr(chat_visuals.httpx,'AsyncClient',Provider)
 body={'conversation_id':parent['id'],'conversation_kind':'assistant_chat','prompt':'A simple illustration of a research notebook.','request_token':'image-mock-token'}
 first=client.post('/api/chat-visuals/generate',json=body);r=wait(client,first);assert r['status']=='completed',r
 assert 'base64' not in r['result']['data'];image_id=r['result']['id'];assert client.get('/api/chat-visuals/images/'+image_id).content==raw
 assert calls[0][0].endswith('/images/generations') and calls[0][1]['n']==1 and calls[0][1]['model']==chat_visuals.IMAGE_MODEL
 assert client.post('/api/chat-visuals/generate',json=body).json()['task_id']==first.json()['task_id'] and len(calls)==1
 usage=db.list_entities(key,'usage_event')[0]['data'];assert usage['process']=='chat_image' and usage['estimated_cost_usd']==pytest.approx(.0031)
 backup=client.get('/api/account/export').json();assert client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')}).status_code==200
 assert len(db.list_entities(key,'chat_image'))==2
 original_cookie=dict(client.cookies);other=client.post('/api/auth/register',json={'username':'other-career','password':'fictional-test-password'}).json();from conftest import onboard_test_account
 onboard_test_account(other);client.headers['X-CSRF-Token']=other['csrf']
 assert client.get('/api/chat-visuals/images/'+image_id).status_code==404
 assert client.get('/api/knowledge-coach/chats/'+parent['id']).status_code==404
 assert client.get('/api/ai-actions/image-mock-token').status_code==404


def test_stop_coach_discards_staged_conversation_and_keeps_manual_state(client,account,key,monkeypatch):
 started=[]
 async def model(*a,**kw):started.append(True);await asyncio.sleep(20)
 monkeypatch.setattr(ai,'structured',model)
 r=turn(client,'new','Help me understand my career options')
 for _ in range(100):
  if started:break
  time.sleep(.01)
 assert started
 manual=db.save(key,'experience',{'category':'project','title':'Manual edit while waiting','confirmed':False})
 cancel=client.post('/api/tasks/'+r.json()['task_id']+'/cancel',json={});assert cancel.status_code==200
 for _ in range(100):
  t=client.get('/api/tasks/'+r.json()['task_id']).json()
  if t['status']=='cancelled':break
  time.sleep(.01)
 assert t['status']=='cancelled' and db.get(key,manual['id'],'experience') and not db.list_entities(key,'assistant_chat')


def test_fewer_than_five_when_no_finalist_is_current(client,account,key,monkeypatch):
 from app import job_search
 row=db.save(key,'job',{'title':'Research assistant','company':'Example','description':'A detailed research assistant opportunity.','location':'Boston, MA','url':'https://example.org/closed'})
 async def discover(*a,**kw):return {'jobs':[row],'query':{},'sources':[],'ai_calls':[]}
 async def model(schema,payload,*a,**kw):
  if schema==jobs.Criteria:return {'roles':['Research assistant'],'explanation':'Related direction'},{'model':'mock'}
  return {'job_ids':[row['id']]},{'model':'mock'}
 async def no_web(*a,**kw):return [],[]
 async def closed(*a,**kw):return None
 monkeypatch.setattr(job_search,'discover',discover);monkeypatch.setattr(ai,'structured',model);monkeypatch.setattr(ai,'web_jobs',no_web);monkeypatch.setattr(jobs,'verify',closed)
 r=wait(client,client.post('/api/job-search/for-you/discover',json={'request_token':'all-closed-token'}));assert r['status']=='completed',r
 assert r['result']['run']['data']['returned_count']==0 and not r['result']['search']['data']['jobs']


def test_stop_image_closes_provider_and_discards_asset(client,account,key,monkeypatch):
 parent=client.post('/api/knowledge-coach/chats',json={'title':'Stopped illustration'}).json();started=[];closed=[]
 class Provider:
  def __init__(self,*a,**k):pass
  async def __aenter__(self):return self
  async def __aexit__(self,*a):closed.append(True)
  async def post(self,*a,**k):started.append(True);await asyncio.sleep(20)
 monkeypatch.setattr(chat_visuals.httpx,'AsyncClient',Provider)
 response=client.post('/api/chat-visuals/generate',json={'conversation_id':parent['id'],'conversation_kind':'assistant_chat','prompt':'An illustration that will be stopped.','request_token':'cancel-image-mock'})
 for _ in range(100):
  if started:break
  time.sleep(.01)
 assert started
 assert client.delete('/api/knowledge-coach/chats/'+parent['id']).status_code==409
 client.post('/api/tasks/'+response.json()['task_id']+'/cancel',json={})
 for _ in range(100):
  result=client.get('/api/tasks/'+response.json()['task_id']).json()
  if result['status']=='cancelled':break
  time.sleep(.01)
 assert result['status']=='cancelled' and closed and not db.list_entities(key,'chat_image')
 assert db.get(key,parent['id'],'assistant_chat')
 usage=db.list_entities(key,'usage_event')[0]['data'];assert usage['estimated_cost_usd'] is None and usage['status']=='unknown'
