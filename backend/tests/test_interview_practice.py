import asyncio,io,json,time
import pytest
from reportlab.pdfgen import canvas
from app import db,ai,credentials,config,interview_practice as practice,career_coach

def pdf(text='Company interview preparation: describe your individual contribution, check assumptions and explain the result. Discuss tradeoffs and what you learned.'):
 out=io.BytesIO();c=canvas.Canvas(out);c.drawString(40,740,text);c.save();return out.getvalue()
def create(client,**data):
 r=client.post('/api/interview-practice/sessions',json=data);assert r.status_code==200,r.text;return r.json()
def load(client,id):return client.get('/api/interview-practice/sessions/'+id).json()
def wait(client,r):
 assert r.status_code==200,r.text
 for _ in range(1000):
  value=client.get('/api/tasks/'+r.json()['task_id']).json()
  if value['status'] not in ('queued','running','cancelling'):return value
  time.sleep(.01)
 raise AssertionError('Fictional interview task did not finish')
def body(s,op='question',**values):return {'operation':op,'expected_updated_at':s['updated_at'],'request_token':'fictional-'+db.uid(),**values}
def question(client,s,text='Tell me about a project and your individual contribution.'):
 r=client.post('/api/interview-practice/sessions/'+s['id']+'/questions',json={'question':text,'expected_updated_at':s['updated_at']});assert r.status_code==200,r.text;return r.json()
@pytest.fixture
def model(monkeypatch,account):
 credentials.save(account['id'],'sk-fictional-interview-not-real');calls=[]
 async def structured(schema,payload,mode='economy',**kwargs):
  calls.append((schema,payload,kwargs));source=payload['source_catalog'][0];ref=[{'source_id':source['source_id'],'quote':source['text'][:80]}]
  if schema==practice.Question:return {'question':'Given a list of IDs, return the unique IDs in their original order. Explain your approach.','topic':'Original deduplication exercise','evaluation_focus':['Reasoning','Testing'],'constraints':['0 to 1000 IDs'],'examples':[{'input':'[2, 2, 1]','output':'[2, 1]','explanation':'Keep the first occurrence.'}],'hints':['Think about membership checks.'],'references':ref},{'model':'fictional-interview','generated_at':db.now()}
  assert schema==practice.Coaching
  return {'summary':'Explain your own decisions and distinguish what is supported from what is new.','strengths':['The answer identifies a concrete activity.'],'improvements':['Explain how you checked the result.'],'star':[{'part':part,'guidance':'Describe your real '+part.lower()+'; add missing details yourself.'} for part in practice.PARTS],'profile_connections':['Your reviewed experience offers a possible example.'],'claims_to_clarify':['Clarify which result you personally checked.'],'follow_up':'How did you check your result?','correctness':'This is a conceptual review, not execution.','complexity':'Consider membership-check cost.','edge_cases':['Empty input','Repeated values'],'references':ref},{'model':'fictional-interview','generated_at':db.now()}
 monkeypatch.setattr(ai,'structured',structured);return calls

def test_no_ai_on_creation_upload_history_and_legacy(client,account,monkeypatch):
 async def forbidden(*a,**k):raise AssertionError('No AI for manual work')
 monkeypatch.setattr(ai,'structured',forbidden)
 r=client.post('/api/interview-practice/documents',files={'file':('prep.pdf',pdf(),'application/pdf')});assert r.status_code==200,r.text
 doc=r.json();s=create(client,kind='star',document_ids=[doc['id']]);assert s['data']['code_execution'] is False
 old=db.save(account['id'],'interview',{'job_id':'old','question':'Preserve earlier practice','attempts':[]})
 result=client.get('/api/interview-practice/sessions').json();assert result['legacy'][0]['id']==old['id'];assert len(result['sessions'])==1
 assert client.get('/api/interview-practice/documents/'+doc['id']+'/file').content==pdf() or client.get('/api/interview-practice/documents/'+doc['id']+'/file').content.startswith(b'%PDF-')
 assert client.post('/api/interview-practice/documents',files={'file':('wrong.txt',b'not PDF','text/plain')}).status_code==422
 assert client.post('/api/interview-practice/documents',files={'file':('wrong.pdf',b'not PDF','application/pdf')}).status_code==400
 assert load(client,s['id'])['questions']==[]

def test_generated_question_private_context_deduplication_and_profile_unchanged(client,account,model):
 db.update_settings(account['id'],{'email':'private@example.test','name':'Private Candidate'})
 db.save(account['id'],'work_style',{'text':'PRIVATE_WORK_STYLE'});db.save(account['id'],'career_goals',{'text':'PRIVATE_GOAL'})
 db.save(account['id'],'experience',{'category':'project','title':'DRAFT_SECRET','confirmed':False})
 before=db.list_entities(account['id'],'experience');s=create(client,company='Fictional Employer',role='Analyst');b=body(s)
 r=client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=b);value=wait(client,r);assert value['status']=='completed',value
 repeated=client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=b);assert repeated.json()['task_id']==r.json()['task_id'];assert len(model)==1
 sent=json.dumps(model[0][1]);assert all(secret not in sent for secret in ('private@example.test','Private Candidate','PRIVATE_WORK_STYLE','PRIVATE_GOAL','DRAFT_SECRET'))
 assert model[0][2]['retry_allowed'] is False
 assert db.list_entities(account['id'],'experience')==before
 assert client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json={**b,'focus':'Different'}).status_code==409
 assert len(load(client,s['id'])['questions'])==1

def test_star_guidance_and_attempts_survive_backup(client,account,model):
 doc=client.post('/api/interview-practice/documents',files={'file':('company-prep.pdf',pdf(),'application/pdf')}).json();s=create(client,kind='star',document_ids=[doc['id']]);d=question(client,s);qid=d['questions'][0]['id']
 before=db.settings(account['id'])
 for op in ('guide','review'):
  b=body(d['session'],op,question_id=qid,star={'Situation':'A real course project','Task':'Check the source records','Action':'I reviewed the rows','Result':'I documented findings'})
  r=wait(client,client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=b));assert r['status']=='completed',r;d=load(client,s['id'])
 assert len(d['attempts'])==2 and {p['part'] for p in d['attempts'][0]['data']['feedback']['star']}==set(practice.PARTS)
 assert db.settings(account['id'])==before
 backup=client.get('/api/account/export').json();restored=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')});assert restored.status_code==200,restored.text
 rows=client.get('/api/interview-practice/sessions').json()['sessions'];assert len(rows)==2
 imported=next(r for r in rows if r['id']!=s['id']);saved=load(client,imported['id']);assert len(saved['attempts'])==2
 assert saved['attempts'][0]['data']['question_id']==saved['questions'][0]['id']
 assert saved['session']['data']['document_ids'][0]!=doc['id']
 # An imported displayed citation cannot replace a saved source URL.
 backup=client.get('/api/account/export').json();a=next(r for r in backup['records'] if r['kind']=='interview_attempt');a['data']['feedback']['references'][0]['url']='javascript:alert(1)'
 assert client.post('/api/account/import',files={'file':('bad.json',json.dumps(backup).encode(),'application/json')}).status_code==400

def test_bad_reference_keeps_previous_attempt_and_stale_inputs_make_no_call(client,account,model,monkeypatch):
 s=create(client);d=question(client,s);qid=d['questions'][0]['id'];b=body(d['session'],'review',question_id=qid,answer='I checked the data and documented the results.')
 assert wait(client,client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=b))['status']=='completed'
 assert client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json={**b,'request_token':'new-stale-token'}).status_code==409;assert len(model)==1
 original=ai.structured
 async def bad(*a,**k):
  out,meta=await original(*a,**k);out['references']=[{'source_id':'invented','quote':'Not supplied'}];return out,meta
 monkeypatch.setattr(ai,'structured',bad);d=load(client,s['id']);result=wait(client,client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=body(d['session'],'review',question_id=qid,answer='Another response to the same question.')))
 assert result['status']=='failed' and len(load(client,s['id'])['attempts'])==1

def test_coding_is_reviewed_not_executed(client,account,model,tmp_path):
 s=create(client,kind='coding',language='Python');r=wait(client,client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=body(s)));assert r['status']=='completed',r
 d=load(client,s['id']);code="open("+repr(str(tmp_path/'must-not-exist'))+", 'w').write('NO')"
 r=wait(client,client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=body(d['session'],'review',question_id=d['questions'][0]['id'],answer=code)))
 assert r['status']=='completed',r
 assert not (tmp_path/'must-not-exist').exists();assert load(client,s['id'])['attempts'][0]['data']['code_execution'] is False
 assert model[-1][1]['answer']==code

def test_company_and_job_context_materials_and_isolation(client,account,model):
 job=db.save(account['id'],'job',{'title':'Analyst','company':'Fictional Co','description':'Evaluate SQL data quality.'});app=db.save(account['id'],'application',{'title':'Analyst interview','company':'Fictional Co','job_id':job['id'],'posting_snapshot':job['data'],'status':'interviewing'})
 doc=client.post('/api/interview-practice/documents',files={'file':('prep.pdf',pdf(),'application/pdf')}).json();s=create(client,application_id=app['id'],document_ids=[doc['id']]);assert s['data']['posting_snapshot']==job['data']
 r=wait(client,client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=body(s)));assert r['status']=='completed'
 sent=json.dumps(model[0][1]);assert 'Evaluate SQL data quality.' in sent and 'Company interview preparation' in sent
 other=client.post('/api/auth/register',json={'username':'other-interview','password':'fictional-password-only'}).json();client.headers['X-CSRF-Token']=other['csrf']
 from conftest import onboard_test_account
 onboard_test_account(other)
 assert client.get('/api/interview-practice/sessions/'+s['id']).status_code==404
 assert client.get('/api/interview-practice/documents/'+doc['id']+'/file').status_code==404
 assert client.post('/api/interview-practice/sessions',json={'document_ids':[doc['id']]}).status_code==404
 assert client.get('/api/interview-practice/sessions').json()=={'sessions':[],'legacy':[]}

def test_education_gate_before_provider_work(client,monkeypatch):
 r=client.post('/api/auth/register',json={'username':'not-ready','password':'fictional-password-only'}).json();client.headers['X-CSRF-Token']=r['csrf']
 assert client.post('/api/interview-practice/sessions',json={}).status_code==403
 assert client.get('/api/interview-practice/documents').status_code==403

def test_stop_discards_ai_changes_and_preserves_manual_question(client,account,model,monkeypatch):
 s=create(client);d=question(client,s);entered=[]
 async def slow(*a,**k):entered.append(True);await asyncio.sleep(30);raise AssertionError('Cancelled work must not finish')
 monkeypatch.setattr(ai,'structured',slow);r=client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=body(d['session']));task=r.json()['task_id']
 for _ in range(300):
  if entered:break
  time.sleep(.01)
 assert entered
 cancelled=client.post('/api/tasks/'+task+'/cancel',json={});assert cancelled.status_code==200
 for _ in range(300):
  state=client.get('/api/tasks/'+task).json()
  if state['status']=='cancelled':break
  time.sleep(.01)
 assert state['status']=='cancelled';after=load(client,s['id']);assert after['attempts']==[] and len(after['questions'])==1 and after['session']==d['session']
 with db.connect() as c:assert c.execute('SELECT count(*) FROM cc_task_stage WHERE task_id=?',(task,)).fetchone()[0]==0

def test_research_uses_only_public_topics_and_checked_passages(client,account,model,monkeypatch):
 monkeypatch.setattr(config,'ENABLE_WEB_SEARCH',True);calls=[]
 db.update_settings(account['id'],{'name':'Private Candidate','email':'do-not-send@example.test'})
 async def web(wire,**kwargs):
  calls.append(wire);assert kwargs['retry_allowed'] is False
  return {'model':'fictional','output':[{'content':[{'annotations':[{'type':'url_citation','url':'https://www.microsoft.com/careers/fictional-prep'}]}]}]}
 async def fetch(url,*a,**k):return {'status':200,'url':url,'content_type':'text/html','content':b'<html><title>Official fictional preparation</title><main>Prepare real examples of your own contribution, explain decisions and reflect on what you learned. These are fictional test materials for preparing for an interview, not actual company interview questions.</main></html>'}
 monkeypatch.setattr(ai,'call_api',web);monkeypatch.setattr(career_coach,'public_fetch',fetch)
 s=create(client,company='Fictional Employer',role='Analyst',notes='PRIVATE_PREPARATION_NOTES');r=wait(client,client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=body(s,'research')));assert r['status']=='completed',r
 assert len(calls)==1 and calls[0]['max_tool_calls']==4
 sent=json.dumps(calls[0]);assert all(v not in sent for v in ('Private Candidate','do-not-send@example.test','PRIVATE_PREPARATION_NOTES','Fictional Setup University'))
 d=load(client,s['id']);assert d['research']['data']['status']=='checked' and d['research']['kind']=='interview_research'
 assert db.list_entities(account['id'],'coach_research')==[]
 b=client.get('/api/account/export').json();r=client.post('/api/account/import',files={'file':('backup.json',json.dumps(b).encode(),'application/json')});assert r.status_code==200,r.text

def test_delete_preserves_material_profile_and_other_sessions(client,account,model):
 doc=client.post('/api/interview-practice/documents',files={'file':('prep.pdf',pdf(),'application/pdf')}).json();s=create(client,document_ids=[doc['id']]);other=create(client,document_ids=[doc['id']]);before=db.list_entities(account['id'],'experience')
 d=question(client,s)
 assert client.delete('/api/records/'+doc['id']).status_code==409
 assert client.delete('/api/records/'+s['id']).status_code==409
 assert client.post('/api/documents/'+doc['id']+'/parse').status_code==400
 assert client.delete('/api/interview-practice/sessions/'+s['id']).status_code==200
 assert client.get('/api/interview-practice/sessions/'+s['id']).status_code==404
 assert load(client,other['id'])['session']['id']==other['id']
 assert client.get('/api/interview-practice/documents/'+doc['id']+'/file').status_code==200
 assert db.list_entities(account['id'],'experience')==before

def test_failed_research_keeps_saved_research_and_no_partial_publish(client,account,model,monkeypatch):
 monkeypatch.setattr(config,'ENABLE_WEB_SEARCH',True)
 async def unavailable(*a,**k):return {'model':'fictional','output':[]}
 monkeypatch.setattr(ai,'call_api',unavailable)
 s=create(client,company='Fictional Employer');old=db.save(account['id'],'interview_research',{'chat_id':s['id'],'chunks':[],'status':'old-checked','checked_at':db.now(),'warnings':[]})
 value=wait(client,client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=body(s,'research')))
 assert value['status']=='failed';assert load(client,s['id'])['research']['id']==old['id'];assert load(client,s['id'])['session']==s
