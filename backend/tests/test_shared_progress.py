import asyncio,json
import pytest
from app import db,task_progress,ai,cover_context as context,cover_letters as letters
from app.main import run_task,get_task
from app.models import CoverContent,CoverMessage,CoverGenerate
from test_task_progress import task
from test_cover_guided import guided,prepare
from test_cover_letters import env


def test_active_task_metadata_owned_and_result_free(client,account):
    user=account['id'];one=task(user,'cover_letter')
    with db.connect() as c:c.execute('INSERT INTO users VALUES(?,?,?,?,?)',('foreign','foreign_user','not-a-login','{}',db.now()))
    two=task('foreign','analysis')
    values=client.get('/api/tasks/active');assert values.status_code==200
    assert [v['id'] for v in values.json()]==[one]
    assert set(values.json()[0])=={'id','kind','status','created_at','updated_at','progress','can_cancel'}
    assert 'private' not in values.text.lower() and 'inputs' not in values.text
    async def work():task_progress.stage('reviewing');return {'id':'workspace','private_result':'not in active listing'}
    asyncio.run(run_task(one,user,work))
    assert client.get('/api/tasks/active').json()==[]
    result=get_task(one,user=account);assert result['result']['private_result']=='not in active listing'
    assert result['progress']['label']=='Reviewing cover-letter answers and changes'
    assert client.get('/api/tasks/'+two).status_code==404


def test_cover_answer_review_progress_without_an_extra_provider_dispatch(guided,client,monkeypatch):
    user,job,resume,state,calls=guided;state=prepare(guided);identity=task(user,'cover_letter');original=ai.structured;seen=[]
    async def model(schema,payload,*args,**kwargs):
        p=get_task(identity,user={'id':user})['progress'];seen.append((schema.__name__,p['code'],p['kind']))
        return await original(schema,payload,*args,**kwargs)
    monkeypatch.setattr(ai,'structured',model);before=len(calls)
    async def work():return await letters.send(user,state['id'],CoverMessage(expected_version=state['data']['version'],content=CoverContent.model_validate(state['data']['content']),text='I wrote a QA guide used by three classmates.',request_token='mock-review'))
    asyncio.run(run_task(identity,user,work));result=get_task(identity,user={'id':user})
    assert result['status']=='completed' and len(calls)==before+1
    assert seen==[('CoverChatOutput','reviewing','provider')]
    assert result['result']['data']['context_proposals'][0]['status']=='pending'
    assert result['progress']['finished_at'] and not result['result']['current']


def test_cover_draft_source_check_and_local_render_stages(guided,monkeypatch):
    user,job,resume,state,calls=guided;identity=task(user,'cover_letter');original=ai.structured;seen=[]
    async def model(schema,payload,*args,**kwargs):
        seen.append((schema.__name__,get_task(identity,user={'id':user})['progress']['code']))
        return await original(schema,payload,*args,**kwargs)
    monkeypatch.setattr(ai,'structured',model)
    async def work():return await letters.generate(user,state['id'],CoverGenerate(expected_version=state['data']['version'],content=CoverContent.model_validate(state['data']['content'])))
    asyncio.run(run_task(identity,user,work));result=get_task(identity,user={'id':user})
    assert result['status']=='completed',result
    assert seen==[('CoverLetterOutput','drafting'),('DraftAudit','checking')]
    progress=result['progress'];assert progress['code']=='saving'
    assert 'rendering' in [v['code'] for v in progress['history']]
    assert len(calls)==2


@pytest.mark.parametrize('kind',['analysis','project_analysis','discovery','interview','preparation','resume_optimize'])
def test_other_ai_actions_have_owned_progress_and_same_result_contract(account,kind):
    identity=task(account['id'],kind)
    async def work():task_progress.provider_wait();task_progress.provider_done();return {'id':'same-result'}
    asyncio.run(run_task(identity,account['id'],work));status=get_task(identity,user=account)
    assert status['result']=={'id':'same-result'} and status['progress']['code']=='processing'
    assert 'provider' in [p['code'] for p in status['progress']['history']]
