import asyncio,json,time
import pytest
from app import db,task_atomic

def test_overlay_is_invisible_and_publish_is_atomic(client,account):
 user=account['id'];id=db.uid()
 with db.connect() as c:c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',(id,user,'career_coach','running',None,None,db.now(),db.now()))
 token=task_atomic.bind(user,id)
 try:
  record=db.save(user,'prep',{'question':'Fictional staged result'})
  assert db.get(user,record['id'])
  with task_atomic.outside():assert db.get(user,record['id']) is None
 finally:task_atomic.reset(token)
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');task_atomic.publish(c,user,id)
 assert db.get(user,record['id'])

def test_cancel_during_provider_discards_all_stages(client,account,monkeypatch):
 from app import ai,credentials
 credentials.save(account['id'],'sk-fictional-never-sent')
 async def blocked(*a,**k):
  db.save(account['id'],'prep',{'temporary':'never publish'})
  await asyncio.sleep(60)
 monkeypatch.setattr(ai,'structured',blocked)
 chat=client.post('/api/career-coach/chats',json={}).json()
 task=client.post('/api/career-coach/chats/'+chat['id']+'/actions',json={'operation':'message','text':'Help me brainstorm a direction','request_token':'stop-fictional-request'}).json()
 for _ in range(100):
  with db.connect() as c:count=c.execute('SELECT count(*) FROM cc_task_stage WHERE task_id=?',(task['task_id'],)).fetchone()[0]
  if count:break
  time.sleep(.01)
 assert db.list_entities(account['id'],'prep')==[]
 result=client.post('/api/tasks/'+task['task_id']+'/cancel',json={});assert result.status_code==200,result.text
 for _ in range(100):
  value=client.get('/api/tasks/'+task['task_id']).json()
  if value['status']=='cancelled':break
  time.sleep(.01)
 assert value['status']=='cancelled',value
 assert db.list_entities(account['id'],'prep')==[]
 assert client.get('/api/career-coach/chats/'+chat['id']).json()['messages']==[]
 with db.connect() as c:assert c.execute('SELECT count(*) FROM cc_task_stage WHERE task_id=?',(task['task_id'],)).fetchone()[0]==0
 assert client.post('/api/tasks/'+task['task_id']+'/cancel',json={}).json()['already_finished']

def test_late_threads_and_concurrent_edits_cannot_publish(client,account):
 user=account['id'];record=db.save(user,'prep',{'value':'before'});id=db.uid()
 with db.connect() as c:c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',(id,user,'preparation','running',None,None,db.now(),db.now()))
 token=task_atomic.bind(user,id)
 try:db.save(user,'prep',{'value':'generated'},record['id'])
 finally:task_atomic.reset(token)
 db.save(user,'prep',{'value':'manual edit'},record['id'])
 from fastapi import HTTPException
 with pytest.raises(HTTPException):
  with db.connect() as c:c.execute('BEGIN IMMEDIATE');task_atomic.publish(c,user,id)
 assert db.get(user,record['id'])['data']['value']=='manual edit'
 with db.connect() as c:c.execute("UPDATE tasks SET status='cancelled' WHERE id=?",(id,));task_atomic.discard(c,id)
 token=task_atomic.bind(user,id)
 try:
  with pytest.raises(task_atomic.Stopped):db.save(user,'prep',{'value':'late thread'},record['id'])
 finally:task_atomic.reset(token)
 assert db.get(user,record['id'])['data']['value']=='manual edit'

def test_usage_survives_discard(client,account):
 from app import cost_history
 id=db.uid();user=account['id']
 with db.connect() as c:c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',(id,user,'preparation','running',None,None,db.now(),db.now()))
 token=task_atomic.bind(user,id)
 try:
  db.save(user,'prep',{'temporary':True})
  event=cost_history.begin({'user_id':user,'task_id':id,'process':'preparation'},{'model':'gpt-6-luna'})
 finally:task_atomic.reset(token)
 with db.connect() as c:task_atomic.discard(c,id)
 assert db.get(user,event['id'],'usage_event') and db.list_entities(user,'prep')==[]

def test_stop_closes_provider_transport_and_keeps_unknown_usage(client,account,monkeypatch):
 from app import ai,credentials,config
 credentials.save(account['id'],'sk-fictional-transport');monkeypatch.setattr(config,'ENABLE_WEB_SEARCH',False)
 observed=[]
 class Transport:
  async def __aenter__(self):return self
  async def __aexit__(self,*args):observed.append('closed')
  async def post(self,*a,**kw):observed.append('sent');await asyncio.sleep(60)
 monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kwargs:Transport())
 value=client.post('/api/career-coach/chats/new/actions',json={'operation':'message','text':'Help me brainstorm a direction','request_token':'transport-stop-test'}).json()
 for _ in range(100):
  if 'sent' in observed:break
  time.sleep(.01)
 assert observed==['sent']
 client.post('/api/tasks/'+value['task_id']+'/cancel',json={})
 for _ in range(100):
  if client.get('/api/tasks/'+value['task_id']).json()['status']=='cancelled':break
  time.sleep(.01)
 assert observed==['sent','closed']
 assert not db.list_entities(account['id'],'coach_chat')
 events=db.list_entities(account['id'],'usage_event');assert len(events)==1
 assert events[0]['data']['status']=='unknown' and events[0]['data']['estimated_cost_usd'] is None

def test_stop_before_dispatch_and_late_thread_cannot_commit(client,account):
 import threading
 from app import main
 user=account['id'];record=db.save(user,'prep',{'value':'original'});started=threading.Event();release=threading.Event();done=threading.Event();blocked=[]
 def renderer():
  started.set();release.wait(3)
  try:db.save(user,'prep',{'value':'late generated artifact'},record['id'])
  except task_atomic.Stopped:blocked.append(True)
  finally:done.set()
 async def scenario():
  first=main.start_task(user,'resume',lambda:asyncio.sleep(60))
  await main.cancel_task(first['task_id'],{'id':user})
  assert main.get_task(first['task_id'],{'id':user})['status']=='cancelled'
  second=main.start_task(user,'resume',lambda:asyncio.to_thread(renderer))
  for _ in range(100):
   if started.is_set():break
   await asyncio.sleep(.01)
  assert started.is_set()
  await main.cancel_task(second['task_id'],{'id':user});release.set()
  for _ in range(100):
   if done.is_set():break
   await asyncio.sleep(.01)
  assert done.is_set() and blocked
 asyncio.run(scenario())
 assert db.get(user,record['id'])['data']['value']=='original'


def test_staged_profile_and_settings_rollback_as_one_unit(client,account):
 user=account['id'];id=db.uid();before=db.settings(user);education=db.list_entities(user,'experience')[0]
 with db.connect() as c:c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',(id,user,'resume_guided','running',None,None,db.now(),db.now()))
 token=task_atomic.bind(user,id)
 try:
  db.update_settings(user,{'headline':'Temporary generated headline'})
  db.save(user,'experience',{**education['data'],'title':'Temporary approved detail'},education['id'])
  with task_atomic.outside():
   assert db.settings(user)==before and db.get(user,education['id'])==education
 finally:task_atomic.reset(token)
 with db.connect() as c:task_atomic.discard(c,id);c.execute("UPDATE tasks SET status='cancelled' WHERE id=?",(id,))
 assert db.settings(user)==before and db.get(user,education['id'])==education
