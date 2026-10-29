import asyncio
import json
import pytest
from fastapi import HTTPException
from app import db,task_progress,ai,resume_layout,resume_conversation as guided
from app.main import run_task,get_task
from app.network import ServiceError
from test_guided_resume import env
from test_applications_workflow import wait_task


def task(user,kind='resume_guided'):
    identity=db.uid();stamp=db.now()
    with db.connect() as c:c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',(identity,user,kind,'queued',json.dumps({'inputs':{'conversation_id':'fixture','private':'Never copy into progress'}}),None,stamp,stamp))
    return identity


def test_owned_progress_preserves_result_contract_and_freezes_completion(account):
    user=account['id'];identity=task(user)
    async def work():
        task_progress.stage('drafting');task_progress.stage('drafting')
        status=get_task(identity,user={'id':user});assert status['progress']['code']=='drafting'
        assert status['result']['inputs']['private']=='Never copy into progress'
        task_progress.stage('rendering');return {'id':'revision'}
    asyncio.run(run_task(identity,user,work))
    status=get_task(identity,user={'id':user});assert status['status']=='completed' and status['result']=={'id':'revision'}
    progress=status['progress'];assert progress['finished_at']==status['updated_at']
    assert [v['code'] for v in progress['history']]==['starting','drafting']
    assert progress['code']=='rendering' and 'private' not in json.dumps(progress).lower()
    with pytest.raises(HTTPException) as error:get_task(identity,user={'id':'foreign'})
    assert error.value.status_code==404


@pytest.mark.parametrize('cancel',[False,True])
def test_failure_and_interruption_keep_inputs_and_stop_stage_timer(account,cancel):
    user=account['id'];identity=task(user)
    async def work():
        task_progress.stage('checking')
        if cancel:raise asyncio.CancelledError()
        raise ServiceError('Mock source check failed')
    if cancel:
        with pytest.raises(asyncio.CancelledError):asyncio.run(run_task(identity,user,work))
    else:asyncio.run(run_task(identity,user,work))
    status=get_task(identity,user={'id':user})
    assert status['status']==('interrupted' if cancel else 'failed')
    assert status['progress']['finished_at']==status['updated_at']
    assert status['result']['inputs']['conversation_id']=='fixture'


def test_no_stage_writes_outside_bound_owned_running_task(account):
    user=account['id'];identity=task(user)
    token=task_progress.bind('foreign',identity)
    try:task_progress.stage('drafting')
    finally:task_progress.reset(token)
    assert get_task(identity,user={'id':user})['progress'] is None
    task_progress.stage('drafting')
    assert get_task(identity,user={'id':user})['progress'] is None


def test_simultaneous_tasks_keep_independent_stage_contexts(account):
    user=account['id'];one,two=task(user),task(user)
    async def first():
        task_progress.stage('drafting');await asyncio.sleep(0);task_progress.stage('checking');return {'one':True}
    async def second():
        task_progress.stage('fitting');await asyncio.sleep(0);task_progress.stage('rendering');return {'two':True}
    async def both():await asyncio.gather(run_task(one,user,first),run_task(two,user,second))
    asyncio.run(both())
    assert get_task(one,user={'id':user})['progress']['code']=='checking'
    assert get_task(two,user={'id':user})['progress']['code']=='rendering'


def test_legacy_and_non_resume_tasks_keep_original_contract(account):
    user=account['id'];identity=task(user,'fixture_other')
    async def work():task_progress.stage('drafting');return {'original':'value'}
    asyncio.run(run_task(identity,user,work))
    value=get_task(identity,user={'id':user});assert value['progress'] is None and value['result']=={'original':'value'}


def test_real_guided_pipeline_reports_draft_layout_audit_and_local_stages(env,client,monkeypatch):
    user,job,rows,session,calls=env;original=ai.structured;observed=[]
    async def model(schema,payload,mode='economy',**kwargs):
        with db.connect() as c:
            row=c.execute("SELECT id FROM tasks WHERE user_id=? AND status='running' ORDER BY created_at DESC LIMIT 1",(user,)).fetchone()
        status=get_task(row['id'],user={'id':user});observed.append((schema.__name__,status['progress']['code']))
        return await original(schema,payload,mode,**kwargs)
    monkeypatch.setattr(ai,'structured',model)
    def inspect(pdf,snapshot):
        item=next(i for s in snapshot['sections'] for e in s['entries'] if e['category']=='project' for i in e['content_items'] if i['field']=='description')
        return [{'kind':'dangling_words','item_id':item['item_id'],'text':'Fictional layout correction'}]
    monkeypatch.setattr(resume_layout,'inspect',inspect)
    identity=task(user)
    async def work():return await guided.build(user,session['id'],session['data']['version'],'economy')
    asyncio.run(run_task(identity,user,work))
    completed=get_task(identity,user={'id':user})
    assert completed['status']=='completed',completed
    assert completed['result']['current']
    assert observed==[('OptimizationOutput','drafting'),('OptimizationOutput','layout'),('DraftAudit','checking')]
    assert len(calls)==3 # Existing bounded correction + audit; progress adds no requests.
    codes=[v['code'] for v in completed['progress']['history']]+[completed['progress']['code']]
    assert codes==['starting','preparing','drafting','fitting','rendering','layout','rendering','checking','saving']


def test_manual_build_reports_only_local_work(env,client):
    user,job,rows,session,calls=env
    result=wait_task(client,client.post('/api/resume-conversations/'+session['id']+'/build?manual=true',json={'expected_version':session['data']['version']}))
    assert result['status']=='completed' and not calls
    assert all(v['kind']=='local' for v in result['progress']['history'])
    assert result['progress']['code']=='saving'


def test_refresh_comparison_stage_only_runs_when_profile_changed(env,monkeypatch):
    user,job,rows,session,calls=env
    state=guided.mutate(user,session['id'],session['data']['version'],lambda d,c:d.update(profile_dirty=True))
    identity=task(user)
    async def compare(*args,**kwargs):
        assert get_task(identity,user={'id':user})['progress']['code']=='comparison'
        raise ServiceError('Mock comparison stop')
    monkeypatch.setattr(ai,'analyze',compare)
    async def work():return await guided.build(user,session['id'],state['data']['version'],'economy')
    asyncio.run(run_task(identity,user,work))
    result=get_task(identity,user={'id':user});assert result['status']=='failed' and result['progress']['code']=='comparison'
    assert not calls


def test_project_analysis_provider_progress_uses_the_real_request_boundary(account,monkeypatch):
    import httpx
    from app import credentials
    user=account['id'];identity=task(user,'project_analysis');calls=[]
    monkeypatch.setattr(credentials,'effective',lambda _: 'fictional-not-a-real-key')
    async def mock_post(self,url,**kwargs):
        calls.append(url)
        status=get_task(identity,user={'id':user})
        assert status['progress']['code']=='provider' and status['progress']['kind']=='provider'
        with pytest.raises(HTTPException):get_task(identity,user={'id':'foreign'})
        return httpx.Response(200,json={'id':'fictional-response','status':'completed','output':[]},request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx.AsyncClient,'post',mock_post)
    async def work():
        assert get_task(identity,user={'id':user})['progress']['label']=='Preparing project analysis'
        await ai.call_api({'model':'gpt-6.1-sol','input':'Fictional progress fixture','max_output_tokens':16})
        assert get_task(identity,user={'id':user})['progress']['code']=='processing'
        return {'fixture':True}
    asyncio.run(run_task(identity,user,work))
    value=get_task(identity,user={'id':user})
    assert value['status']=='completed' and value['result']=={'fixture':True}
    assert [v['code'] for v in value['progress']['history']]==['starting','provider']
    assert value['progress']['finished_at']==value['updated_at']
    assert calls==['https://api.openai.com/v1/responses']
