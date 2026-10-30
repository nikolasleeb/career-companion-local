import json
import pytest
from app import ai,db,credentials,interview_practice as practice
from test_interview_practice import create,load,body,wait

def coaching(**changes):
 return {'summary':'A saved response.','strengths':['A specific contribution.'],'improvements':['Add a supported outcome.'],'star':[],'profile_connections':['Your reviewed project is relevant.'],'claims_to_clarify':[],'follow_up':'What changed?',**changes}

@pytest.fixture
def example_model(account,monkeypatch):
 credentials.save(account['id'],'sk-fictional-examples');calls=[]
 db.save(account['id'],'experience',{'category':'project','title':'Reviewed fictional scheduling project','description':'Built a scheduling tool.','confirmed':True})
 db.save(account['id'],'experience',{'category':'project','title':'DRAFT_SECRET_EXCLUDED','confirmed':False})
 async def model(schema,payload,*args,**kwargs):
  calls.append((schema,payload,kwargs));assert kwargs['retry_allowed'] is False
  if schema is practice.ExampleGeneration:
   assert 'answer' not in payload and 'star_draft' not in payload
   assert 'DRAFT_SECRET_EXCLUDED' not in json.dumps(payload)
   profiles=[s for s in payload['source_catalog'] if s['kind']=='profile'];source=profiles[0] if profiles else None
   return {'structure_label':'Introduction: present, experience, direction' if 'introduction' in payload['question']['question'].lower() else 'STAR','fictional_answer':'I coordinated a fictional campus event. I clarified roles, changed the schedule and checked the result with the team. We delivered the event and documented one improvement.','why_it_works':['It explains an individual action and a concrete outcome.'],'profile_draft':'My reviewed project gives me a starting point. [Add the exact problem.] I [describe your action]. [Add a supported outcome.]' if source else 'INVENTED_PERSONAL_FACT','missing_details':['The exact problem and your action.','A supported outcome.'] if source else [],'follow_up_questions':['What did you personally change?'],'references':[{'source_id':source['source_id'],'quote':source['text'][:80]}] if source else []},{'model':'simulated-examples'}
  if schema is practice.Discussion:
   assert len(payload['recent_feedback'])==1 and len(payload['preparation_guidance'])==1 and len(payload['illustrative_examples'])==1
   assert 'not submitted answers' in payload['illustrative_examples'][0]['label']
   return {'answer':'The fictional example is teaching material. Use your own facts.','references':[]},{'model':'simulated-discussion'}
  return coaching(reviewer_takeaway='A grounded interpretation.',star=[{'part':p,'guidance':'Recall your '+p} for p in practice.PARTS] if payload['answer_structure_guidance']['use_star'] else [],useful_details=[{'title':'Candidate','user_quote':'I coordinated a fictional campus event.','text':'A generated statement must not enter Profile.'}]),{'model':'simulated-coaching'}
 monkeypatch.setattr(ai,'structured',model);return calls

@pytest.mark.parametrize('kind,qid',[('behavioral','behavioral-teamwork'),('star','behavioral-teamwork'),('behavioral','behavioral-introduction')])
def test_examples_are_explicit_read_only_and_follow_the_question(client,account,example_model,kind,qid):
 if qid=='behavioral-introduction':qid=next(q['id'] for g in practice.interview_guides.catalog()['guides'] if g['id']=='behavioral' for q in g['questions'] if q['theme']=='Introduction')
 s=create(client,kind=kind,guide_question_id=qid);d=load(client,s['id']);before=db.list_entities(account['id'],'experience')
 assert not example_model and not d['attempts']
 r=wait(client,client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=body(s,'examples',question_id=d['questions'][0]['id'])));assert r['status']=='completed',r
 row=load(client,s['id'])['attempts'][0];f=row['data']['feedback'];examples=f['example_answers']
 assert row['data']['operation']=='examples' and row['data']['answer']=='' and not row['data']['star'] and not row['data']['voice_id']
 assert f['reviewer_takeaway']=='' and f['useful_details']==[] and examples['fictional_answer'] and '[' in examples['profile_draft']
 assert len(example_model)==1 and example_model[0][0] is practice.ExampleGeneration
 assert db.list_entities(account['id'],'experience')==before
 assert client.post('/api/interview-practice/attempts/'+row['id']+'/supporting-details',json={'expected_updated_at':row['updated_at'],'candidate':0,'title':'Unsafe example','text':'This is not personal evidence.','reviewed':True}).status_code==422
 backup=client.get('/api/account/export').json();assert client.post('/api/account/import',files={'file':('examples.json',json.dumps(backup).encode(),'application/json')}).status_code==200
 assert practice.Coaching.model_validate(coaching()).example_answers is None

@pytest.mark.parametrize('kind',['coding','case','domain','presentation','other'])
def test_other_types_cannot_request_examples(client,account,example_model,kind):
 s=create(client,kind=kind);d=client.post('/api/interview-practice/sessions/'+s['id']+'/questions',json={'question':'A fictional practice question.','expected_updated_at':s['updated_at']}).json()
 assert client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=body(d['session'],'examples',question_id=d['questions'][0]['id'])).status_code==422
 assert not example_model and not load(client,s['id'])['attempts']

def test_empty_profile_uses_placeholders_and_never_invents_personal_facts(client,account,example_model):
 with db.connect() as c:c.execute("DELETE FROM entities WHERE user_id=? AND kind='experience'",(account['id'],))
 s=create(client,guide_question_id='behavioral-teamwork');qid=load(client,s['id'])['questions'][0]['id']
 r=wait(client,client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=body(s,'examples',question_id=qid)));assert r['status']=='completed',r
 f=load(client,s['id'])['attempts'][0]['data']['feedback'];assert 'INVENTED_PERSONAL_FACT' not in f['example_answers']['profile_draft'] and f['example_answers']['missing_details'] and not f['references']

def test_guidance_reviews_examples_and_conversation_keep_distinct_provenance(client,account,example_model):
 s=create(client,guide_question_id='behavioral-teamwork');d=load(client,s['id']);qid=d['questions'][0]['id']
 for operation in ('review','guide','examples','guide'):
  values={'answer':'I changed a real plan and checked the outcome.'} if operation=='review' else {}
  r=wait(client,client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=body(d['session'],operation,question_id=qid,**values)));assert r['status']=='completed',r;d=load(client,s['id'])
  if operation=='review':review=d['attempts'][0]
 assert load(client,s['id'])['attempts'][0]==review
 assert d['attempts'][1]['data']['feedback']['strengths']==[]
 assert d['attempts'][1]['data']['feedback']['reviewer_takeaway']=='' and d['attempts'][1]['data']['feedback']['useful_details']==[]
 assert wait(client,client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=body(d['session'],'message',text='Explain how to apply the example.')))['status']=='completed'

def test_reject_drafts_foreign_questions_and_bad_citations_without_losing_results(client,account,example_model,monkeypatch):
 s=create(client,guide_question_id='behavioral-teamwork');d=load(client,s['id']);qid=d['questions'][0]['id']
 for values in ({'answer':'Do not send this unsent draft.'},{'star':{'Action':'My planning draft'}},{'voice_id':'private-voice'}):
  assert client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=body(s,'examples',question_id=qid,**values)).status_code==422
 other=create(client,guide_question_id='behavioral-teamwork');foreign=load(client,other['id'])['questions'][0]['id']
 assert client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=body(s,'examples',question_id=foreign)).status_code==404
 assert not example_model
 r=wait(client,client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=body(s,'examples',question_id=qid)));assert r['status']=='completed';d=load(client,s['id']);before=d['attempts']
 original=ai.structured
 async def bad(*args,**kwargs):
  result,meta=await original(*args,**kwargs);result['references']=[{'source_id':'invented-source','quote':'Unsupported personal fact.'}];return result,meta
 monkeypatch.setattr(ai,'structured',bad)
 r=wait(client,client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=body(d['session'],'examples',question_id=qid)));assert r['status']=='failed'
 assert load(client,s['id'])['attempts']==before

def test_copied_example_text_is_not_a_supporting_detail(client,account,example_model):
 s=create(client,guide_question_id='behavioral-teamwork');d=load(client,s['id']);qid=d['questions'][0]['id']
 assert wait(client,client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=body(s,'examples',question_id=qid)))['status']=='completed';d=load(client,s['id'])
 quote='I coordinated a fictional campus event.'
 assert wait(client,client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=body(d['session'],'review',question_id=qid,answer=quote)))['status']=='completed'
 row=load(client,s['id'])['attempts'][-1];assert row['data']['feedback']['useful_details']==[]
 row['data']['feedback']['useful_details']=[{'title':'Copied teaching text','user_quote':quote,'text':quote}];row=db.save(account['id'],'interview_attempt',row['data'],row['id'])
 assert client.post('/api/interview-practice/attempts/'+row['id']+'/supporting-details',json={'expected_updated_at':row['updated_at'],'candidate':0,'title':'Not evidence','text':quote,'reviewed':True}).status_code==422
