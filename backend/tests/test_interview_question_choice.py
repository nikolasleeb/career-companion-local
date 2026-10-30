import json
import pytest
from app import db
from test_interview_practice import create,load,body,wait,model

@pytest.mark.parametrize('kind',['behavioral','case','domain','presentation','other'])
def test_ai_setup_question_uses_confirmed_profile_and_owned_job(client,account,model,kind):
 db.save(account['id'],'experience',{'category':'project','title':'Reviewed fictional scheduling project','description':'Built and checked a scheduling tool.','confirmed':True})
 db.save(account['id'],'experience',{'category':'project','title':'UNCONFIRMED_EXCLUDED','confirmed':False})
 job=db.save(account['id'],'job',{'title':'Data analyst','company':'Fictional Employer','description':'Analyze scheduling data and explain decisions.'})
 before=db.list_entities(account['id'],'experience')
 session=create(client,kind=kind,job_id=job['id'],notes='Focus on explaining tradeoffs.')
 assert not load(client,session['id'])['questions'] and not db.list_entities(account['id'],'usage_event')
 result=wait(client,client.post('/api/interview-practice/sessions/'+session['id']+'/actions',json=body(session,focus='Teamwork')))
 assert result['status']=='completed',result
 sent=json.dumps(model[0][1]);assert all(value in sent for value in ('Reviewed fictional scheduling project','Analyze scheduling data','Focus on explaining tradeoffs.','Teamwork'))
 assert 'UNCONFIRMED_EXCLUDED' not in sent and model[0][1]['practice_kind']==kind
 assert model[0][2]['retry_allowed'] is False and len(model)==1
 assert len(load(client,session['id'])['questions'])==1 and db.list_entities(account['id'],'experience')==before
