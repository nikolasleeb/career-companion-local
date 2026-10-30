"""Guide browsing is deterministic; starter questions preserve session boundaries."""
import copy,json,sqlite3
import pytest
from app import ai,db,interview_guides,skills

def forbid_ai(monkeypatch):
 async def forbidden(*a,**k):raise AssertionError('Guide actions must not request AI')
 monkeypatch.setattr(ai,'structured',forbidden)
 monkeypatch.setattr(ai,'call_api',forbidden)

def test_catalog_authenticated_complete_and_no_usage(client,account,monkeypatch):
 forbid_ai(monkeypatch)
 before=db.list_entities(account['id'],'usage_event');sessions=db.list_entities(account['id'],'interview_session')
 r=client.get('/api/interview-practice/guides');assert r.status_code==200
 data=r.json();assert data['reviewed_at'] and data['version']
 assert {g['id']:len(g['questions']) for g in data['guides']}=={'behavioral':10,'case':6,'domain':7,'presentation':6,'other':4}
 sources={s['id'] for s in data['sources']};ids=[]
 for source in data['sources']:assert source['url'].startswith('https://') and source['supports'] and source['publisher']
 for g in data['guides']:
  assert len(g['blocks'])==3 and set(g['source_ids'])<=sources
  for q in g['questions']:
   ids.append(q['id']);assert q['prompt'] and q['structure'] and q['look_for'] and q['mistakes'] and set(q['source_ids'])<=sources
 assert len(ids)==len(set(ids))==33
 domain=next(g for g in data['guides'] if g['id']=='domain')
 assert {q['field'] for q in domain['questions']}==set(skills.FIELDS)
 assert all(q['prompt'].startswith('Fictional scenario:') for q in domain['questions'])
 assert db.list_entities(account['id'],'usage_event')==before
 assert db.list_entities(account['id'],'interview_session')==sessions
 client.cookies.clear();assert client.get('/api/interview-practice/guides').status_code==401

def test_every_guide_question_creates_one_ready_session_without_ai(client,account,monkeypatch):
 forbid_ai(monkeypatch);profile=db.list_entities(account['id'],'experience')
 for guide in interview_guides.catalog()['guides']:
  for q in guide['questions']:
   r=client.post('/api/interview-practice/sessions',json={'kind':guide['id'],'guide_question_id':q['id']});assert r.status_code==200,r.text
   s=r.json();detail=client.get('/api/interview-practice/sessions/'+s['id']).json()
   assert len(detail['questions'])==1 and detail['attempts']==[]
   saved=detail['questions'][0]['data'];assert saved['question']==q['prompt'] and saved['origin']=='guide'
   assert saved['references']==[] and not saved.get('source_snapshot')
   assert saved['guide_provenance']=={'guide_id':guide['id'],'guide_title':guide['title'],'question_id':q['id'],'catalog_version':interview_guides.catalog()['version'],'reviewed_at':interview_guides.catalog()['reviewed_at'],'source_ids':q['source_ids']}
   assert s['data']['use_work_styles'] is False
 assert db.list_entities(account['id'],'usage_event')==[]
 assert db.list_entities(account['id'],'experience')==profile

@pytest.mark.parametrize('kind,id',[('behavioral','missing-question'),('coding','behavioral-teamwork'),('star','behavioral-teamwork'),('case','behavioral-teamwork')])
def test_invalid_starter_creates_nothing(client,account,kind,id):
 before=db.list_entities(account['id'],'interview_session');questions=db.list_entities(account['id'],'interview_question')
 r=client.post('/api/interview-practice/sessions',json={'kind':kind,'guide_question_id':id});assert r.status_code==422
 assert db.list_entities(account['id'],'interview_session')==before and db.list_entities(account['id'],'interview_question')==questions

def test_starter_insert_failure_rolls_back_session(client,account,monkeypatch):
 old=db.save(account['id'],'interview_session',{'title':'Existing session'})
 ids=iter(['failed-starter-session',old['id']]);monkeypatch.setattr(db,'uid',lambda:next(ids))
 with pytest.raises(sqlite3.IntegrityError):client.post('/api/interview-practice/sessions',json={'kind':'behavioral','guide_question_id':'behavioral-teamwork'})
 assert db.get(account['id'],'failed-starter-session') is None
 assert db.get(account['id'],old['id'])==old

def test_starter_snapshot_restore_deletion_and_account_isolation(client,account,monkeypatch):
 r=client.post('/api/interview-practice/sessions',json={'kind':'behavioral','guide_question_id':'behavioral-teamwork','notes':'Private fictional notes'});assert r.status_code==200
 s=r.json();detail=client.get('/api/interview-practice/sessions/'+s['id']).json();question=detail['questions'][0]
 changed=copy.deepcopy(interview_guides.catalog());changed['guides'][0]['questions'][4]['prompt']='An edited future prompt'
 monkeypatch.setattr(interview_guides,'catalog',lambda:changed)
 assert client.get('/api/interview-practice/sessions/'+s['id']).json()['questions'][0]==question
 backup=client.get('/api/account/export').json()
 restored=client.post('/api/account/import',files={'file':('guides.json',json.dumps(backup).encode(),'application/json')});assert restored.status_code==200,restored.text
 rows=client.get('/api/interview-practice/sessions').json()['sessions'];assert len(rows)==2
 imported=next(row for row in rows if row['id']!=s['id'])
 assert client.get('/api/interview-practice/sessions/'+imported['id']).json()['questions'][0]['data']['guide_provenance']==question['data']['guide_provenance']
 profile=db.list_entities(account['id'],'experience')
 assert client.delete('/api/interview-practice/sessions/'+imported['id']).status_code==200
 assert db.list_entities(account['id'],'experience')==profile
 client.post('/api/auth/logout');client.headers.pop('X-CSRF-Token',None)
 other=client.post('/api/auth/register',json={'username':'otherguide','password':'fictional-test-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
 assert client.get('/api/interview-practice/guides').status_code==200
 assert client.get('/api/interview-practice/sessions').json()['sessions']==[]
 assert client.get('/api/interview-practice/sessions/'+s['id']).status_code==404
 assert client.delete('/api/interview-practice/sessions/'+s['id']).status_code==404
 assert db.get(account['id'],s['id'])==s
