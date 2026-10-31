"""Fictional account and simulated provider contracts for shared writing sources."""
import asyncio,json
import pytest
from fastapi.testclient import TestClient
from app import ai,db,guidance,knowledge_assistant as coach,assistant_context,personalization,career_coach

def action(text):return coach.Action(text=text,request_token='fictional-'+db.uid())
def result(payload):
 sources=[s for s in payload['source_catalog'] if s['kind']=='writing_guidance']
 return {'answer':'Use clear, specific writing supported by your experience.','references':[{'source_id':sources[0]['source_id'],'quote':sources[0]['text'][:90]}] if sources else []},{'model':'simulated'}

@pytest.mark.parametrize('question',['How can I improve my resume bullets?','Why do cover-letter sources disagree about length?','How should I format my CV?','Help improve my résumé.'])
def test_general_coach_cites_bundled_writing_without_research(client,account,monkeypatch,question):
 calls=[]
 async def model(schema,payload,*a,**kw):
  calls.append(payload);sources=payload['source_catalog'];assert any(s['kind']=='writing_guidance' for s in sources)
  assert len(sources)<=18 and sum(len(s['text']) for s in sources)<=26000
  assert len({s['source_id'] for s in sources})==len(sources)
  for s in sources:
   if s['kind']=='writing_guidance':assert all(s[k] for k in ('audience','publisher','reviewed_at','revision','url','content_kind'))
  return result(payload)
 async def forbidden(*a,**kw):raise AssertionError('No external research needed for these bundled-source questions')
 monkeypatch.setattr(ai,'structured',model);monkeypatch.setattr(career_coach,'research',forbidden)
 r=asyncio.run(coach.execute(account['id'],'new',action(question)))
 assert len(calls)==1 and r['chat']['data'].get('context_scope','workspace')=='workspace'
 assert r['messages'][-1]['data']['reply']['references'][0]['kind']=='writing_guidance'
 assert not r['messages'][-1]['data']['research_used']

@pytest.mark.parametrize('question',['Explain the Python loop in my project.','Explore skills for my goals','What about job search?','Can I learn SQL next?'])
def test_unrelated_questions_do_not_receive_writing(client,account,monkeypatch,question):
 async def model(schema,payload,*a,**kw):
  assert not any(s['kind']=='writing_guidance' for s in payload['source_catalog']);return result(payload)
 monkeypatch.setattr(ai,'structured',model)
 asyncio.run(coach.execute(account['id'],'new',action(question)))

def test_followup_scope_changes_and_account_permissions(client,account,monkeypatch):
 u=account['id'];r=db.save(u,'experience',{'category':'project','title':'Fictional SQL work','description':'PRIVATE_CONFIRMED_EXPERIENCE','confirmed':True})
 # Another account's source and unconfirmed drafts must stay unavailable.
 foreign=TestClient(client.app,base_url='http://127.0.0.1').post('/api/auth/register',json={'username':'foreign-writing-account','password':'fictional-foreign-password'}).json()
 db.save(foreign['id'],'experience',{'category':'project','title':'FOREIGN_SECRET','confirmed':True})
 db.save(u,'experience',{'category':'project','title':'UNREVIEWED_SECRET','confirmed':False})
 db.save(u,'private_profile',{'religion':'PRIVATE_DISCLOSURE_SECRET'})
 calls=[]
 async def model(schema,payload,*a,**kw):
  calls.append(payload);wire=json.dumps(payload)
  assert all(v not in wire for v in ('FOREIGN_SECRET','UNREVIEWED_SECRET','PRIVATE_DISCLOSURE_SECRET'))
  return result(payload)
 monkeypatch.setattr(ai,'structured',model)
 first=asyncio.run(coach.execute(u,'new',action('How can I improve my resume?')));id=first['chat']['id']
 asyncio.run(coach.execute(u,id,action('What about the length?')))
 assert any(s['kind']=='writing_guidance' for s in calls[-1]['source_catalog'])
 asyncio.run(coach.execute(u,id,action('What about job search?')))
 assert not any(s['kind']=='writing_guidance' for s in calls[-1]['source_catalog'])
 asyncio.run(coach.execute(u,id,action('Make it shorter.')))
 assert not any(s['kind']=='writing_guidance' for s in calls[-1]['source_catalog'])
 # Explicitly disabled automatic personal context still allows public guidance.
 state=personalization.read(u)
 client.put('/api/profile/personalization',json={'enabled':False,'expected_revision':state['revision']})
 asyncio.run(coach.execute(u,'new',action('How should I write a cover letter?')))
 assert any(s['kind']=='writing_guidance' for s in calls[-1]['source_catalog'])
 assert not any(s['record_id']==r['id'] for s in calls[-1]['source_catalog'])

def test_budget_pins_deduplication_and_bad_citations(client,account):
 sources=[{'source_id':str(i),'record_id':'pin' if i==0 else str(i),'kind':'reviewed_profile','text':'x'*1800} for i in range(18)]
 rows=guidance.with_workspace_sources(sources,'Improve my resume',pinned=['pin'])
 assert rows[0]['record_id']=='pin' and len(rows)<=18 and sum(len(s['text']) for s in rows)<=26000
 assert len({s['source_id'] for s in rows})==len(rows)
 with pytest.raises(Exception,match='citation'):
  coach.validate_reply({'answer':'Unsupported','references':[{'source_id':rows[1]['source_id'],'quote':'INVENTED QUOTE'}]},rows)

def test_writing_scope_rejects_uncovered_response_with_fake_evidence(client,account,monkeypatch):
 async def model(schema,payload,*a,**kw):return {'answer':'Outside writing scope.','coverage':'not_covered','references':[]},{'model':'simulated'}
 monkeypatch.setattr(ai,'structured',model)
 r=asyncio.run(coach.execute(account['id'],'new',coach.Action(text='What is the weather?',context_scope='writing',request_token='fictional-outside-scope')))
 assert r['messages'][-1]['data']['reply']['coverage']=='not_covered'
