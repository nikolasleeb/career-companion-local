import json
import pytest
from app import db,ai,credentials,interview_practice as practice,interview_guides
from test_interview_practice import create,load,body,wait

@pytest.mark.parametrize('kind,qid',[('behavioral','behavioral-teamwork'),('star','behavioral-teamwork'),('case','case-profitability')])
def test_attach_guide_to_existing_empty_session_is_free_atomic_and_owned(client,account,monkeypatch,kind,qid):
 guide=next(g for g in interview_guides.catalog()['guides'] if g['id']==('behavioral' if kind=='star' else kind));qid=guide['questions'][0]['id']
 async def forbidden(*a,**k):raise AssertionError('Guide selection must be free')
 monkeypatch.setattr(ai,'structured',forbidden)
 s=create(client,kind=kind,title='Existing fictional session',notes='Keep existing notes')
 path='/api/interview-practice/sessions/'+s['id']+'/questions'
 for bad in [{'guide_question_id':'missing'},{'question':'Valid manual question','guide_question_id':qid},{}, {'question':'x'}]:
  r=client.post(path,json={**bad,'expected_updated_at':s['updated_at']});assert r.status_code==422
  assert not load(client,s['id'])['questions'] and len(db.list_entities(account['id'],'interview_session'))==1
 r=client.post(path,json={'guide_question_id':qid,'expected_updated_at':s['updated_at']});assert r.status_code==200,r.text
 detail=r.json();assert detail['session']['id']==s['id'] and detail['session']['data']['kind']==kind
 assert detail['session']['data']['notes']=='Keep existing notes' and len(detail['questions'])==1
 assert detail['questions'][0]['data']['origin']=='guide'
 assert detail['questions'][0]['data']['guide_provenance']['guide_id']==guide['id']
 assert client.post(path,json={'guide_question_id':qid,'expected_updated_at':s['updated_at']}).status_code==409
 assert not db.list_entities(account['id'],'usage_event')
 backup=client.get('/api/account/export').json();assert client.post('/api/account/import',files={'file':('fictional.json',json.dumps(backup).encode(),'application/json')}).status_code==200
 client.post('/api/auth/logout');client.headers.pop('X-CSRF-Token',None)
 other=client.post('/api/auth/register',json={'username':'other-cleanup','password':'fictional-test-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
 assert client.post(path,json={'guide_question_id':qid,'expected_updated_at':detail['session']['updated_at']}).status_code==404

@pytest.mark.parametrize('kind,theme,use_star',[('behavioral','Introduction',False),('behavioral','Teamwork',True),('case',None,False),('domain',None,False),('presentation',None,False),('other',None,False),('coding',None,False)])
def test_type_appropriate_guidance_and_grounded_content_review(client,account,monkeypatch,kind,theme,use_star):
 credentials.save(account['id'],'sk-fictional-cleanup')
 if kind=='coding':
  s=create(client,kind=kind);d=client.post('/api/interview-practice/sessions/'+s['id']+'/questions',json={'question':'Explain an algorithm to sum an integer list.','expected_updated_at':s['updated_at']}).json()
 else:
  guide=next(g for g in interview_guides.catalog()['guides'] if g['id']==kind)
  selected=next((q for q in guide['questions'] if q['theme']==theme),guide['questions'][0])
  s=create(client,kind=kind,guide_question_id=selected['id']);d=load(client,s['id'])
 qid=d['questions'][0]['id'];calls=[]
 async def model(schema,payload,*args,**kwargs):
  calls.append(payload);assert kwargs['retry_allowed'] is False
  assert payload['answer_structure_guidance']['use_star']==use_star
  return {'reviewer_takeaway':'The response describes a decision, but the result needs an example.','summary':'Explain your own contribution.','strengths':[],'improvements':['Give the outcome.'],'star':[{'part':p,'guidance':'Explain '+p} for p in practice.PARTS] if use_star else [],'profile_connections':[],'claims_to_clarify':[],'follow_up':'What changed?'},{'model':'fictional'}
 monkeypatch.setattr(ai,'structured',model)
 r=wait(client,client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=body(d['session'],'guide',question_id=qid)));assert r['status']=='completed',r
 d=load(client,s['id']);assert d['attempts'][0]['data']['feedback']['reviewer_takeaway']
 r=wait(client,client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=body(d['session'],'review',question_id=qid,answer='I changed a fictional project plan and checked the outcome.')));assert r['status']=='completed',r
 assert 'regardless of whether STAR fields were used' in calls[-1]['task']
 assert 'grounding every observation in the actual words or code' in calls[-1]['task']
 backup=client.get('/api/account/export').json();assert client.post('/api/account/import',files={'file':('feedback.json',json.dumps(backup).encode(),'application/json')}).status_code==200
 assert practice.Coaching.model_validate({'summary':'Older saved feedback','strengths':[],'improvements':[],'star':[],'profile_connections':[],'claims_to_clarify':[],'follow_up':''}).reviewer_takeaway==''
