import asyncio,json,time,copy
import pytest
from app import db,private_profile,private_answers,config,career_goals,work_preferences,ai,credentials
from test_career_coach import wait
VALUES={'us_citizen':'yes','authorized_us':'yes','sponsorship_now':'no','sponsorship_future':'unsure'}
def raw_settings(user):
 with db.connect() as c:return json.loads(c.execute('SELECT settings FROM users WHERE id=?',(user,)).fetchone()[0])
def test_status_migration_is_lossless_encrypted_idempotent_and_compatible(client,account):
 u=account['id'];d={**raw_settings(u),**VALUES,'name':'Fictional User'}
 with db.connect() as c:c.execute('UPDATE users SET settings=? WHERE id=?',(json.dumps(d),u))
 private_profile.migrate_statuses()
 assert not set(VALUES)&raw_settings(u).keys()
 assert {k:db.settings(u)[k] for k in VALUES}==VALUES
 with db.connect() as c:cipher=c.execute("SELECT ciphertext FROM cc_private_profile WHERE user_id=? AND section='authorization'",(u,)).fetchone()[0]
 assert private_answers.unseal(u,'private-profile:authorization',cipher)==VALUES
 private_profile.migrate_statuses()
 with db.connect() as c:assert c.execute("SELECT ciphertext FROM cc_private_profile WHERE user_id=? AND section='authorization'",(u,)).fetchone()[0]==cipher
 db.update_settings(u,{'name':'Changed contact','authorized_us':'unsure'})
 assert db.settings(u)['authorized_us']=='unsure' and db.settings(u)['us_citizen']=='yes'
 assert not set(VALUES)&raw_settings(u).keys()
 assert not set(VALUES)&client.get('/api/account/export').json()['profile'].keys()
 with pytest.raises(Exception):private_answers.unseal('another-account','private-profile:authorization',cipher)
def test_failed_migration_or_missing_key_preserves_data(client,account,monkeypatch):
 u=account['id'];private_answers.key()
 with db.connect() as c:c.execute('UPDATE users SET settings=? WHERE id=?',(json.dumps(VALUES),u))
 original=private_profile.store
 def fail(*a,**k):raise RuntimeError('Fictional migration failure')
 monkeypatch.setattr(private_profile,'store',fail)
 with pytest.raises(RuntimeError):private_profile.migrate_statuses()
 assert raw_settings(u)==VALUES
 monkeypatch.setattr(private_profile,'store',original)
 private_profile.migrate_statuses();config.VAULT_KEY_FILE.unlink()
 with pytest.raises(Exception):db.settings(u)
 assert not config.VAULT_KEY_FILE.exists() and not set(VALUES)&raw_settings(u).keys()
def test_legacy_backup_authorization_is_imported_into_vault(client,account):
 backup=client.get('/api/account/export').json();backup['profile'].update(VALUES)
 r=client.post('/api/account/import',files={'file':('legacy.json',json.dumps(backup).encode(),'application/json')})
 assert r.status_code==200,r.text
 assert private_profile.authorization(account['id'])==VALUES and not set(VALUES)&raw_settings(account['id']).keys()
def test_general_statement_conversion_limits_and_entry_operations(client,account):
 u=account['id'];long='A long career direction. '*180
 specific={'id':'future-cert','category':'certification','text':'Earn a future credential','target':'2028','priority':'high','progress':'planned'}
 db.save(u,'career_goals',{'note':long,'text':long+'\ncertification: Earn a future credential','items':[specific],'revision':5},career_goals.identity(u))
 before=copy.deepcopy(db.get(u,career_goals.identity(u),'career_goals'));value=client.get('/api/profile/career-goals').json()
 assert value['items'][0]['text']==long and value['items'][1]==specific and db.get(u,career_goals.identity(u),'career_goals')==before
 items=value['items'];bad=items+[dict(items[0],id='second-general')]
 assert client.put('/api/profile/career-goals',json={'items':bad,'expected_revision':5}).status_code==422
 items[1]['text']='Revised future credential';r=client.put('/api/profile/career-goals',json={'items':items,'expected_revision':5})
 assert r.status_code==200 and r.json()['note']==long and r.json()['text'].count('Revised future credential')==1
 assert client.put('/api/profile/career-goals',json={'items':[],'expected_revision':5}).status_code==409
 assert client.put('/api/profile/career-goals',json={'items':items[:1],'expected_revision':6}).status_code==200
 r=client.put('/api/profile/career-goals',json={'expected_revision':7,'use_for_ai':True});assert r.json()['items']==items[:1]
@pytest.fixture
def work(client,account):
 u=account['id'];credentials.save(u,'sk-fictional-work-summary')
 db.save(u,'work_style',{'status':'completed','report':{'preferences':[{'selected':'I prefer focused work with planned team check-ins.'}],'domains':[{'name':'Private assessment','pattern':'SECRET_ASSESSMENT_DESCRIPTION'}]},'answers':{'secret':'SECRET_RATINGS'}})
 db.save(u,'experience',{'category':'project','title':'SECRET_PROFESSIONAL_PROFILE','confirmed':True})
 return u
def body(**kw):return {'operation':'generate','notes':'I enjoy collaboration after time to prepare.','draft':'','expected_revision':0,'request_token':'summary-once-token',**kw}
def test_summary_whitelist_estimate_one_request_recovery_and_review(client,work,monkeypatch):
 calls=[]
 async def model(schema,payload,*a,**kw):
  calls.append((payload,kw));source=payload['source_statements'][0]
  return {'summary':'I like focused work and planned check-ins, with time to prepare before collaborating.','references':[{'source_id':source['id'],'quote':source['text']}]},{'model':'fictional','usage':{'output_tokens':20}}
 monkeypatch.setattr(ai,'structured',model)
 assert client.get('/api/profile/work-preferences').status_code==200
 assert client.post('/api/profile/work-preferences/summary/estimate',json=body()).status_code==200 and not calls
 start=client.post('/api/profile/work-preferences/summary/actions',json=body());result=wait(client,start.json());assert result['status']=='completed',result
 assert len(calls)==1 and calls[0][1]['retry_allowed'] is False and 'SECRET' not in json.dumps(calls[0][0])
 assert work_preferences.read(work)['summary']==''
 assert client.post('/api/profile/work-preferences/summary/actions',json=body()).json()['task_id']==start.json()['task_id'] and len(calls)==1
 assert client.get('/api/ai-actions/'+body()['request_token']).json()['task_id']==start.json()['task_id']
 proposal=result['result'];r=client.put('/api/profile/work-preferences',json={'summary':proposal['summary'],'reviewed':True,'use_for_ai':True,'expected_revision':0,'generation_task_id':start.json()['task_id']})
 assert r.status_code==200,r.text
 assert work_preferences.context(work)['preferences']==[proposal['summary']] and r.json()['generation']['ai']['model']=='fictional'
 assert client.put('/api/profile/work-preferences',json={'summary':proposal['summary'],'reviewed':True,'use_for_ai':False,'expected_revision':1}).status_code==200
 assert not work_preferences.context(work)['preferences']
def test_summary_validation_private_notes_and_stale_revision(client,work,monkeypatch):
 calls=[]
 async def model(*a,**k):calls.append(1);return {'summary':'word '*251,'references':[]},{'model':'fictional'}
 monkeypatch.setattr(ai,'structured',model)
 assert client.post('/api/profile/work-preferences/summary/actions',json=body(notes='Include my political views')).status_code==422 and not calls
 r=wait(client,client.post('/api/profile/work-preferences/summary/actions',json=body()).json());assert r['status']=='failed' and len(calls)==1 and not work_preferences.read(work)['summary']
 assert client.put('/api/profile/work-preferences',json={'summary':'word '*251,'reviewed':True,'use_for_ai':False,'expected_revision':0}).status_code==422
 assert client.put('/api/profile/work-preferences',json={'summary':'I like planned check-ins.','reviewed':False,'use_for_ai':True,'expected_revision':0}).status_code==422
 client.put('/api/profile/work-preferences',json={'summary':'I like planned check-ins.','reviewed':True,'use_for_ai':False,'expected_revision':0})
 assert client.post('/api/profile/work-preferences/summary/actions',json=body(request_token='stale-summary-token')).status_code==409 and len(calls)==1
def test_summary_cancel_retains_saved_state_and_no_repeat(client,work,monkeypatch):
 client.put('/api/profile/work-preferences',json={'summary':'I like planned check-ins.','reviewed':True,'use_for_ai':True,'expected_revision':0});before=copy.deepcopy(work_preferences.read(work));calls=[]
 async def delayed(*a,**kw):calls.append(1);await asyncio.sleep(60)
 monkeypatch.setattr(ai,'structured',delayed)
 b=body(operation='revise',draft='I like planned check-ins.',notes='Emphasize quiet preparation time.',expected_revision=1)
 start=client.post('/api/profile/work-preferences/summary/actions',json=b).json()
 for _ in range(80):
  if calls:break
  time.sleep(.01)
 assert client.post('/api/tasks/'+start['task_id']+'/cancel',json={}).status_code==200
 result=wait(client,start);assert result['status']=='cancelled' and work_preferences.read(work)==before
 assert client.post('/api/profile/work-preferences/summary/actions',json=b).json()['task_id']==start['task_id'] and len(calls)==1

def test_summary_provider_wire_and_usage_ledger(client,work,monkeypatch):
 calls=[]
 class Response:
  status_code=200;headers={}
  def __init__(self,value):self.value=value
  def json(self):return self.value
 class Provider:
  def __init__(self,*a,**k):pass
  async def __aenter__(self):return self
  async def __aexit__(self,*a):pass
  async def post(self,url,**kw):
   wire=kw['json'];calls.append(wire);p=json.loads(wire['input']);source=p['source_statements'][0]
   value={'summary':'I prefer focused work with planned check-ins.','references':[{'source_id':source['id'],'quote':source['text']}]}
   return Response({'id':'mock-summary-response','model':'gpt-6.1-sol','status':'completed','usage':{'input_tokens':200,'output_tokens':60},'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(value)}]}]})
 monkeypatch.setattr(ai.httpx,'AsyncClient',Provider)
 r=wait(client,client.post('/api/profile/work-preferences/summary/actions',json=body()).json());assert r['status']=='completed',r
 assert len(calls)==1 and calls[0]['store'] is False and not calls[0].get('tools')
 usage=db.list_entities(work,'usage_event');assert len(usage)==1 and usage[0]['data']['process']=='work_style_summary' and usage[0]['data']['estimated_cost_usd'] is not None
 assert 'source_statements' not in json.dumps(usage) and not work_preferences.read(work)['summary']

def test_summary_rejects_unsupported_refs_and_concurrent_save(client,work,monkeypatch):
 async def unsupported(schema,payload,*a,**k):return {'summary':'I like flexible work.','references':[{'source_id':'invented','quote':'not supplied'}]},{'model':'fictional'}
 monkeypatch.setattr(ai,'structured',unsupported)
 result=wait(client,client.post('/api/profile/work-preferences/summary/actions',json=body()).json());assert result['status']=='failed' and not work_preferences.read(work)['summary']
 async def conflict(schema,payload,*a,**k):
  from app.task_atomic import outside
  with outside():work_preferences.put(work_preferences.Change(expected_revision=0,summary='My newer manual summary.',reviewed=True,use_for_ai=False),{'id':work})
  source=payload['source_statements'][0]
  return {'summary':'I like focused work.','references':[{'source_id':source['id'],'quote':source['text']}]},{'model':'fictional'}
 monkeypatch.setattr(ai,'structured',conflict)
 result=wait(client,client.post('/api/profile/work-preferences/summary/actions',json=body(request_token='concurrent-summary')).json());assert result['status']=='failed' and work_preferences.read(work)['summary']=='My newer manual summary.'

def test_long_general_statement_and_chat_snapshots_round_trip(client,account):
 u=account['id'];general='a'*36000
 career_goals.save(u,career_goals.Change(text=general,items=[career_goals.Goal(id='long-specific',category='skill',text='b'*1000)],use_for_ai=True,expected_revision=0))
 assert client.post('/api/career-coach/chats',json={}).status_code==200
 backup=client.get('/api/account/export').json()
 r=client.post('/api/account/import',files={'file':('long-goals.json',json.dumps(backup).encode(),'application/json')})
 assert r.status_code==200,r.text
 assert career_goals.read(u)['items'][0]['text']==general

def test_summary_action_preserves_education_gate(client,account,monkeypatch):
 other=client.post('/api/auth/register',json={'username':'summary-needs-education','password':'fictional-password'}).json();client.headers['X-CSRF-Token']=other['csrf'];credentials.save(other['id'],'sk-fictional-only')
 assert client.get('/api/profile/work-preferences').status_code==403
 assert client.post('/api/profile/work-preferences/summary/actions',json=body()).status_code==403
 assert not db.list_entities(other['id'],'usage_event')
