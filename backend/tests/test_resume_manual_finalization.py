"""Explicit manual acceptance of the exact unfinished checkpoint; no extra AI."""
import base64,copy,hashlib,json
import pytest
from app import db,resume_runs as runs,resume_conversation as guided
from app.models import ConversationStart
from test_resume_standard import setup

def failed(setup):
 user,session,behavior,calls,build=setup
 behavior['factual']=True
 state=build();assert not state['current']
 run=state['optimization_run'];assert run['status']=='needs_changes' and run['manual_finalize_available']
 body={'expected_version':state['data']['version'],'reviewed':True,'checkpoint_id':run['id'],'checkpoint_version':run['preview_version'],'incomplete_review_acknowledged':True}
 return user,state,run,body,calls

def test_manual_acceptance_exact_pdf_honest_metadata_idempotency_and_account_export(setup,client):
 user,state,run,body,calls=failed(setup)
 application=client.post('/api/applications/start',json={'job_id':state['data']['job_id']}).json()
 original=copy.deepcopy(runs.read(user,run['id'])['data']);pdf=base64.b64decode(original['preview']['artifacts']['pdf'])
 path='/api/resume-conversations/'+state['id']+'/finalize';count=len(calls)
 result=client.post(path,json=body);assert result.status_code==200,result.text
 final=result.json();revision=final['current'];resume_id=revision['data']['finalized_resume_id'];snapshot=db.get(user,resume_id,'resume')['data']
 assert base64.b64decode(snapshot['artifacts']['pdf'])==pdf
 assert snapshot['optimization']['source_checked'] is False
 assert snapshot['optimization']['review_pending'] is True
 assert snapshot['optimization']['manual_review']['ai_review_completed'] is False
 assert snapshot['optimization']['quality_review']['status']=='unavailable'
 assert not revision['data'].get('review_run_id')
 assert final['optimization_run']['status']=='user_finalized' and not final['optimization_run']['manual_finalize_available']
 assert final['optimization_run']['requests_used']==4 and len(calls)==count
 assert db.get(user,application['id'],'application')['data']['resume_ids']==[resume_id]
 download=client.get('/api/resumes/'+resume_id+'/export/pdf');assert download.status_code==200 and download.content==pdf
 retry=client.post(path,json=body);assert retry.status_code==200 and retry.json()['current']['id']==revision['id']
 assert len(db.list_entities(user,'resume'))==1 and len(calls)==count
 assert runs.read(user,run['id'])['data']['stages']==original['stages']
 # Import strips run authority but keeps the separately saved, honestly labeled document.
 restored=runs.restore_value(runs.read(user,run['id'])['data']);assert restored['restored'] and 'preview' not in restored and 'manual_resume_id' not in restored

@pytest.mark.parametrize('change,code',[
 ({'incomplete_review_acknowledged':False},409),({'reviewed':False},422),({'checkpoint_version':'changed'},409),({'expected_version':99999},409),({'revision_id':'also-selected'},400),({'checkpoint_id':'missing'},404)])
def test_manual_finalize_requires_exact_current_acknowledged_owned_preview(setup,client,change,code):
 user,state,run,body,calls=failed(setup);before=len(calls)
 response=client.post('/api/resume-conversations/'+state['id']+'/finalize',json={**body,**change})
 assert response.status_code==code,response.text
 assert not db.list_entities(user,'resume') and not guided.state(user,state['id'])['current'] and len(calls)==before

@pytest.mark.parametrize('case',['active','imported','latest','cross_conversation','malformed','clipped','overflow'])
def test_manual_finalize_rejects_ineligible_checkpoints(setup,client,case):
 user,state,run,body,calls=failed(setup);row=runs.read(user,run['id']);value=row['data']
 if case=='active':
  stamp=db.now()
  with db.connect() as c:c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',(db.uid(),user,'resume_guided','running',json.dumps({'_task_inputs':{'conversation_id':state['id']}}),None,stamp,stamp))
 elif case=='imported':value['restored']=True
 elif case=='latest':db.save(user,'resume_run',{**value,'created_at':db.now()})
 elif case=='cross_conversation':
  job=db.save(user,'job',{'title':'Other job','description':'Fictional role'})
  other=guided.start(user,ConversationStart(job_id=job['id']))
  response=client.post('/api/resume-conversations/'+other['id']+'/finalize',json={**body,'expected_version':other['data']['version']})
  assert response.status_code==404;return
 elif case=='malformed':value['preview']['artifacts']['pdf']=base64.b64encode(b'not a pdf').decode();body['checkpoint_version']=hashlib.sha256(value['preview']['artifacts']['pdf'].encode()).hexdigest()[:20]
 elif case=='clipped':value['preview']['layout']['validated']=False
 elif case=='overflow':value['preview']['layout']['pages']=2
 if case not in ('active','latest'):db.save(user,'resume_run',value,row['id'])
 response=client.post('/api/resume-conversations/'+state['id']+'/finalize',json=body)
 assert response.status_code==409,response.text
 assert not db.list_entities(user,'resume')

def test_other_account_cannot_view_or_finalize_checkpoint(setup,client):
 user,state,run,body,calls=failed(setup)
 client.post('/api/auth/logout')
 other=client.post('/api/auth/register',json={'username':'other-student','password':'fictional-other-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
 from conftest import onboard_test_account
 onboard_test_account(other)
 assert client.post('/api/resume-conversations/'+state['id']+'/finalize',json=body).status_code==404
 assert client.get('/api/resume-revisions/'+run['id']+'/pages/1').status_code==404
 assert not db.list_entities(user,'resume')


def test_saved_manual_document_survives_export_restore_without_ai_authority(setup,client):
 user,state,run,body,calls=failed(setup)
 response=client.post('/api/resume-conversations/'+state['id']+'/finalize',json=body);assert response.status_code==200,response.text
 saved=response.json()['current']['data']['finalized_resume_id'];pdf=client.get('/api/resumes/'+saved+'/export/pdf').content;count=len(calls)
 backup=client.get('/api/account/export').json()
 imported=client.post('/api/account/import',files={'file':('fictional-manual.json',json.dumps(backup).encode(),'application/json')})
 assert imported.status_code==200,imported.text
 copies=[r for r in db.list_entities(user,'resume') if r['id']!=saved];assert len(copies)==1
 assert copies[0]['data']['optimization']['source_checked'] is False and copies[0]['data']['optimization']['manual_review']['ai_review_completed'] is False
 assert client.get('/api/resumes/'+copies[0]['id']+'/export/pdf').content==pdf
 imported_runs=[r for r in db.list_entities(user,'resume_run') if r['id']!=run['id']];assert imported_runs and imported_runs[0]['data']['restored'] and 'preview' not in imported_runs[0]['data']
 assert len(calls)==count


def test_storage_failure_rolls_back_whole_manual_finalization(setup,client,monkeypatch):
 user,state,run,body,calls=failed(setup)
 monkeypatch.setenv('HOSTED_DATA_LIMIT_BYTES','1')
 response=client.post('/api/resume-conversations/'+state['id']+'/finalize',json=body)
 assert response.status_code==400 and 'storage is full' in response.text,response.text
 assert not db.list_entities(user,'resume') and not db.list_entities(user,'resume_revision')
 assert guided.state(user,state['id'])['data']['version']==state['data']['version']
 assert runs.read(user,run['id'])['data']['status']=='needs_changes'
