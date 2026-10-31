"""Subject routing and provider privacy contracts, with fictional data only."""
import asyncio,json
import pytest
from app import coach_research as routing,knowledge_assistant as coach,career_coach,ai,db,config,personalization
from app.network import ServiceError

def action(text):return coach.Action(text=text,request_token='fictional-'+db.uid())
def history(subject='AWS',purpose='company_culture'):
 return [{'data':{'role':'assistant','research_diagnostics':{'subjects':[subject],'purpose':purpose}}}]

def test_exact_aws_question_and_paraphrased_queries_ignore_profile(client,account):
 u=account['id'];db.save(u,'experience',{'title':'PRIVATE_PROFILE_TOPIC Python Data Science','category':'project','confirmed':True})
 brief=routing.brief('Research a company’s culture\n- AWS',['AWS workplace culture employee experiences'],[],u)
 assert brief['subjects']==['AWS'] and brief['purpose']=='company_culture'
 assert 'employee accounts' in brief['topics'][0] and 'Python' not in json.dumps(brief)
 # A paraphrased search phrase is not required to occur verbatim in the question.
 assert routing.brief('Research workplace culture at Example Computing',['Example Computing'],[],u)['subjects']==['Example Computing']

@pytest.mark.parametrize('question,expected',[
 ('What about their work-life balance?',['AWS']),('Can you tell me more?',['AWS']),
 ('Compare Microsoft’s culture instead',['Microsoft']),('What about Oracle?',[]),('What about housing?',[]),
 ('What about my Python project?',[]),('Explain a Python loop',[])])
def test_followups_and_changes(client,account,question,expected):
 assert routing.brief(question,[],history(),account['id'])['subjects']==expected

@pytest.mark.parametrize('question,suggested',[
 ('Research company culture',[]),('What is Apple?',['Apple']),
 ('Research my offer salary 55000',['my offer salary 55000']),
 ('Research Alice Example',['Alice Example']),('Research citizenship visa status',['citizenship visa status'])])
def test_ambiguity_and_private_queries_require_clarification(client,account,question,suggested):
 db.update_settings(account['id'],{'name':'Alice Example'})
 assert routing.brief(question,suggested,[],account['id'])['clarification']

def test_relevance_requires_subject_and_culture(client,account):
 brief=routing.brief('Research company culture\n- AWS',[],[],account['id'])
 for text in ['Python learning and education','Google Cloud data engineering certification','AWS SDK API documentation']:
  assert not routing.relevant({'title':'Documentation','text':text},brief)
 for text in ['AWS employees describe mentoring.','Amazon Web Services workplace culture and workload.']:
  assert routing.relevant({'title':'Company report','text':text},brief)

@pytest.mark.parametrize('unavailable,irrelevant',[(False,False),(False,True),(True,False)])
def test_provider_query_is_public_balanced_bounded_and_status_accurate(client,account,monkeypatch,unavailable,irrelevant):
 u=account['id'];monkeypatch.setattr(config,'ENABLE_WEB_SEARCH',True);wires=[];fetches=[];model_payloads=[]
 db.save(u,'experience',{'title':'PRIVATE_PYTHON_TOPIC','category':'project','description':'Work Styles PRIVATE_WORK_STYLE', 'confirmed':True})
 db.save(u,'private_profile',{'religion':'PRIVATE_DISCLOSURE'})
 async def provider(wire,**kw):
  wires.append(wire);assert kw['retry_allowed'] is False
  assert wire['max_tool_calls']==4 and wire['tool_choice']=='required'
  public=json.loads(wire['input']);assert public['public_subjects']==['AWS']
  assert all(v not in json.dumps(wire) for v in ('PRIVATE_PYTHON_TOPIC','PRIVATE_WORK_STYLE','PRIVATE_DISCLOSURE','Fictional Setup University'))
  assert all(v in wire['instructions'] for v in ('independent reporting','employee accounts','self-selected'))
  if unavailable:raise ServiceError('Simulated unavailable provider')
  return {'output':[{'type':'web_search_call'},{'content':[{'annotations':[{'type':'url_citation','url':'https://example.org/'+str(i)} for i in range(8)]}]}]}
 async def fetch(url,limit):
  fetches.append(url);text=('Python documentation for learning data science. '*20 if irrelevant else 'AWS workplace culture: employees describe mentoring and workload. '*20)
  return {'url':url,'status':200,'content_type':'text/html','content':'<html><title>Research page</title><body>'+text+'</body></html>'}
 async def structured(schema,payload,*a,**kw):
  model_payloads.append(payload.copy());assert 'natural paragraphs' in kw['instructions']
  assert 'PRIVATE_DISCLOSURE' not in json.dumps(payload)
  assert len(payload['source_catalog'])<=18 and sum(len(s['text']) for s in payload['source_catalog'])<=26000
  web=[s for s in payload['source_catalog'] if s['kind']=='web']
  return {'answer':'Research is unavailable.' if unavailable or irrelevant else 'AWS culture varies by team. Employee accounts describe individual experiences.',
   'needs_research':not bool(payload.get('research_diagnostics')),'research_subjects':['AWS'],
   'references':[{'source_id':web[0]['source_id'],'quote':web[0]['text'][:90]}] if web else []},{'model':'simulated'}
 monkeypatch.setattr(ai,'call_api',provider);monkeypatch.setattr(ai,'structured',structured);monkeypatch.setattr(career_coach,'public_fetch',fetch)
 result=asyncio.run(coach.execute(u,'new',action('Research a company’s culture\n- AWS')))
 data=result['messages'][-1]['data'];assert len(wires)==1 and len(model_payloads)==2 and len(fetches)<=6
 assert data['research_diagnostics']['outcome']==('unavailable' if unavailable or irrelevant else 'relevant_sources')
 assert all(s['kind']!='web' for s in data['source_snapshot']) if unavailable or irrelevant else any(s['kind']=='web' for s in data['source_snapshot'])
 # Other accounts cannot see the conversation, public research records or messages.
 assert not db.get('foreign-account',result['chat']['id'],'assistant_chat')
 assert not db.list_entities('foreign-account','assistant_research')


def test_ambiguous_research_has_no_external_call_and_does_not_leak_old_subject(client,account,monkeypatch):
 async def model(*a,**k):return {'answer':'I will research','needs_research':True,'research_topics':['Private Profile employer']},{'model':'simulated'}
 async def forbidden(*a,**k):raise AssertionError('Ambiguous subject must not search')
 monkeypatch.setattr(ai,'structured',model);monkeypatch.setattr(career_coach,'research',forbidden)
 result=asyncio.run(coach.execute(account['id'],'new',action('Research a company’s culture')))
 assert result['messages'][-1]['data']['research_diagnostics']['outcome']=='clarification'


def test_catalog_interleaves_and_budgets_without_duplicates():
 chunks=[{'chunk_id':str(i),'title':'AWS culture','url':'https://example.org/'+str(i//6),'text':'AWS employees mentoring '+('x'*1700),'checked_at':'2026-10-30'} for i in range(18)]
 record={'id':'research','updated_at':'now','data':{'chunks':chunks}}
 sources=routing.catalog_sources(record,{'subjects':['AWS'],'purpose':'company_culture'})
 assert len({s['url'] for s in sources[:3]})==3
 result=routing.budget(sources+sources+[{'source_id':'pin','record_id':'pin','kind':'reviewed_profile','text':'x'*1800}],['pin'])
 assert result[0]['record_id']=='pin' and len(result)<=18 and sum(len(s['text']) for s in result)<=26000
 assert len(result)==len({s['source_id'] for s in result})

def test_followup_preserves_company_but_updates_question_purpose(client,account):
 brief=routing.brief('What about their certifications?',[],history(),account['id'])
 assert brief['subjects']==['AWS'] and brief['purpose']=='certification'
 assert 'exam' in brief['topics'][0] and 'workplace' not in brief['topics'][0]


def test_legacy_followup_uses_user_subject_not_wrong_saved_research(client,account):
 old=[{'data':{'role':'user','content':'Research a company’s culture\n- AWS'}},{'data':{'role':'assistant','content':'Data Science topics', 'source_snapshot':[{'text':'PRIVATE_PROFILE_EMPLOYER'}]}}]
 brief=routing.brief('What about their workload?',[],old,account['id'])
 assert brief['subjects']==['AWS'] and 'Data Science' not in json.dumps(brief)


def test_model_detected_ambiguous_public_name_does_not_search(client,account,monkeypatch):
 async def model(*a,**k):return {'answer':'Do you mean Epic Systems or Epic Games?', 'research_clarification':True,'needs_research':False,'research_subjects':['Epic']},{'model':'simulated'}
 async def forbidden(*a,**k):raise AssertionError('Clarify before public research')
 monkeypatch.setattr(ai,'structured',model);monkeypatch.setattr(career_coach,'research',forbidden)
 result=asyncio.run(coach.execute(account['id'],'new',action('Research Epic workplace culture')))
 assert result['messages'][-1]['data']['research_diagnostics']['outcome']=='clarification'
 assert 'Epic Systems or Epic Games' in result['messages'][-1]['data']['content']


def test_personal_management_question_does_not_trigger_public_search(client,account,monkeypatch):
 async def model(*a,**k):return {'answer':'Your reviewed summary describes preferences, not a fixed ability.','references':[]},{'model':'simulated'}
 async def forbidden(*a,**k):raise AssertionError('Personal guidance needs no public search')
 monkeypatch.setattr(ai,'structured',model);monkeypatch.setattr(career_coach,'research',forbidden)
 result=asyncio.run(coach.execute(account['id'],'new',action('Explain my management style.')))
 assert not result['messages'][-1]['data']['research_used']
