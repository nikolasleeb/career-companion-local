import asyncio,copy,json,time
import pytest
from app import db,career_goals,assistant_ai,career_coach as coach,ai,config,credentials
from test_career_coach import reply,wait

def test_goals_optional_revision_isolation_and_export(client,account):
 assert client.get('/api/profile/career-goals').json()['revision']==0
 r=client.put('/api/profile/career-goals',json={'text':'I want to explore public health and a future credential.','expected_revision':0});assert r.status_code==200
 assert r.json()['revision']==1
 assert client.put('/api/profile/career-goals',json={'text':'stale','expected_revision':0}).status_code==409
 assert coach.profile(account['id'])['sources'] # Aspirations never enter qualification evidence.
 assert 'future credential' not in json.dumps(coach.profile(account['id']))
 payload=client.get('/api/account/export').json();assert any(r['kind']=='career_goals' for r in payload['records'])
 other=client.post('/api/auth/register',json={'username':'other-goals','password':'fictional-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
 assert client.get('/api/profile/career-goals').json()['text']==''
 assert client.put('/api/profile/career-goals',json={'text':'Explore nursing','expected_revision':0}).status_code==200 # Accessible during education setup.
 assert client.get('/api/career-coach/chats').status_code==403

def test_aspiration_only_application_context_and_validation(client,account):
 career_goals.save(account['id'],career_goals.Change(text='Learn cloud engineering',expected_revision=0))
 run={'unresolved':[{'id':'q','label':'Why do you want this job?','description':'','context':'','options':[],'control':'textarea','private':False}]}
 body=assistant_ai.Assistance(request_token='x'*32,question_id='q',action='draft_short_answer',use_career_goals=True,approved_cost_usd=.01,consent=True)
 payload=assistant_ai.build_payload(account['id'],run,body);assert payload['career_goals_as_aspirations']['revision']==1
 result={'explanation':'Draft','excerpts':[],'sentences':[{'kind':'aspiration','text':'I am interested in this role because it aligns with my goal to learn cloud engineering.','source_id':'career_goals','quote':'Learn cloud engineering'}]}
 assert assistant_ai.validate(result,payload)['career_goals_revision']==1
 result['sentences'][0]['text']='I am certified in cloud engineering.'
 with pytest.raises(ValueError):assistant_ai.validate(result,payload)
 for label,control in [('Do you have a cloud certification?','textarea'),('Why are you eligible for sponsorship?','text'),('Why do you want this job?','select')]:
  changed=copy.deepcopy(run);changed['unresolved'][0].update(label=label,control=control)
  with pytest.raises(Exception):assistant_ai.build_payload(account['id'],changed,body)
 off=body.model_copy(update={'use_career_goals':False,'evidence_ids':[]})
 with pytest.raises(Exception):assistant_ai.build_payload(account['id'],run,off)
 plain=body.model_copy(update={'action':'interpret','use_career_goals':False})
 assert 'career_goals_as_aspirations' not in assistant_ai.build_payload(account['id'],run,plain)

def test_new_chat_is_published_only_on_success_and_goals_snapshot(client,account,monkeypatch):
 credentials.save(account['id'],'sk-fictional-goals');monkeypatch.setattr(config,'ENABLE_WEB_SEARCH',False)
 career_goals.save(account['id'],career_goals.Change(text='Explore data science',expected_revision=0))
 async def model(schema,payload,*a,**k):return reply(payload,recommendations=[]),{'model':'fictional'}
 monkeypatch.setattr(ai,'structured',model)
 task=client.post('/api/career-coach/chats/new/actions',json={'operation':'message','text':'Help me brainstorm','request_token':'new-question-only'}).json();result=wait(client,task);assert result['status']=='completed',result
 chats=client.get('/api/career-coach/chats').json()['chats'];assert len(chats)==1
 detail=client.get('/api/career-coach/chats/'+chats[0]['id']).json();assert not detail['plans']
 assert detail['chat']['data']['profile_goals_snapshot']['text']=='Explore data science'
 career_goals.save(account['id'],career_goals.Change(text='Explore nursing',expected_revision=1))
 assert client.get('/api/career-coach/chats/'+chats[0]['id']).json()['chat']['data']['profile_goals_snapshot']['text']=='Explore data science'


def test_conference_research_decision_and_bounded_requests(client,account,monkeypatch):
 credentials.save(account['id'],'sk-fictional-goals');monkeypatch.setattr(config,'ENABLE_WEB_SEARCH',True);models=[];web=[]
 async def model(schema,payload,*a,**k):
  models.append(payload)
  return reply(payload,recommendations=[],needs_fresh_research=len(models)==1,research_topics=['Fictional Research Summit']),{'model':'fictional'}
 async def search(body,**kwargs):
  web.append(body);return {'model':'fictional','output':[{'content':[{'annotations':[{'type':'url_citation','url':'https://conference.example.org/agenda'}]}]}]}
 async def fetch(url,*a):return {'url':url,'status':200,'content_type':'text/html','content':b'<main>The Fictional Research Summit agenda lists an opening talk and practical workshops for professional development. Check the official organizer for current registration details.</main>'}
 monkeypatch.setattr(ai,'structured',model);monkeypatch.setattr(ai,'call_api',search);monkeypatch.setattr(coach,'public_fetch',fetch)
 task=client.post('/api/career-coach/chats/new/actions',json={'operation':'message','text':'Help me prepare for Fictional Research Summit conference','request_token':'conference-request'}).json();value=wait(client,task)
 assert value['status']=='completed',value
 assert len(models)==2 and len(web)==1 and web[0]['max_tool_calls']==4
 assert 'Fictional Research Summit' in web[0]['input']
 assert value['result']['data']['research_used']
 assert not client.get('/api/career-coach/chats/'+value['result']['data']['chat_id']).json()['plans']

def test_explicit_save_only_and_no_silent_goal_replacement(client,account,monkeypatch):
 credentials.save(account['id'],'sk-fictional-goals');monkeypatch.setattr(config,'ENABLE_WEB_SEARCH',False)
 career_goals.save(account['id'],career_goals.Change(text='Explore data science',expected_revision=0))
 chat=client.post('/api/career-coach/chats',json={}).json()
 async def model(schema,payload,*a,**k):
  return reply(payload,recommendations=[],profile_goal_update='Explore nursing',profile_goal_save_quote=payload['question']),{'model':'fictional'}
 monkeypatch.setattr(ai,'structured',model)
 def act(text,token):return wait(client,client.post('/api/career-coach/chats/'+chat['id']+'/actions',json={'operation':'message','text':text,'request_token':token}).json())
 assert act('I might explore nursing','discussion-only')['status']=='failed'
 assert career_goals.read(account['id'])['text']=='Explore data science'
 assert act('Save my Career Goals: Explore nursing','explicit-goal-save')['status']=='completed'
 assert career_goals.read(account['id'])['text']=='Explore nursing'
 assert 'Explore nursing' not in json.dumps(coach.profile(account['id']))


def test_application_assistance_can_stop_without_filling_or_replaying(client,account,monkeypatch):
 from test_application_agent import run,scan,field
 credentials.save(account['id'],'sk-fictional-only');calls=[]
 async def delayed(*a,**k):calls.append(1);await asyncio.sleep(60)
 monkeypatch.setattr(ai,'call_api',delayed)
 r,c,_=run(client,account['id']);r=scan(client,r,c,[field(label='Why do you want this role?')]).json()['run']
 token='s'*32;url='/api/application-agent/runs/'+r['id']+'/assistance'
 body={'request_token':token,'question_id':'f0','action':'interpret','approved_cost_usd':.01,'consent':True}
 assert client.post(url,json=body).status_code==200
 for _ in range(50):
  if calls:break
  time.sleep(.01)
 active=client.get('/api/tasks/active').json();assert any(v['id']=='assistant:'+token for v in active)
 assert client.post('/api/tasks/assistant:'+token+'/cancel',json={}).status_code==200
 for _ in range(50):
  result=client.get(url+'/'+token).json()
  if result['state']=='cancelled':break
  time.sleep(.01)
 assert result['state']=='cancelled' and result['result'] is None and result['reserved_usd']>0
 assert client.post(url,json=body).json()['state']=='cancelled' and len(calls)==1
 assert client.get('/api/tasks/active').json()==[]


def test_goal_backup_restores_without_publishing_qualification_evidence(client,account):
 from conftest import onboard_test_account
 career_goals.save(account['id'],career_goals.Change(text='Earn a future public-health credential',expected_revision=0))
 payload=client.get('/api/account/export').json()
 other=client.post('/api/auth/register',json={'username':'goal-restoration','password':'fictional-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
 response=client.post('/api/account/import',files={'file':('backup.json',json.dumps(payload).encode(),'application/json')});assert response.status_code==200,response.text
 assert career_goals.read(other['id'])['text']=='Earn a future public-health credential'
 assert 'future public-health credential' not in json.dumps(coach.profile(other['id']))
 with db.connect() as c:assert not c.execute('SELECT 1 FROM evidence_fts WHERE user_id=? AND text LIKE ?', (other['id'],'%future public-health%')).fetchone()
