"""Retry preserves user-started full optimization; no live model requests."""
import asyncio,json
import pytest
from app import db,ai,resume_conversation as guided
from app.network import ServiceError
from test_guided_resume import env,build
from test_applications_workflow import wait_task

@pytest.mark.parametrize('operation,refresh',[('build',True),('build',False),('build?manual=true',False),(None,True)])
def test_failed_build_recovery_exposes_only_action_intent(env,operation,refresh):
 user,job,rows,session,calls=env;state=build(env);before=len(calls)
 inputs={'conversation_id':session['id'],'template':'education','decisions':[],'refresh_linked_evidence':refresh,'preparation':{'private':'Not included in recovery descriptor'}}
 if operation:inputs['operation']=operation
 stamp=db.now()
 with db.connect() as c:c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',(db.uid(),user,'resume_guided','failed',json.dumps({'inputs':inputs}),'Fictional optimization failure.',stamp,stamp))
 recovered=guided.state(user,session['id']);assert recovered['last_failure']
 assert recovered['failed_build_action']=={'operation':operation or 'build','asTask':True,'body':{'refresh_linked_evidence':refresh}}
 assert 'Not included' not in json.dumps(recovered['failed_build_action']) and len(calls)==before


def test_failed_full_build_retries_all_the_way_through_quality_review(env,client,monkeypatch):
 from app import main
 user,job,rows,session,calls=env;state=build(env);previous=state['current']['id'];raw=ai.structured
 monkeypatch.setattr(main,'require_ai',lambda *a:None);monkeypatch.setattr(guided,'require_initial_comparison',lambda *a:None)
 async def failure(schema,payload,*a,**kw):
  if schema.__name__=='ResumeStrategy':raise ServiceError('Fictional grouped-qualification failure.')
  return await raw(schema,payload,*a,**kw)
 monkeypatch.setattr(ai,'structured',failure)
 path='/api/resume-conversations/'+session['id']+'/build'
 failed=wait_task(client,client.post(path,json={'expected_version':state['data']['version'],'refresh_linked_evidence':True}))
 assert failed['status']=='failed'
 recovered=guided.state(user,session['id']);assert recovered['current']['id']==previous
 assert recovered['failed_build_action']['body']['refresh_linked_evidence'] is True
 monkeypatch.setattr(ai,'structured',raw);before=len(calls)
 retried=wait_task(client,client.post(path,json={'expected_version':recovered['data']['version'],**recovered['failed_build_action']['body']}))
 assert retried['status']=='completed',retried
 names=[name for name,payload in calls[before:]]
 assert 'ResumeStrategy' in names and 'ResumeQualityReview' in names and names[-1]=='DraftAudit'
 assert retried['result']['current']['data']['snapshot']['optimization']['quality_review']['status']=='ready'
