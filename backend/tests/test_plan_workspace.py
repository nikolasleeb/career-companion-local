import copy,json
from datetime import datetime,timezone
import pytest
from app import db,config,credentials,ai,plan_progress as pp,daily_usage,career_coach as coach,cost_history
from test_career_coach import make,act,reply,wait
@pytest.fixture
def workspace(client,account,monkeypatch):
 u=account['id'];credentials.save(u,'sk-fictional-not-real');monkeypatch.setattr(config,'ENABLE_WEB_SEARCH',False);calls=[]
 async def fake(schema,payload,*args,**kwargs):calls.append(copy.deepcopy(payload));return reply(payload),{'model':'simulated','generated_at':db.now()}
 monkeypatch.setattr(ai,'structured',fake);chat=make(client);act(client,chat['id']);plan=client.get('/api/career-coach/chats/'+chat['id']).json()['plans'][0]
 return u,chat,plan,calls

def test_checklist_revision_scopes_and_ai_snapshot(client,workspace):
 u,chat,plan,calls=workspace;id=plan['id'];path='/api/career-coach/plans/'+id+'/progress';p=client.get(path).json();mid=plan['data']['actions'][0]['id'];sid=p['step_ids'][mid][0]
 assert p['total']==3 and p['completed']==0
 r=client.patch(path,json={'expected_revision':0,'milestone_id':mid,'step_id':sid,'completed':True});assert r.status_code==200,r.text;p=r.json();assert p['completed']==1 and p['percent']==33 and p['milestones'][mid]['state']=='in_progress'
 assert client.patch(path,json={'expected_revision':0,'milestone_id':mid,'completed':True}).status_code==409
 assert client.patch(path,json={'expected_revision':1,'milestone_id':mid,'step_id':'other','completed':True}).status_code==404
 assert len(calls)==1
 r=client.post('/api/career-coach/chats/'+chat['id']+'/actions',json={'operation':'message','text':'Explain this step','plan_ref':{'plan_id':id,'milestone_id':mid,'step_id':sid},'request_token':'step-context-check'});t=wait(client,r.json());assert t['status']=='completed',t
 assert calls[-1]['selected_plan_context']['progress']['completed']==1
 assert calls[-1]['selected_plan_context']['selected_step_id']==sid
 assert client.get(path).json()==p # AI did not change progress.
 another=make(client);assert client.post('/api/career-coach/chats/'+another['id']+'/actions',json={'operation':'message','text':'Foreign chat','plan_ref':{'plan_id':id},'request_token':'wrong-chat-check'}).status_code==404
 r=client.patch(path,json={'expected_revision':1,'milestone_id':mid,'completed':True}).json();assert r['percent']==100 and r['milestones'][mid]['completed_at']
 assert client.patch(path,json={'expected_revision':2,'milestone_id':mid,'completed':False}).json()['completed']==0
 assert not db.list_entities(u,'usage_event') # All model calls in this test are simulated.

def test_versions_inherit_unchanged_steps_only_and_legacy(client,workspace):
 u,chat,plan,calls=workspace;path='/api/career-coach/plans/'+plan['id']+'/progress';mid=plan['data']['actions'][0]['id'];p=client.get(path).json()
 client.patch('/api/career-coach/chats/'+chat['id']+'/actions/'+mid,json={'state':'completed'})
 assert client.get(path).json()['completed']==3
 result=act(client,chat['id'],'message','Revise the plan','new-version-test');a=copy.deepcopy(plan['data']['actions'][0]);a['steps'][1]='A new different step'
 r=client.post('/api/career-coach/chats/'+chat['id']+'/roadmap',json={'message_id':result['result']['id'],'milestones':[{k:a.get(k,'') for k in ('id','title','steps','period_label','due_date','effort')}]});assert r.status_code==200,r.text
 new=client.get('/api/career-coach/plans/'+r.json()['id']+'/progress').json();assert new['completed']==2 and client.get(path).json()['completed']==3
 # Legacy plans with no dedicated record are readable without migration writes.
 for row in db.list_entities(u,pp.KIND):db.delete(u,row['id'])
 before=db.list_entities(u,pp.KIND);assert client.get(path).json()['completed']==3 and db.list_entities(u,pp.KIND)==before

def test_checklist_backup_restore_cleanup_and_isolation(client,workspace):
 u,chat,plan,calls=workspace;mid=plan['data']['actions'][0]['id'];path='/api/career-coach/plans/'+plan['id']+'/progress';client.patch(path,json={'expected_revision':0,'milestone_id':mid,'completed':True})
 backup=client.get('/api/account/export').json();assert any(r['kind']==pp.KIND for r in backup['records'])
 restored=client.post('/api/account/import',files={'file':('account.json',json.dumps(backup).encode(),'application/json')});assert restored.status_code==200,restored.text
 other=client.post('/api/auth/register',json={'username':'plan-other','password':'fictional-password'}).json();client.headers['X-CSRF-Token']=other['csrf'];assert client.get(path).status_code==404
 assert client.post('/api/account/import',files={'file':('account.json',json.dumps(backup).encode(),'application/json')}).status_code==200
 plans=client.get('/api/career-coach/plans').json()['plans'];assert plans[0]['checklist']['completed']==3
 preview=client.post('/api/account/cleanup/preview',json={'categories':['plans'],'action':'delete'}).json();assert pp.KIND in {r['kind'] for r in preview['records']}
 assert client.post('/api/account/cleanup/apply',json={'preview_id':preview['preview_id'],'confirmed':True}).status_code==200
 assert not db.list_entities(other['id'],pp.KIND)

def event(u,key,at,amount,status='completed',partial=False):
 return cost_history.write(u,{'event_key':key,'occurred_at':at,'model':'simulated','process':'career_coach','status':status,'estimated_cost_usd':amount,'partial':partial})
def test_daily_warning_boundaries_timezones_unknowns_and_settings(client,account):
 u=account['id'];now=datetime(2026,10,29,8,tzinfo=timezone.utc)
 assert daily_usage.summary(u,'America/Phoenix',now)['estimated_cost_usd']==0
 assert client.put('/api/settings',json={'daily_spend_warning_usd':10,'usage_timezone':'America/Phoenix'}).status_code==200
 event(u,'outside','2026-10-29T06:59:59+00:00',20)
 row=event(u,'inside','2026-10-29T07:00:00+00:00',7.99)
 assert daily_usage.summary(u,'UTC',now)['warning_state']=='normal'
 db.save(u,'usage_event',{**row['data'],'estimated_cost_usd':8},row['id']);assert daily_usage.summary(u,'UTC',now)['warning_state']=='near'
 db.save(u,'usage_event',{**row['data'],'estimated_cost_usd':10},row['id']);assert daily_usage.summary(u,'UTC',now)['warning_state']=='limit'
 event(u,'pending','2026-10-29T07:30:00+00:00',None,'pending',True);v=daily_usage.summary(u,'UTC',now);assert v['partial'] and v['pending_requests']==1 and v['estimated_cost_usd']==10
 assert client.put('/api/settings',json={'daily_spend_warning_usd':0}).status_code==200
 assert daily_usage.summary(u,'UTC',now)['percent'] is None
 for value in [-1,float('inf')]:
  if value==-1:assert client.put('/api/settings',json={'daily_spend_warning_usd':value}).status_code==422
 assert client.put('/api/settings',json={'usage_timezone':'invalid/zone'}).status_code==422
 # Reads do not write/recover requests or alter warning settings.
 before=db.list_entities(u,'usage_event');assert client.get('/api/usage/today?tz=UTC').status_code==200;assert db.list_entities(u,'usage_event')==before
 assert daily_usage.summary(u,'UTC',datetime(2026,10,30,8,tzinfo=timezone.utc))['estimated_cost_usd']==0

def test_only_unknown_cost_is_not_zero(client,account):
 u=account['id'];event(u,'unknown',db.now(),None,'failed',True)
 assert client.get('/api/usage/today').json()['estimated_cost_usd'] is None
 other=client.post('/api/auth/register',json={'username':'usage-other','password':'fictional-password'}).json();assert client.get('/api/usage/today').json()['estimated_cost_usd']==0

def test_duplicate_milestone_steps_are_independent():
 a={'id':'one','kind':'project','title':'Practice','steps':['Repeat']};b={**a,'id':'two'}
 ids=pp.step_ids({'data':{'actions':[a,b]}})
 assert ids['one']!=ids['two']

def test_failed_cancelled_and_duplicate_ai_preserve_checklists(client,workspace,monkeypatch):
 from app.network import ServiceError
 u,chat,plan,calls=workspace;mid=plan['data']['actions'][0]['id'];path='/api/career-coach/plans/'+plan['id']+'/progress'
 before=client.patch(path,json={'expected_revision':0,'milestone_id':mid,'completed':True}).json()
 async def fail(*a,**kw):raise ServiceError('Simulated provider failure; no paid retry')
 monkeypatch.setattr(ai,'structured',fail)
 body={'operation':'message','text':'Explain this plan','plan_ref':{'plan_id':plan['id']},'request_token':'failure-preservation'}
 started=client.post('/api/career-coach/chats/'+chat['id']+'/actions',json=body).json();result=wait(client,started);assert result['status']=='failed'
 assert client.post('/api/career-coach/chats/'+chat['id']+'/actions',json=body).json()['task_id']==started['task_id']
 assert client.get(path).json()==before and len(db.list_entities(u,'coach_plan'))==1
 # Invalid scoped references are rejected before queueing another paid action.
 assert client.post('/api/career-coach/chats/'+chat['id']+'/actions',json={**body,'request_token':'invalid-selection','plan_ref':{'plan_id':plan['id'],'milestone_id':'missing'}}).status_code==404
 assert len(calls)==1

def test_daily_dst_repeated_requests_and_partial_tool_costs(client,account):
 u=account['id'];now=datetime(2026,11,1,16,tzinfo=timezone.utc)
 assert client.put('/api/settings',json={'usage_timezone':'America/New_York','daily_spend_warning_usd':1}).status_code==200
 event(u,'first','2026-11-01T04:00:00+00:00',.4)
 event(u,'second','2026-11-02T04:59:59+00:00',.7)
 value=daily_usage.summary(u,now=now)
 assert value['requests']==2 and value['estimated_cost_usd']==1.1 and value['warning_state']=='limit'
 assert value['next_midnight']=='2026-11-02T00:00:00-05:00'
 # The same ledger request is one event, including its known partial tool estimate.
 event(u,'first','2026-11-01T04:00:00+00:00',.6,'completed',True)
 value=daily_usage.summary(u,now=now);assert value['requests']==2 and value['estimated_cost_usd']==1.3 and value['partial']
 backup=client.get('/api/account/export').json();assert backup['profile']['daily_spend_warning_usd']==1 and backup['profile']['usage_timezone']=='America/New_York'

def test_older_selected_version_is_revision_parent_and_consent_rechecked(client,workspace):
 u,chat,first,calls=workspace;mid=first['data']['actions'][0]['id'];path='/api/career-coach/plans/'+first['id']+'/progress'
 client.patch(path,json={'expected_revision':0,'milestone_id':mid,'completed':True})
 result=act(client,chat['id'],'message','Create another version','version-parent-other')
 second=client.post('/api/career-coach/chats/'+chat['id']+'/roadmap',json={'message_id':result['result']['id']}).json()
 client.patch('/api/career-coach/plans/'+second['id']+'/progress',json={'expected_revision':0,'milestone_id':mid,'completed':False})
 r=client.post('/api/career-coach/chats/'+chat['id']+'/actions',json={'operation':'message','text':'Revise this older plan','plan_ref':{'plan_id':first['id']},'request_token':'version-parent-selected'})
 result=wait(client,r.json());assert result['status']=='completed'
 third=client.post('/api/career-coach/chats/'+chat['id']+'/roadmap',json={'message_id':result['result']['id']}).json()
 assert client.get('/api/career-coach/plans/'+third['id']+'/progress').json()['completed']==3
 assert client.get('/api/career-coach/plans/'+second['id']+'/progress').json()['completed']==0
 # A previously copied gated input cannot be shared through a plan after consent is off.
 db.save(u,'coach_plan',{**first['data'],'work_style_summary':'Private reviewed summary'},first['id']);before=len(calls)
 response=client.post('/api/career-coach/chats/'+chat['id']+'/actions',json={'operation':'message','text':'Use this plan','plan_ref':{'plan_id':first['id']},'request_token':'revoked-consent'})
 assert response.status_code==409 and len(calls)==before
