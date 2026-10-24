import asyncio
import copy
import json
import pytest
from fastapi import HTTPException
from app import db, ai, project_sources as sources, work_style, profile_answers, answer_drafts
from app.project_routes import Draft, Review, Prompts
from app.network import ServiceError
from app.models import ExperienceItem


def pasted(client,text='from sklearn.linear_model import LinearRegression\nmodel = LinearRegression()'):
    response=client.post('/api/project-sources/paste',json={'title':'Fictional coursework','text':text})
    assert response.status_code==200,response.text
    return response.json()

def draft_for(user,snapshot):
    return db.save(user,'answer_draft',{'version':1,'status':'draft','builder':'project','title':'Course project','text':'','contribution':'','snapshot_id':snapshot['id'],'analysis_id':db.save(user,'project_analysis',{'snapshot_id':snapshot['id'],'summary':'A model is defined','findings':[],'questions':[]})['id'],'experience_id':'','questions':[{'id':'0','text':'What did you implement?'}],'question_answers':{},'findings':[{'file_path':snapshot['data']['files'][0]['file_path'],'quote':'LinearRegression','observation':'Project contains a model','line_start':1,'line_end':1}],'history':[]})


def test_read_preview_uploads_notebooks_and_bounds_without_ai(client,account,monkeypatch):
    async def no_ai(*args,**kwargs):raise AssertionError('No AI permitted for import')
    monkeypatch.setattr(ai,'structured',no_ai)
    snapshot=pasted(client,'é'*150000)
    f=snapshot['data']['files'][0];assert f['truncated'] and len(f['text'].encode())<=sources.MAX_FILE
    notebook={'cells':[{'cell_type':'code','source':['dangerous_call()'],'outputs':[{'text':['saved output only']}]}]}
    response=client.post('/api/project-sources/upload',files=[('files',('analysis.ipynb',json.dumps(notebook),'application/json')),('files',('.env','secret','text/plain')),('files',('node_modules/x.js','ignored','text/plain')),('files',('report.zip',b'zip','application/zip'))])
    assert response.status_code==200,response.text
    value=response.json()['data'];assert len(value['files'])==1 and len(value['excluded'])==3
    assert 'Cell 1' in value['files'][0]['text'] and 'saved output only' in value['files'][0]['text']
    assert not profile_answers.confirmed(account['id'])
    assert client.post('/api/project-sources/upload',files=[('files',(f'x{i}.py','a','text/plain')) for i in range(31)]).status_code==400
    assert not sources.allowed('../x.py') and not sources.allowed('src/credentials.json') and not sources.allowed('dist/index.js')


def test_public_github_resolves_slash_branch_pins_commit_and_never_executes(client,account,monkeypatch):
    import base64
    calls=[]
    async def gh(path):
        calls.append(path)
        if path=='repos/example/demo':return {'default_branch':'main','private':False}
        if '/commits/feature%2Fnew%2Fmain.py' in path:raise ServiceError('unavailable')
        if '/commits/' in path:return {'sha':'abc123'}
        if '/git/trees/' in path:return {'tree':[{'type':'blob','path':'main.py','size':50,'sha':'file1','mode':'100644'},{'type':'blob','path':'.env','size':10,'sha':'bad','mode':'100644'},{'type':'blob','path':'linked.py','size':10,'sha':'sym','mode':'120000'}]}
        if '/git/blobs/' in path:return {'encoding':'base64','content':'\n'.join([base64.b64encode(b'print("not executed")').decode()[:12],base64.b64encode(b'print("not executed")').decode()[12:]])}
        raise AssertionError(path)
    monkeypatch.setattr(sources,'github',gh)
    row=asyncio.run(sources.discover(account['id'],'https://github.com/example/demo/blob/feature/new/main.py'))
    assert row['data']['commit']=='abc123' and '/commits/feature%2Fnew' in calls[-3]
    assert len(row['data']['available_files'])==1 and len(row['data']['excluded'])==2
    snap=asyncio.run(sources.select(account['id'],row['id'],['main.py']))
    assert '/blob/abc123/main.py' in snap['data']['files'][0]['url']
    repeat=asyncio.run(sources.select(account['id'],row['id'],['main.py']));assert repeat['id']==snap['id']
    with pytest.raises(HTTPException):sources.parse_url('https://github.com.evil.test/example/demo')
    with pytest.raises(HTTPException):sources.parse_url('http://127.0.0.1/test')


def test_github_retries_transient_download_once_without_retrying_access_errors(monkeypatch):
    calls=[]
    async def flaky(*args):
        calls.append(args)
        if len(calls)==1:raise ServiceError('The public page could not be reached.')
        return {'status':200,'content':b'{"encoding":"base64"}'}
    monkeypatch.setattr(sources,'public_fetch',flaky)
    assert asyncio.run(sources.github('repos/example/demo/git/blobs/sha'))=={'encoding':'base64'}
    assert len(calls)==2
    calls.clear()
    async def denied(*args):calls.append(args);return {'status':403}
    monkeypatch.setattr(sources,'public_fetch',denied)
    with pytest.raises(ServiceError,match='rate limit'):asyncio.run(sources.github('repos/example/demo'))
    assert len(calls)==1


def test_two_repositories_have_distinct_files_one_analysis_and_reusable_links(client,account,monkeypatch):
    import base64
    user=account['id'];requests=[];paid=[]
    urls=['https://github.com/example/original','https://github.com/example/extension']
    async def gh(path):
        requests.append(path)
        if '/git/blobs/' in path:
            label='extension model validation' if '/extension/' in path else 'original data cleaning'
            return {'encoding':'base64','content':base64.b64encode(label.encode()).decode()}
        if '/git/trees/' in path:return {'tree':[{'type':'blob','path':'README.md','size':100,'sha':'blob','mode':'100644'}]}
        if '/commits/' in path:return {'sha':'ext123' if '/extension/' in path else 'base123'}
        return {'default_branch':'main','private':False}
    monkeypatch.setattr(sources,'github',gh)
    response=client.post('/api/project-sources/github',json={'urls':urls})
    assert response.status_code==200,response.text
    source=response.json();paths=[f['file_path'] for f in source['data']['available_files']]
    assert len(paths)==2 and len(set(paths))==2 and all(p.endswith('/README.md') for p in paths)
    snap=client.post('/api/project-sources/'+source['id']+'/select',json={'file_paths':paths}).json()
    assert snap['data']['urls']==urls and len(snap['data']['members'])==2
    assert len({f['url'] for f in snap['data']['files']})==2
    assert all('/blob/'+f['commit']+'/README.md' in f['url'] for f in snap['data']['files'])
    async def fake(schema,payload,mode):
        paid.append(payload)
        assert len(payload['files'])==2 and len({f['repository'] for f in payload['files']})==2
        return {'summary':'Original and extension materials.','findings':[{'file_path':f['file_path'],'quote':f['text'],'observation':'Source content.'} for f in payload['files']],'questions':['What was your individual contribution across both classes?']},{'model':'fixture'}
    monkeypatch.setattr(ai,'structured',fake)
    result=asyncio.run(sources.analyze(user,snap['id'],'economy'))
    assert len(paid)==1 and not profile_answers.confirmed(user)
    assert result['draft'] is None and not db.list_entities(user,'answer_draft')
    # Legacy manual review remains available for already saved source drafts.
    draft=draft_for(user,snap)
    draft=db.save(user,'answer_draft',{**draft['data'],'findings':result['analysis']['data']['findings']},draft['id'])
    review=client.post('/api/profile-answers/drafts/'+draft['id']+'/review',json={'expected_version':1,'title':'Extended course project','text':'I cleaned the original data and extended validation.','contribution':'I implemented the checks.','confirmed':True,'create_experience':True})
    assert review.status_code==200,review.text
    assert db.list_entities(user,'experience')[0]['data']['project_urls']==urls
    assert len(review.json()['data']['sources'][0]['repositories'])==2
    backup=client.get('/api/account/export').json()
    other=client.post('/api/auth/register',json={'username':'two-repo-restore','password':'fictional-restore-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
    assert client.get('/api/project-sources').json()['snapshots']==[]
    assert client.post('/api/project-sources/'+source['id']+'/select',json={'file_paths':paths}).status_code==404
    restored=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup),'application/json')})
    assert restored.status_code==200,restored.text
    assert db.list_entities(other['id'],'experience')[0]['data']['project_urls']==urls
    assert len(db.list_entities(other['id'],'project_snapshot')[0]['data']['members'])==2


def test_multi_link_import_validates_before_fetch_and_limits_total_selection(client,account,monkeypatch):
    async def forbidden(*args):raise AssertionError('Invalid links must not be fetched')
    monkeypatch.setattr(sources,'discover',forbidden)
    assert client.post('/api/project-sources/github',json={'urls':['https://github.com/example/good','http://127.0.0.1/private']}).status_code==400
    assert client.post('/api/project-sources/github',json={'urls':['https://github.com/example/'+str(i) for i in range(6)]}).status_code==422
    source=db.save(account['id'],'project_source',{'provider':'github','available_files':[]})
    assert client.post('/api/project-sources/'+source['id']+'/select',json={'file_paths':['file'+str(i) for i in range(31)]}).status_code==422


def test_combined_excerpt_budget_reaches_every_selected_repository():
    files=[{'file_path':str(i)+'.py','text':'x'*20000,'repository':'original' if i<5 else 'extension','commit':'abc'} for i in range(6)]
    excerpts=sources.passages({'files':files,'members':[{'repo':'original'},{'repo':'extension'}]})
    assert len(excerpts)==6 and sum(len(f['text']) for f in excerpts)==60000
    assert all(f['analysis_truncated'] for f in excerpts)
    assert excerpts[-1]['repository']=='extension' and excerpts[-1]['commit']=='abc'


def test_source_analysis_quotes_questions_and_pending_facts(client,account,monkeypatch):
    snap=pasted(client)
    async def fake(schema,payload,mode,**kw):
        assert 'Never infer applicant' in payload['task']
        return {'summary':'Model definition, execution unknown','findings':[{'file_path':snap['data']['files'][0]['file_path'],'quote':'LinearRegression','observation':'Code defines a linear model'}],'questions':['Which code did you write?','How did you validate the model?']},{'model':'test','estimated_token_cost_usd':0}
    monkeypatch.setattr(ai,'structured',fake)
    result=asyncio.run(sources.analyze(account['id'],snap['id'],'economy'))
    assert result['draft'] is None and 'questions' not in result['analysis']['data']
    assert not db.list_entities(account['id'],'answer_draft')
    assert result['analysis']['data']['findings'][0]['line_start']==1
    assert not profile_answers.confirmed(account['id'])
    async def unsupported(*a,**k):return {'summary':'bad','findings':[{'file_path':'nonexistent.py','quote':'invented','observation':'invented'}],'questions':[]},{}
    monkeypatch.setattr(ai,'structured',unsupported)
    with pytest.raises(ServiceError):asyncio.run(sources.analyze(account['id'],snap['id'],'economy'))
    assert len(db.list_entities(account['id'],'project_analysis'))==1


def test_project_approval_requires_contribution_is_transactional_repeat_safe_and_reusable(client,account):
    user=account['id'];snap=pasted(client);draft=draft_for(user,snap)
    payload={'expected_version':1,'title':'Course project','text':'I cleaned public gasoline price data.','confirmed':True}
    url='/api/profile-answers/drafts/'+draft['id']+'/review'
    assert client.post(url,json=payload).status_code==400
    payload.update(contribution='I personally implemented the regression model.',create_experience=True)
    response=client.post(url,json=payload);assert response.status_code==200,response.text
    result=response.json();assert result['data']['status']=='confirmed' and result['data']['sources'][0]['excerpts']
    assert len(db.list_entities(user,'experience'))==1
    assert client.post(url,json=payload).json()['id']==result['id'] and len(db.list_entities(user,'experience'))==1
    assert 'personally implemented' in profile_answers.records(user)[0]['data']['contribution']
    assert profile_answers.records(user)[0]['data']['answer_sources'][0]['provenance'][0]['snapshot_id']==snap['id']
    assert client.post(url,json={**payload,'text':'Changed claim'}).status_code==409


def test_correction_rejection_concurrent_profile_edits_and_private_fields(client,account):
    user=account['id'];snap=pasted(client);draft=draft_for(user,snap)
    target=db.save(user,'experience',ExperienceItem(title='Project',confirmed=True).model_dump())
    payload={'expected_version':1,'title':'Project detail','text':'I prepared the data.','contribution':'I wrote the cleaning code.','confirmed':True,'experience_id':target['id'],'experience_updated_at':target['updated_at'],'update_experience':True}
    db.save(user,'experience',{**target['data'],'description':'Newer change'},target['id'])
    url='/api/profile-answers/drafts/'+draft['id']+'/review'
    assert client.post(url,json=payload).status_code==409
    assert not profile_answers.confirmed(user)
    assert client.post(url,json={**payload,'experience_id':'','text':'I am a US citizen'}).status_code==400
    response=client.post(url,json={'expected_version':1,'title':'Reject','rejected':True});assert response.status_code==200
    assert response.json()['data']['status']=='rejected' and not profile_answers.confirmed(user)


def test_source_refresh_snapshot_and_account_isolation(client,account):
    user=account['id'];snap=pasted(client);original=copy.deepcopy(snap['data'])
    response=client.post('/api/auth/register',json={'username':'another','password':'fictional-test-password'})
    other=response.json();client.headers['X-CSRF-Token']=other['csrf']
    assert client.get('/api/project-snapshots/'+snap['id']).status_code==404
    assert client.get('/api/project-sources').json()['snapshots']==[]
    assert client.put('/api/project-snapshots/'+snap['id']+'/archive',json={'archived':True}).status_code==404
    assert db.get(user,snap['id'],'project_snapshot')['data']==original


def test_work_style_exact_item_order_and_published_reverse_scoring(client,account,monkeypatch):
    async def no_ai(*a,**k):raise AssertionError('Scoring must be local')
    monkeypatch.setattr(ai,'structured',no_ai)
    catalog=work_style.legacy_catalog()
    assert len(catalog['items'])==50 and catalog['items'][0]['text']=='Am the life of the party.' and catalog['items'][-1]['text']=='Am full of ideas.'
    assert len(catalog['options'])==5 and len({q['id'] for q in catalog['items']})==50
    ones=work_style.score({str(i):1 for i in range(1,51)})
    assert [r['total'] for r in ones]==[30,26,26,42,22]
    high={str(i):5 if i in work_style.POSITIVE else 1 for i in range(1,51)}
    assert [r['total'] for r in work_style.score(high)]==[50]*5
    assert [r['total'] for r in work_style.score({k:6-v for k,v in high.items()})]==[10]*5
    row=db.save(account['id'],'work_style',{'version':1,'catalog_version':work_style.VERSION,'catalog':catalog,'status':'draft','answers':{},'page':0,'scores':[]})
    body={'expected_version':1,'answers':{'1':5},'page':2}
    saved=client.put('/api/work-style/'+row['id']+'/progress',json=body);assert saved.status_code==200
    assert client.put('/api/work-style/'+row['id']+'/progress',json=body).status_code==409
    assert client.post('/api/work-style/'+row['id']+'/score',json={**body,'expected_version':2}).status_code==400
    assert next(r for r in client.get('/api/work-style').json() if r['id']==row['id'])['data']['answers']=={'1':5}
    result=client.post('/api/work-style/'+row['id']+'/score',json={'expected_version':2,'answers':high,'page':4});assert result.status_code==200
    assert result.json()['data']['status']=='completed'
    assert client.put('/api/work-style/'+row['id']+'/progress',json={**body,'expected_version':3}).status_code==409
    assert client.post('/api/work-style').json()['id']!=row['id']
    assert not profile_answers.confirmed(account['id'])
    assert client.put('/api/work-style/'+row['id']+'/progress',json={**body,'answers':{'1':True}}).status_code==422


def test_reflection_story_autosave_review_and_prompt_privacy(client,account,monkeypatch):
    user=account['id'];question=work_style.DIMENSIONS[2]['prompt']
    row=client.post('/api/answer-drafts',json={'expected_version':0,'title':'Organizing a project','text':'','question':question}).json()
    value={'expected_version':1,'title':'Organizing a project','text':'I organized a task board and delivered the agreed report.','question_answers':{'story':'I kept the board current.'}}
    saved=client.put('/api/answer-drafts/'+row['id'],json=value);assert saved.status_code==200,saved.text
    assert not profile_answers.confirmed(user)
    listing=client.get('/api/profile-answers').json();assert any(r['id']==row['id'] and r['data']['status']=='draft' for r in listing)
    response=client.post('/api/profile-answers/drafts/'+row['id']+'/review',json={'expected_version':2,'title':value['title'],'text':value['text'],'confirmed':True});assert response.status_code==200,response.text
    assert len(profile_answers.confirmed(user))==1
    job=db.save(user,'job',{'title':'Analyst','description':'Clean datasets and present results.'})
    async def fake(schema,payload,mode,**kwargs):
        assert payload['posting']['title']=='Analyst'
        assert 'answers' not in payload and 'scores' not in payload and 'result' not in payload
        assert payload['themes'][0]['name']=='Conscientiousness'
        return {'questions':['When did you organize a data-cleaning task?']},{'model':'test'}
    monkeypatch.setattr(ai,'structured',fake)
    result=asyncio.run(work_style.prompts(user,Prompts(themes=['3'],job_id=job['id'])))
    assert result['data']['questions']


def test_backup_round_trip_remaps_new_evidence_and_reflection_references(client,account):
    user=account['id'];snap=pasted(client);draft=draft_for(user,snap)
    response=client.post('/api/profile-answers/drafts/'+draft['id']+'/review',json={'expected_version':1,'title':'Course project','text':'I prepared public data.','contribution':'I built the model.','confirmed':True})
    assert response.status_code==200,response.text
    client.post('/api/work-style')
    backup=client.get('/api/account/export');assert backup.status_code==200
    raw=backup.json();before=len(db.list_entities(user,'project_snapshot'))
    response=client.post('/api/account/import',files={'file':('backup.json',json.dumps(raw),'application/json')})
    assert response.status_code==200,response.text
    assert len(db.list_entities(user,'project_snapshot'))==before*2
    added=next(r for r in db.list_entities(user,'answer_draft') if r['id']!=draft['id'])
    assert added['data']['snapshot_id']!=snap['id']
    imported_answer=db.get(user,added['data']['profile_answer_id'],'profile_answer')
    assert imported_answer['data']['sources'][0]['draft_id']==added['id']
    corrupt=copy.deepcopy(raw)
    record=next(r for r in corrupt['records'] if r['kind']=='answer_draft');record['data']['snapshot_id']='foreign'
    response=client.post('/api/account/import',files={'file':('backup.json',json.dumps(corrupt),'application/json')})
    assert response.status_code==400,response.text

from test_cover_letters import env
from test_cover_guided import guided,prepare,answer
from test_applications_workflow import wait_task


def test_attached_sources_inform_questions_without_establishing_facts(guided,client):
    user=guided[0];state=prepare(guided);q=state['data']['questions'][1];snap=pasted(client)
    saved=client.put('/api/cover-workspaces/'+state['id']+'/answers',json={'expected_version':state['data']['version'],'answers':[{'question_id':q['id'],'text':'My older project is at GitHub; I need to check which part I wrote.','expected_answer_version':0}]}).json()
    response=client.post('/api/project-snapshots/'+snap['id']+'/attach',json={'builder':'cover','conversation_id':state['id'],'question_id':q['id'],'expected_version':saved['data']['version']})
    assert response.status_code==200,response.text
    attached=response.json()
    assert snap['id'] in attached['data']['project_snapshot_ids']
    linked=next(item for item in attached['data']['questions'] if item['id']==q['id'])
    assert linked['answer']==saved['data']['questions'][1]['answer'] and linked['project_snapshot_ids']==[snap['id']]
    assert not attached['current'] and not profile_answers.confirmed(user)
    answer(guided,attached,'Please clarify what I personally did in this project.')
    payload=next(payload for schema,payload in reversed(guided[-1]) if schema=='CoverChatOutput')
    assert payload['unreviewed_project_material_for_questions_only'][0]['snapshot_id']==snap['id']
    assert all('LinearRegression' not in source['text'] for source in payload['saved_resume_sources'])
    backup=client.get('/api/account/export').json()
    restored=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup),'application/json')})
    assert restored.status_code==200,restored.text
    new=next(r for r in db.list_entities(user,'cover_workspace') if r['id']!=state['id'])
    assert new['data']['project_snapshot_ids'][0]!=snap['id']


def test_approved_source_details_reach_snapshot_and_corrections_keep_history(client,account):
    from app.main import build_resume
    from app.models import ResumeRequest,ProfileAnswerEdit
    user=account['id'];snap=pasted(client);draft=draft_for(user,snap)
    first=answer_drafts.review(user,draft['id'],Review(expected_version=1,title='Course project',text='I cleaned public data.',contribution='I implemented linear regression.',confirmed=True,create_experience=True))
    snapshot=build_resume(user,ResumeRequest(experience_ids=[first['data']['experience_id']]))
    entry=next(e for sec in snapshot['sections'] for e in sec['entries'])
    assert entry['reviewed_answer_sources'][0]['provenance'][0]['snapshot_id']==snap['id']
    frozen=copy.deepcopy(snapshot)
    target=db.get(user,first['data']['experience_id'],'experience')
    corrected='I cleaned public data.\nI implemented and evaluated linear regression.'
    current=profile_answers.edit(user,first['id'],ProfileAnswerEdit(expected_version=1,title='Course project',text=corrected,experience_id=target['id'],experience_updated_at=target['updated_at'],values={'contribution':corrected}))
    assert current['data']['history'][0]['text']==first['data']['text']
    assert frozen==snapshot and 'evaluated' not in json.dumps(snapshot)
    assert 'evaluated' in json.dumps(profile_answers.records(user))
    second=draft_for(user,snap)
    # A second approval of the same professional detail must reuse the existing Profile record.
    result=answer_drafts.review(user,second['id'],Review(expected_version=1,title='Course project',text='I cleaned public data.',contribution='I implemented and evaluated linear regression.',confirmed=True,create_experience=True))
    assert result['id']==first['id'] and len(db.list_entities(user,'experience'))==1


def test_source_analysis_task_token_survives_completion(guided,client,monkeypatch):
    snap=pasted(client);calls=[]
    async def fake(*args,**kwargs):
        calls.append(args)
        return {'summary':'A project model','findings':[{'file_path':snap['data']['files'][0]['file_path'],'quote':'LinearRegression','observation':'Project uses a linear model'}],'questions':['Which model code did you personally implement?']},{'model':'fixture'}
    monkeypatch.setattr(ai,'structured',fake)
    endpoint='/api/project-snapshots/'+snap['id']+'/analyze';body={'mode':'economy','request_token':'stable-test-token'}
    response=client.post(endpoint,json=body);assert response.status_code==200,response.text
    first=response.json()['task_id'];result=wait_task(client,response);assert result['status']=='completed',result
    assert result['result']['analysis']['data']['snapshot_id']==snap['id']
    repeated=client.post(endpoint,json=body);assert repeated.json()['task_id']==first and len(calls)==1
    assert client.post(endpoint,json={**body,'mode':'deep'}).status_code==409
    recovery=client.get('/api/project-sources').json()['tasks']
    assert recovery[0]['id']==first and recovery[0]['snapshot_id']==snap['id'] and recovery[0]['status']=='completed'
    assert 'result' not in recovery[0] and 'inputs' not in recovery[0]
    assert client.get('/api/tasks/'+first).json()['result']['draft'] is None and result['result']['draft'] is None
    assert len(calls)==1


def test_project_recovery_is_owned_and_active_snapshot_reuses_task(guided,client):
    from app.main import start_task
    user=guided[0];snap=pasted(client);stamp=db.now();task_id=db.uid()
    inputs={'snapshot_id':snap['id'],'mode':'deep','request_token':'original'}
    with db.connect() as c:
        c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',(task_id,user,'project_analysis','running',json.dumps({'inputs':inputs}),None,stamp,stamp))
    async def forbidden():raise AssertionError('Do not restart a running provider task')
    reused=start_task(user,'project_analysis',forbidden,{'snapshot_id':snap['id'],'mode':'economy','request_token':'new-tab'})
    assert reused=={'task_id':task_id,'status':'running'}
    rows=client.get('/api/project-sources').json()['tasks'];assert rows[0]['id']==task_id
    with db.connect() as c:
        c.execute("UPDATE tasks SET status='failed',error=? WHERE id=?",('Fixture provider failure',task_id))
    assert client.get('/api/project-sources').json()['tasks'][0]['error']=='Fixture provider failure'
    response=client.post('/api/auth/register',json={'username':'differentstudent','password':'another-fictional-password'})
    assert response.status_code==200
    assert client.get('/api/project-sources').json()['tasks']==[]
    assert client.get('/api/tasks/'+task_id).status_code==404


def test_manual_source_review_without_key_and_malformed_links(client,account):
    snap=pasted(client)
    notes=client.post('/api/project-snapshots/'+snap['id']+'/notes');assert notes.status_code==200,notes.text
    draft=notes.json()
    assert client.post('/api/project-snapshots/'+snap['id']+'/notes').json()['id']==draft['id']
    assert client.post('/api/project-snapshots/'+snap['id']+'/analyze',json={'mode':'economy'}).status_code==503
    result=client.post('/api/profile-answers/drafts/'+draft['id']+'/review',json={'expected_version':1,'title':'Project','text':'I prepared data for a coursework model.','contribution':'I implemented the cleaning.','confirmed':True})
    assert result.status_code==200,result.text
    backup=client.get('/api/account/export').json()
    assert client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup),'application/json')}).status_code==200
    assert client.post('/api/project-sources/paste',json={'title':'Bad link','text':'Notes','url':'javascript:alert(1)'}).status_code==400
    with pytest.raises(HTTPException):sources.parse_url('https://github.com:notaport/example/demo')


def test_file_selection_estimate_is_free_and_validates_source_files(client,account,monkeypatch):
    async def never(*a,**k):raise AssertionError('An estimate must not read files or call a provider')
    monkeypatch.setattr(sources,'github',never);monkeypatch.setattr(ai,'structured',never)
    row=db.save(account['id'],'project_source',{'provider':'github','available_files':[{'file_path':'README.md','size':30},{'file_path':'model.py','size':90}]})
    path='/api/project-sources/'+row['id']+'/estimate'
    response=client.post(path,json={'file_paths':['README.md','model.py']});assert response.status_code==200,response.text
    assert response.json()['input_tokens']==7800 and response.json()['usd']>0
    assert client.post(path,json={'file_paths':['outside.py']}).status_code==400
    assert client.post(path,json={'file_paths':['model.py','model.py']}).status_code==400
    assert db.list_entities(account['id'],'project_snapshot')==[]
