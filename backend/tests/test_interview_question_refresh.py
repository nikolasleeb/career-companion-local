"""Explicit generation replaces only unused AI questions, atomically on success."""
import asyncio
import json
import time
import pytest
from app import ai,db,interview_practice as practice
from app.network import ServiceError
from test_interview_practice import create,load,body,wait,model


def generated(client,s,model):
 result=wait(client,client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=body(s)))
 assert result['status']=='completed',result
 d=load(client,s['id'])
 return d,d['questions'][-1]


def change_question(monkeypatch):
 original=ai.structured
 async def changed(*args,**kwargs):
  output,meta=await original(*args,**kwargs)
  return {**output,'question':'Describe a real disagreement about priorities. How did you resolve it?','topic':'Prioritization and disagreement'},meta
 monkeypatch.setattr(ai,'structured',changed)


@pytest.mark.parametrize('kind',['behavioral','star','coding','case','domain','presentation','other'])
def test_replace_unanswered_generated_question_on_success(client,account,model,monkeypatch,kind):
 d,q=generated(client,create(client,kind=kind),model);change_question(monkeypatch)
 b=body(d['session'],question_id=q['id'],replace_question_id=q['id'])
 result=wait(client,client.post('/api/interview-practice/sessions/'+d['session']['id']+'/actions',json=b))
 assert result['status']=='completed',result
 current=load(client,d['session']['id'])
 assert len(current['questions'])==1 and current['questions'][0]['id']!=q['id']
 assert db.get(account['id'],q['id']) is None
 assert q['data']['question'] in model[-1][1]['previous_questions']
 assert q['data']['topic'] in model[-1][1]['previous_topics']
 assert len(model)==2 and not model[-1][2]['retry_allowed']
 # Reusing a completed request does not remove another question or charge again.
 assert client.post('/api/interview-practice/sessions/'+d['session']['id']+'/actions',json=b).status_code==200
 assert len(model)==2
 exported=client.get('/api/account/export').json()
 assert client.post('/api/account/import',files={'file':('backup.json',json.dumps(exported).encode(),'application/json')}).status_code==200


@pytest.mark.parametrize('failure',['provider','duplicate','invalid-reference','cancel'])
def test_failed_replacement_keeps_original(client,account,model,monkeypatch,failure):
 d,q=generated(client,create(client),model);original=ai.structured
 async def failed(*args,**kwargs):
  if failure=='provider':raise ServiceError('Fictional provider failure')
  if failure=='cancel':await asyncio.sleep(30)
  output,meta=await original(*args,**kwargs)
  if failure=='invalid-reference':output['references']=[{'source_id':'unknown','quote':'Not supplied'}]
  return output,meta
 monkeypatch.setattr(ai,'structured',failed)
 response=client.post('/api/interview-practice/sessions/'+d['session']['id']+'/actions',json=body(d['session'],question_id=q['id'],replace_question_id=q['id']))
 if failure=='cancel':
  assert client.post('/api/tasks/'+response.json()['task_id']+'/cancel',json={}).status_code==200
 result=wait(client,response)
 assert result['status'] in ('failed','cancelled'),result
 current=load(client,d['session']['id'])
 assert current['questions']==d['questions'] and current['session']==d['session']
 if failure=='duplicate':assert 'repeated an earlier question' in result['error']


@pytest.mark.parametrize('protected',['draft','star','voice','guide','examples','material','conversation','guide-question','custom-question'])
def test_cannot_replace_question_with_work_or_non_ai_origin(client,account,model,protected):
 d,q=generated(client,create(client),model);b=body(d['session'],question_id=q['id'],replace_question_id=q['id'])
 if protected=='draft':b['answer']='An unsent typed answer.'
 elif protected=='star':b['star']={'Action':'An unsent planning draft.'}
 elif protected in ('guide-question','custom-question'):
  db.save(account['id'],'interview_question',{**q['data'],'origin':'guide' if protected=='guide-question' else 'custom'},q['id'])
 elif protected=='conversation':db.save(account['id'],'interview_message',{'session_id':d['session']['id'],'role':'user','content':'Discuss this question.'})
 else:
  kind={'voice':'interview_voice','material':'interview_material'}.get(protected,'interview_attempt')
  db.save(account['id'],kind,{'session_id':d['session']['id'],'question_id':q['id'],'operation':protected})
 response=client.post('/api/interview-practice/sessions/'+d['session']['id']+'/actions',json=b)
 assert response.status_code in (409,422),response.text
 assert len(model)==1 and db.get(account['id'],q['id'])


def test_add_question_keeps_existing_answers_and_history(client,account,model,monkeypatch):
 d,q=generated(client,create(client),model)
 review=wait(client,client.post('/api/interview-practice/sessions/'+d['session']['id']+'/actions',json=body(d['session'],'review',question_id=q['id'],answer='I checked the inputs and documented the result.')))
 assert review['status']=='completed';d=load(client,d['session']['id']);change_question(monkeypatch)
 result=wait(client,client.post('/api/interview-practice/sessions/'+d['session']['id']+'/actions',json=body(d['session'],question_id=q['id'])))
 assert result['status']=='completed'
 current=load(client,d['session']['id'])
 assert len(current['questions'])==2 and current['attempts']==d['attempts']


def test_recent_history_is_owned_same_type_and_includes_legacy_star(client,account,model,monkeypatch):
 original=create(client,kind='star');db.save(account['id'],'interview_question',{'session_id':original['id'],'question':'OWNED_LEGACY_STAR','topic':'Teamwork'})
 other_kind=create(client,kind='coding');db.save(account['id'],'interview_question',{'session_id':other_kind['id'],'question':'CODING_EXCLUDED','topic':'Other'})
 another=create(client);q=db.save(account['id'],'interview_question',{'session_id':another['id'],'origin':'ai','question':'OWNED_OTHER_SESSION','topic':'Leadership'})
 target=create(client)
 foreign=client.post('/api/auth/register',json={'username':'otherowner','password':'fictional-other-password'}).json()
 foreign_session=db.save(foreign['id'],'interview_session',{'kind':'behavioral'})
 foreign_q=db.save(foreign['id'],'interview_question',{'session_id':foreign_session['id'],'question':'FOREIGN_EXCLUDED','topic':'Other'})
 login=client.post('/api/auth/login',json={'username':'student','password':'fictional-test-password'}).json();client.headers['X-CSRF-Token']=login['csrf']
 result=wait(client,client.post('/api/interview-practice/sessions/'+target['id']+'/actions',json=body(target)))
 assert result['status']=='completed',result
 assert set(model[-1][1]['previous_questions'])=={'OWNED_LEGACY_STAR','OWNED_OTHER_SESSION'}
 current=load(client,target['id'])
 for destination in (q,foreign_q):
  response=client.post('/api/interview-practice/sessions/'+target['id']+'/actions',json=body(current['session'],replace_question_id=destination['id']))
  assert response.status_code==404,response.text
 assert len(model)==1
