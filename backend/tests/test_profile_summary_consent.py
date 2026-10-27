import json
from app import career_goals,career_coach,assistant_context,db,work_preferences,work_style_neo,ai,credentials,config
from test_career_coach import reply,wait

def test_legacy_goals_default_off_and_keep_text(client,account):
 u=account['id'];db.save(u,'career_goals',{'text':'Future research ambition','revision':7},career_goals.identity(u))
 value=client.get('/api/profile/career-goals').json()
 assert value['text']=='Future research ambition' and value['use_for_ai'] is False
 assert not career_goals.context(u)['text']
 assert not any(s['kind']=='aspiration' for s in assistant_context.sources(u))
 assert db.get(u,career_goals.identity(u),'career_goals')['data']=={'text':'Future research ambition','revision':7}

def test_goal_consent_revision_revocation_and_context(client,account):
 u=account['id'];value=client.put('/api/profile/career-goals',json={'text':'Research leadership','expected_revision':0}).json()
 assert value['use_for_ai'] is False and not career_goals.context(u)['text']
 value=client.put('/api/profile/career-goals',json={'text':'Research leadership','expected_revision':1,'use_for_ai':True}).json()
 snapshot=career_goals.context(u);assert snapshot['text']=='Research leadership'
 assert any(s['kind']=='aspiration' for s in assistant_context.retrieve(u,'leadership'))
 assert client.put('/api/profile/career-goals',json={'text':'stale','expected_revision':1,'use_for_ai':False}).status_code==409
 # Updating the text through an older client or explicitly authorized chat preserves consent.
 career_goals.save(u,career_goals.Change(text='Research leadership and communication',expected_revision=2))
 assert career_goals.read(u)['use_for_ai'] is True
 client.put('/api/profile/career-goals',json={'text':'Research leadership and communication','expected_revision':3,'use_for_ai':False})
 assert not career_goals.context(u,snapshot)['text']
 assert not any(s['kind']=='aspiration' for s in assistant_context.sources(u))
 assert snapshot['text']=='Research leadership' # Historical snapshots are not rewritten.
 assert 'Research leadership' not in json.dumps(career_coach.profile(u))

def test_plan_payload_honors_revocation_without_rewriting_history(client,account,monkeypatch):
 u=account['id'];credentials.save(u,'sk-fictional-summary');monkeypatch.setattr(config,'ENABLE_WEB_SEARCH',False)
 career_goals.save(u,career_goals.Change(text='Research leadership',expected_revision=0,use_for_ai=True))
 chat=client.post('/api/career-coach/chats',json={}).json();seen=[]
 career_goals.save(u,career_goals.Change(text='Research leadership',expected_revision=1,use_for_ai=False))
 async def model(schema,payload,*a,**kw):seen.append(payload);return reply(payload,recommendations=[]),{'model':'fictional'}
 monkeypatch.setattr(ai,'structured',model)
 result=wait(client,client.post('/api/career-coach/chats/'+chat['id']+'/actions',json={'operation':'message','text':'Brainstorm a useful project','request_token':'revoked-goals-context'}).json())
 assert result['status']=='completed',result
 assert seen and not seen[0]['career_goals_as_aspirations']['text']
 assert client.get('/api/career-coach/chats/'+chat['id']).json()['chat']['data']['profile_goals_snapshot']['text']=='Research leadership'
 new=client.post('/api/career-coach/chats',json={}).json();assert not new['data']['profile_goals_snapshot']['text']

def test_goal_backup_restores_consent_and_structured_items(client,account):
 u=account['id'];career_goals.save(u,career_goals.Change(text='Explore research',expected_revision=0,use_for_ai=True,items=[career_goals.Goal(id='future-skill',category='skill',text='Learn research methods')]))
 backup=client.get('/api/account/export').json()
 other=client.post('/api/auth/register',json={'username':'summary-restore','password':'fictional-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
 result=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')});assert result.status_code==200,result.text
 goals=career_goals.read(other['id']);assert goals['use_for_ai'] and goals['items'][1]['text']=='Learn research methods'
 assert career_goals.read(u)['use_for_ai']

def test_assessment_summary_is_local_and_raw_answers_excluded(client,account):
 u=account['id'];cat=work_style_neo.catalog();report=work_style_neo.score({x['id']:3 for x in cat['items']},{'p1':'left'})
 row=db.save(u,'work_style',{'status':'completed','completed_at':db.now(),'report':report,'answers':{'private':'SECRET_RAW'},'comparison_answers':{'private':'SECRET_COMPARE'}})
 value=client.get('/api/profile/work-preferences').json()
 assert len(value['assessment']['summary'])==5
 assert value['assessment']['summary'][0]=={k:report['domains'][0][k] for k in ('name','pattern')}
 assert 'SECRET' not in json.dumps(value) and value['preferences']==[] and value['assessment']['suggested_preferences']
 assert value['use_for_ai'] is False and not work_preferences.context(u)['preferences']
 assert not any(s['record_id']==row['id'] for s in assistant_context.sources(u))
