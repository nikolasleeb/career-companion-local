"""Writing guide uses fictional accounts and mocked providers; never paid requests."""
import asyncio
import copy
import json
import time

import pytest
from app import ai,db,credentials,guidance,knowledge_assistant as coach,career_coach,coach_bls
from app.network import ServiceError

def action(text='How should I write a cover letter?',**kw):
 return coach.Action(text=text,context_scope='writing',request_token='guide-'+db.uid(),**kw)

def answer(sources,**kw):
 s=next(s for s in sources if s['kind']=='writing_guidance')
 return {'answer':'Develop a relevant example and explain its connection to the role.',
         'references':[{'source_id':s['source_id'],'quote':s['text'][:80]}],**kw}

def test_catalog_and_builder_compatibility(client,account):
 value=client.get('/api/guidance').json()
 legacy=json.loads((guidance.config.CONTENT_DIR/'guidance.json').read_text())
 assert value['items']==legacy
 assert guidance.handbook()['sections'][0]['title']=='Resume essentials'
 for topic in ('resume','cover'):
  selected=guidance.selected(topic)
  assert set(selected)=={'version','items'}
  assert selected['items']==[r for r in legacy if r.get('topic') in (topic,'formatting') or r['id']=='guide_evidence']
 resources=guidance.handbook()['resources']
 assert len({r['url'] for r in resources})==len(resources)
 assert {'MIT CAPD','University of Arizona · Eller','Harvard Mignone Center','CareerOneStop','Greenhouse Support'}=={r['publisher'] for r in resources}

@pytest.mark.parametrize('question,expected',[
 ('How long should a resume be? One page or two?',{'writing:eller-format','writing:format-layout'}),
 ('Which font and margins should I choose?',{'writing:eller-format','writing:format-layout'}),
 ('How can I describe work with specific bullets?',{'writing:experience-specific'}),
 ('Can an ATS parser read my columns and tables?',{'writing:parser-limitations'}),
 ('Where are MIT samples for a PhD?',{'writing:mit-samples'}),
 ('Why this employer in my cover letter?',{'writing:cover-purpose'}),
])
def test_substantive_retrieval(question,expected):
 rows=guidance.retrieve(question)
 assert expected<={s['source_id'] for s in rows}
 assert all(s['publisher'] and s['audience'] and s['section'] and s['reviewed_at'] and s['revision'] for s in rows)
 assert {s['content_kind'] for s in guidance.writing_sources()}=={'original_excerpt','editorial_summary'}

def test_sources_only_default_and_conflicts(client,account,monkeypatch):
 calls=[]
 def forbidden(*a,**k):pytest.fail('A guide conversation attempted an outside lookup')
 monkeypatch.setattr(career_coach,'research',forbidden);monkeypatch.setattr(coach_bls,'run',forbidden)
 db.save(account['id'],'experience',{'category':'project','title':'SECRET_OTHER_CONTEXT','description':'SECRET_METHOD','confirmed':True})
 before=copy.deepcopy(db.list_entities(account['id'],'experience'))
 async def model(schema,payload,*a,**kw):
  calls.append(payload)
  assert payload['context_scope']=='writing' and payload['available_read_operations']==[]
  assert all(s['kind']=='writing_guidance' for s in payload['source_catalog'])
  assert 'SECRET' not in json.dumps(payload)
  assert 'conflicts' in kw['instructions'] and 'institutional preferences' in kw['instructions']
  rows=[s for s in payload['source_catalog'] if s['source_id'] in ('writing:eller-format','writing:format-layout')]
  assert len(rows)==2
  return {'answer':'Eller recommends one page for undergraduate resumes. CareerOneStop allows one or two depending on experience. Follow employer instructions.',
          'references':[{'source_id':s['source_id'],'quote':s['text'][:100]} for s in rows]}, {'model':'mock'}
 monkeypatch.setattr(ai,'structured',model)
 result=asyncio.run(coach.execute(account['id'],'new',action('Why do sources disagree about resume length?')))
 assert len(calls)==1 and result['chat']['data']['context_scope']=='writing'
 assert len(result['messages'][-1]['data']['reply']['references'])==2
 assert not result['messages'][-1]['data']['research_used']
 assert db.list_entities(account['id'],'experience')==before

def test_selected_only_context_change_and_revision(client,account,monkeypatch):
 u=account['id'];chosen=db.save(u,'experience',{'category':'project','title':'SELECTED_PROJECT','description':'Documented a laboratory method.','confirmed':True})
 unchosen=db.save(u,'experience',{'category':'project','title':'UNSELECTED_PROJECT','confirmed':True})
 calls=[]
 async def model(schema,payload,*a,**kw):
  calls.append(payload)
  personal=[s for s in payload['source_catalog'] if s['kind']!='writing_guidance']
  assert {s['record_id'] for s in personal}=={chosen['id']}
  assert 'UNSELECTED_PROJECT' not in json.dumps(payload)
  return answer(payload['source_catalog']),{'model':'mock'}
 monkeypatch.setattr(ai,'structured',model)
 body=action(selected_record_ids=[chosen['id']]);r=asyncio.run(coach.execute(u,'new',body));id=r['chat']['id']
 changed=client.post('/api/knowledge-coach/chats/'+id+'/messages',json=action(selected_record_ids=[unchosen['id']]).model_dump())
 assert changed.status_code==409
 assert len(calls)==1
 assert client.post('/api/knowledge-coach/chats/'+id+'/messages',json=coach.Action(text='Switch mode',request_token='switch-mode').model_dump()).status_code==409
 db.save(u,'experience',{**chosen['data'],'description':'Changed after the previous answer.'},chosen['id'])
 async def updated(schema,payload,*a,**kw):
  assert payload['conversation']==[] # Old personal facts cannot leak through conversation history.
  return answer(payload['source_catalog']),{'model':'mock'}
 monkeypatch.setattr(ai,'structured',updated)
 asyncio.run(coach.execute(u,id,body))
 backup=client.get('/api/account/export').json()
 restored=client.post('/api/account/import',files={'file':('guide.json',json.dumps(backup).encode(),'application/json')})
 assert restored.status_code==200,restored.text

def test_foreign_unreviewed_and_private_records_rejected(client,account):
 from fastapi.testclient import TestClient
 foreign=TestClient(client.app,base_url='http://127.0.0.1').post('/api/auth/register',json={'username':'other-guide-account','password':'fictional-guide-password'}).json()
 u=account['id'];other=db.save(foreign['id'],'experience',{'title':'FOREIGN','confirmed':True})
 draft=db.save(u,'experience',{'title':'DRAFT','confirmed':False})
 private=db.save(u,'profile_answer',{'answer_kind':'eligibility','answer':'SECRET','confirmed':True})
 for r in (other,draft,private):
  response=client.post('/api/knowledge-coach/chats/new/messages',json=action(selected_record_ids=[r['id']]).model_dump())
  assert response.status_code==404
 assert not db.list_entities(u,'assistant_chat')
 for kw in ({'pinned_ids':['anything']},{'excluded_ids':['anything']}):
  assert client.post('/api/knowledge-coach/chats/new/messages',json=action(**kw).model_dump()).status_code==422

@pytest.mark.parametrize('result',[
 {'references':[]},
 {'references':[{'source_id':'fabricated','quote':'Not real'}]},
 {'needs_research':True},
 {'research_topics':['current hiring']},
])
def test_unsupported_citations_and_outside_operations_fail_closed(client,account,monkeypatch,result):
 async def model(schema,payload,*a,**kw):return answer(payload['source_catalog'],**result),{'model':'mock'}
 monkeypatch.setattr(ai,'structured',model)
 with pytest.raises(ServiceError):asyncio.run(coach.execute(account['id'],'new',action()))
 assert not db.list_entities(account['id'],'assistant_message')

def test_not_covered_has_no_automatic_research(client,account,monkeypatch):
 async def model(schema,payload,*a,**kw):
  return {'answer':'This collection does not cover that employer’s current deadline. Check the posting.','references':[],'coverage':'not_covered'}, {'model':'mock'}
 monkeypatch.setattr(ai,'structured',model)
 r=asyncio.run(coach.execute(account['id'],'new',action('What is the latest employer deadline and salary?')))
 assert r['messages'][-1]['data']['reply']['coverage']=='not_covered'

def test_selected_record_revoked_during_provider_wait(client,account,monkeypatch):
 u=account['id'];record=db.save(u,'experience',{'category':'project','title':'Selected source','confirmed':True})
 async def model(schema,payload,*a,**kw):
  db.save(u,'experience',{**record['data'],'confirmed':False},record['id'])
  return answer(payload['source_catalog']),{'model':'mock'}
 monkeypatch.setattr(ai,'structured',model)
 with pytest.raises(Exception,match='selected record is unavailable'):
  asyncio.run(coach.execute(u,'new',action(selected_record_ids=[record['id']])))
 assert not db.list_entities(u,'assistant_message')

def test_cancellation_discards_partial_guide_chat(client,account,monkeypatch):
 import threading
 started=threading.Event();credentials.save(account['id'],'sk-fictional-never-sent')
 async def model(schema,payload,*a,**kw):
  started.set()
  await asyncio.sleep(30)
  return answer(payload['source_catalog']),{'model':'mock'}
 monkeypatch.setattr(ai,'structured',model)
 response=client.post('/api/knowledge-coach/chats/new/messages',json=action().model_dump())
 assert response.status_code==200,response.text
 assert started.wait(3)
 task_id=response.json()['task_id']
 assert client.post('/api/tasks/'+task_id+'/cancel',json={}).status_code==200
 for _ in range(200):
  task=client.get('/api/tasks/'+task_id).json()
  if task['status'] not in ('queued','running','cancelling'):break
  time.sleep(.01)
 assert task['status']=='cancelled'
 assert not db.list_entities(account['id'],'assistant_chat')
 assert not db.list_entities(account['id'],'assistant_message')

def test_request_deduplication_history_delete_and_keyless_reading(client,account,monkeypatch):
 calls=[];u=account['id']
 assert client.get('/api/guidance').status_code==200
 assert client.get('/api/knowledge-coach/context?context_scope=writing').status_code==200
 assert client.get('/api/knowledge-coach/chats').json()==[]
 credentials.save(u,'sk-fictional-never-sent')
 async def model(schema,payload,*a,**kw):calls.append(payload);return answer(payload['source_catalog']),{'model':'mock'}
 monkeypatch.setattr(ai,'structured',model)
 body=action().model_dump()
 first=client.post('/api/knowledge-coach/chats/new/messages',json=body)
 assert first.status_code==200,first.text
 for _ in range(200):
  task=client.get('/api/tasks/'+first.json()['task_id']).json()
  if task['status'] not in ('queued','running','cancelling'):break
  time.sleep(.01)
 assert task['status']=='completed',task
 repeated=client.post('/api/knowledge-coach/chats/new/messages',json=body)
 assert repeated.json()['task_id']==first.json()['task_id'] and len(calls)==1
 id=task['result']['chat']['id']
 assert len(client.get('/api/knowledge-coach/chats/'+id).json()['messages'])==2
 assert client.delete('/api/knowledge-coach/chats/'+id).status_code==200
 assert client.get('/api/knowledge-coach/chats/'+id).status_code==404
 assert not db.list_entities(u,'assistant_message')
 assert db.list_entities(u,'experience')
