"""Fictional accounts only: atomic numbering, duplicate checks and backup compatibility."""
import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi import HTTPException
from app import db,interview_practice as interviews,saved_names,task_atomic

def test_numbering_per_type_account_concurrency_and_deletion(client,account):
 user=account['id']
 first=client.post('/api/interview-practice/sessions',json={'kind':'behavioral','title':'Ignored stale setup draft'}).json()
 assert first['data']['title']=='Behavioral 1'
 # Assignment is serialized with the session insert, even across browser tabs.
 with ThreadPoolExecutor(max_workers=5) as pool:
  rows=list(pool.map(lambda _:interviews.create(interviews.Setup(kind='behavioral'),user),range(5)))
 assert sorted(int(r['data']['title'].split()[-1]) for r in rows)==list(range(2,7))
 assert client.delete('/api/interview-practice/sessions/'+next(r['id'] for r in rows if r['data']['title']=='Behavioral 6')).status_code==200
 assert interviews.create(interviews.Setup(),user)['data']['title']=='Behavioral 7'
 for kind,label in saved_names.INTERVIEW_LABELS.items():
  if kind!='behavioral':assert interviews.create(interviews.Setup(kind=kind),user)['data']['title']==label+' 1'
 client.post('/api/auth/logout');client.headers.pop('X-CSRF-Token')
 other=client.post('/api/auth/register',json={'username':'othernames','password':'fictional-test-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
 assert client.post('/api/interview-practice/sessions',json={}).json()['data']['title']=='Behavioral 1'
 assert db.get(user,first['id'])==first

def test_invalid_starter_does_not_consume_name(client,account):
 assert client.post('/api/interview-practice/sessions',json={'kind':'coding','guide_question_id':'behavioral-teamwork'}).status_code==422
 assert db.list_entities(account['id'],'interview_session')==[]
 assert client.post('/api/interview-practice/sessions',json={}).json()['data']['title']=='Behavioral 1'

@pytest.mark.parametrize('path,kind',[('career-coach','coach_chat'),('knowledge-coach','assistant_chat')])
def test_duplicate_create_rename_normalization_and_scoping(client,account,path,kind):
 def create(title):return client.post('/api/'+path+'/chats',json={'title':title})
 a=create('Plan my career');assert a.status_code==200,a.text;a=a.json()
 assert create('  PLAN   my career ').status_code==409
 assert create('Ｐｌａｎ my career').status_code==409
 b=create('Another direction').json()
 value={'title':'plan my career'}
 if kind=='coach_chat':value['expected_updated_at']=b['updated_at']
 assert client.patch('/api/'+path+'/chats/'+b['id'],json=value).status_code==409
 assert db.get(account['id'],b['id'])['data']==b['data']
 # Updating other fields on an unchanged title remains supported.
 assert db.save(account['id'],kind,{**a['data'],'last_activity':'fictional'},a['id'])['data']['title']==a['data']['title']
 # Separate workflows may use the same name.
 other_kind='assistant_chat' if kind=='coach_chat' else 'coach_chat'
 assert db.save(account['id'],other_kind,{'title':'Plan my career'})
 # Name validation is before credentials, tasks, usage or provider calls.
 url='/api/'+path+'/chats/new/'+('actions' if kind=='coach_chat' else 'messages')
 response=client.post(url,json={'text':'Plan my career','request_token':'fictional-name-conflict'})
 assert response.status_code==409,response.text
 assert 'different name' in response.json()['detail']
 assert db.list_entities(account['id'],'usage_event')==[]
 with db.connect() as c:assert c.execute('SELECT count(*) FROM tasks').fetchone()[0]==0

def test_atomic_publish_rechecks_names(client,account):
 user=account['id'];task=db.uid();stamp=db.now()
 with db.connect() as c:c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',(task,user,'career_coach','running',None,None,stamp,stamp))
 token=task_atomic.bind(user,task)
 try:staged=db.save(user,'coach_chat',{'title':'Same name'})
 finally:task_atomic.reset(token)
 winner=db.save(user,'coach_chat',{'title':'Same name'})
 with pytest.raises(HTTPException):
  with db.connect() as c:c.execute('BEGIN IMMEDIATE');task_atomic.publish(c,user,task)
 assert db.get(user,staged['id']) is None
 assert db.get(user,winner['id'])==winner

def test_backup_import_avoids_name_collisions_and_preserves_content(client,account):
 user=account['id']
 s=client.post('/api/interview-practice/sessions',json={'guide_question_id':'behavioral-teamwork'}).json()
 # Use a real guide ID without depending on editorial IDs.
 if 'id' not in s:
  guide=client.get('/api/interview-practice/guides').json()['guides'][0]
  s=client.post('/api/interview-practice/sessions',json={'guide_question_id':guide['questions'][0]['id']}).json()
 a=db.save(user,'assistant_chat',{'title':'A saved conversation'})
 plan=client.post('/api/career-coach/chats',json={'title':'A saved plan'}).json()
 prep=db.save(user,'prep',{'confirmed_gaps':['Python'],'suggestions':[]})
 backup=client.get('/api/account/export').json()
 result=client.post('/api/account/import',files={'file':('names.json',json.dumps(backup).encode(),'application/json')})
 assert result.status_code==200,result.text
 for kind in ('interview_session','assistant_chat','coach_chat','prep'):
  rows=db.list_entities(user,kind);assert len(rows)==2
  assert len({saved_names.key(r['data']['title']) for r in rows})==2
 assert db.get(user,a['id'])==a and db.get(user,plan['id'])['data']==plan['data'] and db.get(user,prep['id'])==prep
 assert db.get(user,s['id'])==s
 assert len(db.list_entities(user,'interview_question'))==2
