import asyncio
import json
import time
from app import applications, application_preparation, db, main, config


def task(user, kind, status, inputs, stamp=None):
    id=db.uid();stamp=stamp or db.now()
    with db.connect() as c:
        c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',(id,user,kind,status,json.dumps({'inputs':inputs}),None,stamp,stamp))
    return id


def test_posting_save_alone_does_not_create_application(client,account):
    result=client.post('/api/jobs',json={'title':'Example role','company':'Example','description':'Fictional posting for application continuity.'})
    assert result.status_code==200,result.text
    assert client.get('/api/applications').json()==[]


def test_comparison_creates_preparing_before_request_finishes(client,account,sample,monkeypatch):
    monkeypatch.setattr(config,'OPENAI_KEY','fictional-never-used')
    released=False
    async def compare(*args,**kwargs):
        while not released:await asyncio.sleep(.02)
        return {'summary':'Fictional comparison'}
    monkeypatch.setattr(main.ai,'analyze',compare)
    response=client.post('/api/analyses',json={'job_id':sample['id']})
    assert response.status_code==200,response.text
    rows=client.get('/api/applications').json();assert len(rows)==1
    assert rows[0]['data']['status']=='preparing'
    assert rows[0]['preparation']['label']=='Comparing posting'
    assert rows[0]['preparation']['task_id']==response.json()['task_id']
    released=True
    for _ in range(100):
        if client.get('/api/tasks/'+response.json()['task_id']).json()['status']=='completed':break
        time.sleep(.02)
    assert client.get('/api/applications').json()[0]['data']['status']=='preparing'
    assert len(client.get('/api/applications').json())==1


def test_workspace_start_is_visible_and_stable(client,account,sample):
    body={'job_id':sample['id']}
    first=client.post('/api/resume-conversations',json=body).json()
    rows=client.get('/api/applications').json();assert len(rows)==1
    again=client.post('/api/resume-conversations',json=body).json()
    assert first['id']==again['id']
    assert rows[0]['id']==client.get('/api/applications').json()[0]['id']
    assert client.get('/api/workspace').json()['application'][0]['preparation']['stage']=='resume'


def test_reconcile_orphan_draft_once_without_mutating_snapshot(client,account,sample):
    user=account['id']
    revision=db.save(user,'resume_revision',{'job_id':sample['id'],'snapshot':{'content':'original historical snapshot'}})
    conversation=db.save(user,'resume_conversation',{'job_id':sample['id'],'version':13,'current_revision_id':revision['id']})
    before=[db.get(user,r['id'],r['kind']) for r in (revision,conversation)]
    rows=client.get('/api/applications').json();assert len(rows)==1
    assert rows[0]['preparation']['label']=='Draft ready to review'
    assert rows[0]['preparation']['stage']=='resume'
    assert before==[db.get(user,r['id'],r['kind']) for r in (revision,conversation)]
    applications.migrate(user);assert len(db.list_entities(user,'application'))==1
    db.delete(user,rows[0]['id']);applications.migrate(user)
    assert not db.list_entities(user,'application')


def test_active_failed_cancelled_and_recovered_states(client,account,sample):
    user=account['id'];app=applications.start(user,sample['id'])
    conv=db.save(user,'resume_conversation',{'job_id':sample['id']})
    id=task(user,'resume_guided','running',{'conversation_id':conv['id']})
    state=application_preparation.decorate(user,[app])[0]['preparation']
    assert state['label']=='Resume generating' and state['task_id']==id
    for status in ('cancelling','cancelled','failed','interrupted'):
        with db.connect() as c:c.execute('UPDATE tasks SET status=?,updated_at=? WHERE id=?',(status,db.now(),id))
        state=application_preparation.decorate(user,[app])[0]['preparation']
        assert state['label']==('Stopping preparation' if status=='cancelling' else 'Needs attention')
    rev=db.save(user,'resume_revision',{'job_id':sample['id']})
    db.save(user,'resume_conversation',{'job_id':sample['id'],'current_revision_id':rev['id']},conv['id'])
    assert application_preparation.decorate(user,[app])[0]['preparation']['label']=='Draft ready to review'
    with db.connect() as c:assert c.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]==1


def test_selected_resume_and_applied_status_are_preserved(client,account,sample):
    user=account['id'];app=applications.start(user,sample['id'])
    resume=db.save(user,'resume',{'job_id':sample['id']})
    old=db.save(user,'resume_revision',{'job_id':sample['id']})
    db.save(user,'resume_conversation',{'job_id':sample['id'],'current_revision_id':old['id']})
    app=db.save(user,'application',{**app['data'],'workflow':{'resume_id':resume['id']}},app['id'])
    assert application_preparation.decorate(user,[app])[0]['preparation']['stage']=='letter'
    assert db.get(user,app['id'],'application')['data']['workflow']['resume_id']==resume['id']
    app=db.save(user,'application',{**app['data'],'status':'applied'},app['id'])
    assert application_preparation.decorate(user,[app])==[app]
    applications.migrate(user);assert db.get(user,app['id'],'application')['data']['status']=='applied'


def test_foreign_records_and_task_ids_never_influence_status(client,account,sample):
    user=account['id'];app=applications.start(user,sample['id'])
    # An unrelated task that mentions a job ID in free text cannot acquire its identity.
    task(user,'resume_guided','running',{'conversation_id':'foreign','text':sample['id']})
    state=application_preparation.decorate(user,[app])[0]['preparation']
    assert state['state']=='ready' and 'task_id' not in state
    client.post('/api/auth/logout')
    registered=client.post('/api/auth/register',json={'username':'otherprep','password':'fictional-other-password'}).json()
    from conftest import onboard_test_account
    onboard_test_account(registered)
    client.headers['X-CSRF-Token']=registered['csrf']
    assert client.get('/api/applications').json()==[]
    assert client.get('/api/resume-conversations/'+app['id']).status_code==404


def test_historical_successful_task_resolves_owned_result(client,account,sample):
    user=account['id'];app=applications.start(user,sample['id'])
    convo=db.save(user,'resume_conversation',{'job_id':sample['id']})
    tid=task(user,'resume_guided','completed',{})
    with db.connect() as c:c.execute('UPDATE tasks SET result=? WHERE id=?',(json.dumps({'_task_result':convo}),tid))
    assert application_preparation.decorate(user,[app])[0]['preparation']['stage']=='resume'


def test_missing_selected_resume_is_not_silently_substituted(client,account,sample):
    user=account['id'];app=applications.start(user,sample['id'])
    db.save(user,'resume',{'job_id':sample['id']})
    app=db.save(user,'application',{**app['data'],'workflow':{'resume_id':'unavailable'}},app['id'])
    state=application_preparation.decorate(user,[app])[0]['preparation']
    assert state['state']=='attention' and state['action_label']=='Choose a saved resume'
    assert db.get(user,app['id'],'application')['data']['workflow']['resume_id']=='unavailable'


def test_combined_upload_keeps_preparing_on_cancellation_without_partial_posting(client,account,monkeypatch):
    from app import job_parser
    monkeypatch.setattr(config,'OPENAI_KEY','fictional-never-used')
    calls=[]
    async def extract(job,*args,**kwargs):
        return {**job_parser.organize({**job,'title':'Fictional uploaded role','company':'Example'}),'extraction_version':1}
    async def compare(*args,**kwargs):
        calls.append('comparison')
        while True:await asyncio.sleep(.02)
    monkeypatch.setattr(main.posting_extraction,'extract',extract)
    monkeypatch.setattr(main.ai,'analyze',compare)
    response=client.post('/api/analyses/from-document',data={'request_token':'fictional-upload-visibility'},files={'file':('role.txt',b'Fictional uploaded role\nRequirements: SQL\nResponsibilities: create reports.')})
    assert response.status_code==200,response.text
    tid=response.json()['task_id']
    for _ in range(100):
        rows=client.get('/api/applications').json()
        if rows and calls:break
        time.sleep(.02)
    assert len(rows)==1 and rows[0]['data']['status']=='preparing'
    assert rows[0]['preparation']['task_id']==tid
    assert not db.list_entities(account['id'],'job')
    assert client.post('/api/tasks/'+tid+'/cancel',json={}).status_code==200
    for _ in range(100):
        if client.get('/api/tasks/'+tid).json()['status']=='cancelled':break
        time.sleep(.02)
    rows=client.get('/api/applications').json()
    assert rows[0]['preparation']['label']=='Needs attention'
    assert rows[0]['preparation']['posting_available'] is False
    assert rows[0]['data']['posting_snapshot']['title']=='Fictional uploaded role'
    assert not db.list_entities(account['id'],'job')
    status=client.get('/api/analyses/from-document/status?request_token=fictional-upload-visibility').json()
    assert status['task_id']==tid and calls==['comparison']
