import copy
import json
from app import ai, career_goals, config, credentials, db
from test_broader_career import wait
from test_career_coach import reply
from conftest import onboard_test_account

def setup_model(account,monkeypatch):
    credentials.save(account['id'],'sk-fictional-never-sent');monkeypatch.setattr(config,'ENABLE_WEB_SEARCH',False)
    calls=[]
    async def model(schema,payload,*args,**kwargs):
        calls.append(copy.deepcopy(payload));value=reply(payload)
        action=value['recommendations'][0]
        action.update(horizon='flexible',period_label='Next semester',due_date='2028-04-01',date_basis='verified_deadline')
        return value,{'model':'fictional'}
    monkeypatch.setattr(ai,'structured',model)
    return calls

def generate(client,text='Prepare for internships',**extra):
    return wait(client,client.post('/api/career-coach/chats/new/actions',json={
        'operation':'plan','text':text,'request_token':'flex-plan-'+db.uid(),**extra}))

def accept(client,result,**extra):
    message=result['result'];id=message['data']['chat_id']
    chat=client.get('/api/career-coach/chats/'+id).json()['chat']
    return client.post('/api/career-coach/chats/'+id+'/roadmap',json={'message_id':message['id'],'expected_updated_at':chat['updated_at'],**extra})

def test_generated_plan_requires_review_and_explicitly_selected_goals(client,account,monkeypatch):
    calls=setup_model(account,monkeypatch);u=account['id']
    career_goals.save(u,career_goals.Change(expected_revision=0,items=[career_goals.Goal(id='chosen',text='Explore a research internship.'),career_goals.Goal(id='other',text='UNSELECTED_PLANNING_GOAL')]))
    plan={'purpose':'internships','objective':'Explore research internships.','target':'Graduation in May 2028','time_available':'Three hours per week','budget':'Free resources','goal_ids':['chosen'],'goals_revision':1}
    result=generate(client,plan_input=plan);assert result['status']=='completed',result
    assert not db.list_entities(u,'coach_plan')
    assert calls[0]['planning_inputs']['selected_goals_as_aspirations'][0]['id']=='chosen'
    assert 'UNSELECTED_PLANNING_GOAL' not in json.dumps(calls)
    assert result['result']['data']['planning_inputs_snapshot']['target']=='Graduation in May 2028'
    assert client.get('/api/career-coach/plans').json()['plans']==[]
    saved=accept(client,result);assert saved.status_code==200,saved.text
    index=client.get('/api/career-coach/plans').json()['plans']
    assert len(index)==1 and index[0]['current'] and index[0]['next_step']
    assert not career_goals.read(u)['use_for_ai']

def test_reviewed_edits_keep_sources_identity_and_progress_and_import(client,account,monkeypatch):
    setup_model(account,monkeypatch);u=account['id'];before=copy.deepcopy(db.list_entities(u,'experience'))
    result=generate(client);assert result['status']=='completed',result
    proposal=result['result']['data']['reply']['recommendations'][0]
    assert proposal['date_basis']=='suggested' # No fetched source verifies this exact date.
    changes={'id':proposal['id'],'title':'Talk with a researcher','steps':['Prepare three questions','Ask about day-to-day work'],'period_label':'This semester','due_date':'2028-03-15','effort':'Two hours'}
    saved=accept(client,result,milestones=[changes],direction='Explore through conversations first.')
    assert saved.status_code==200,saved.text
    data=saved.json()['data'];action=data['actions'][0]
    assert action['id']==proposal['id'] and action['citations']==proposal['citations'] and action['evidence']==proposal['evidence']
    assert action['period_label']=='This semester' and action['date_basis']=='suggested'
    assert action['steps']==changes['steps']
    assert client.patch('/api/career-coach/chats/'+data['chat_id']+'/actions/'+action['id'],json={'state':'completed'}).status_code==200
    assert db.list_entities(u,'experience')==before
    index=client.get('/api/career-coach/plans').json()['plans'];assert index[0]['next_step']=='All milestones completed'
    backup=client.get('/api/account/export').json()
    imported=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')})
    assert imported.status_code==200,imported.text
    assert len(client.get('/api/career-coach/plans').json()['plans'])==2

def test_plan_revision_checks_and_invalid_edits_preserve_proposal(client,account,monkeypatch):
    calls=setup_model(account,monkeypatch);u=account['id']
    career_goals.save(u,career_goals.Change(expected_revision=0,items=[career_goals.Goal(id='chosen',text='Explore an internship.')]))
    stale=client.post('/api/career-coach/chats/new/actions',json={'operation':'plan','text':'Plan','request_token':'stale-planning-goal','plan_input':{'objective':'Explore','goal_ids':['chosen'],'goals_revision':0}})
    assert stale.status_code==409 and not calls
    result=generate(client);assert result['status']=='completed'
    message=result['result'];chatid=message['data']['chat_id']
    rejected=client.post('/api/career-coach/chats/'+chatid+'/roadmap',json={'message_id':message['id'],'expected_updated_at':'old-timestamp'})
    assert rejected.status_code==409 and not db.list_entities(u,'coach_plan')
    bad={'id':'invented-action','title':'Unsupported identity','steps':['One step']}
    assert accept(client,result,milestones=[bad]).status_code==422
    assert not db.list_entities(u,'coach_plan')
    assert db.get(u,message['id'],'coach_message')
    other=client.post('/api/auth/register',json={'username':'other-plans','password':'fictional-password'}).json();onboard_test_account(other);client.headers['X-CSRF-Token']=other['csrf']
    assert client.get('/api/career-coach/plans').json()['plans']==[]
    assert client.post('/api/career-coach/chats/'+chatid+'/roadmap',json={'message_id':message['id']}).status_code==404

def test_legacy_plan_backup_without_new_timeline_fields(client,account,monkeypatch):
    setup_model(account,monkeypatch);result=generate(client);saved=accept(client,result)
    assert saved.status_code==200
    backup=client.get('/api/account/export').json()
    for record in backup['records']:
        d=record['data']
        actions=d.get('actions',[]) if record['kind']=='coach_plan' else d.get('reply',{}).get('recommendations',[])
        for action in actions:
            action['horizon']='30'
            for field in ('period_label','due_date','date_basis'):action.pop(field,None)
    restored=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')})
    assert restored.status_code==200,restored.text
