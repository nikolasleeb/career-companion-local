import json
import pytest
from app import db,onboarding,ai,integrations,work_style

@pytest.fixture
def fresh(client):
    value=client.post('/api/auth/register',json={'username':'new_student','password':'fictional-setup-password'}).json()
    client.headers['X-CSRF-Token']=value['csrf']
    return value

def state(client):return client.get('/api/onboarding').json()
def request(s):return {'expected_version':s['version'],'profile_signature':s['profile_signature']}
def section(s,key):return next(r for r in s['sections'] if r['id']==key)
def empty(client,key):
    s=state(client);return client.put('/api/onboarding/sections',json={**request(s),'section':key,'empty':True})
def education(client,**values):return client.post('/api/experience',json={'category':'education','title':'Bachelor of Science','organization':'Fictional University','degree':'BS','confirmed':True,**values}).json()
def ready(client):
    education(client)
    for key in onboarding.SECTIONS[1:]:assert empty(client,key).status_code==200
    return state(client)

def test_first_time_checklist_and_resources_without_key(client,fresh,monkeypatch):
    s=state(client);assert not s['completed'] and not s['ready'] and len(s['sections'])==6
    assert client.get('/api/me').json()['onboarding']==s
    assert not section(s,'education')['can_mark_empty']
    for url in ('/api/workspace','/api/profile-answers','/api/project-sources','/api/settings/job-connections','/api/account/export','/api/tasks/active'):
        assert client.get(url).status_code==200,url
    assert client.post('/api/work-style').status_code==403
    assert client.post('/api/project-sources/paste',json={'title':'Notes','text':'A course project.'}).status_code==200
    assert client.post('/api/answer-drafts',json={'title':'Example','expected_version':0,'text':'','question':work_style.DIMENSIONS[0]['prompt']}).status_code==200
    assert client.post('/api/onboarding/complete',json=request(s)).status_code==409
    assert client.put('/api/onboarding/sections',json={**request(s),'section':'education','empty':True}).status_code==422
    assert client.delete('/api/records/'+s['id']).status_code==409

@pytest.mark.parametrize('method,path',[
 ('post','/api/jobs'),('post','/api/jobs/parse'),('post','/api/jobs/import-document'),('post','/api/jobs/import-url'),('post','/api/jobs/search'),('get','/api/jobs/foreign/overview'),('post','/api/jobs/foreign/check'),
 ('post','/api/boards'),('post','/api/analyses'),('get','/api/analyses/foreign/role-alignment'),('post','/api/resumes'),('post','/api/resumes/save'),('post','/api/resume-content'),('post','/api/resumes/fit'),('post','/api/resumes/optimize'),('post','/api/resumes/optimize-estimate'),('post','/api/resumes/keywords'),('get','/api/resumes/foreign/export/pdf'),('post','/api/resume-conversations'),('post','/api/resume-conversations/foreign/build'),('get','/api/resume-drafts'),('post','/api/cover-letters/workspace'),('post','/api/cover-workspaces/foreign/questions'),('post','/api/cover-workspaces/foreign/context/review'),('get','/api/cover-letters/foreign/export/pdf'),('get','/api/applications'),('get','/api/applications/dashboard'),('post','/api/applications/start'),('post','/api/applications'),('put','/api/applications/foreign'),('delete','/api/applications/foreign'),('post','/api/preparation'),('post','/api/interviews'),('post','/api/demo/analyst')])
def test_all_application_entrypoints_are_guarded_before_work(client,fresh,monkeypatch,method,path):
    async def forbidden(*a,**k):raise AssertionError('Provider/network must not run')
    monkeypatch.setattr(ai,'structured',forbidden)
    response=client.request(method,path,json={} if method not in ('get','delete') else None)
    assert response.status_code==403,(path,response.text)
    assert 'education entry' in response.json()['detail']
    assert response.headers['x-next-step-setup']=='required'
    with db.connect() as c:assert c.execute('SELECT count(*) FROM tasks WHERE user_id=?',(fresh['id'],)).fetchone()[0]==0

@pytest.mark.parametrize('values,expected',[
 ({'confirmed':False},'needs_review'),({'organization':''},'required'),({'degree':'','title':'Education'},'required'),({'degree':'','title':'Fictional University'},'required'),({'degree':'','title':'High school diploma'},'complete')])
def test_education_requires_review_school_and_qualification(client,fresh,values,expected):
    education(client,**values);assert section(state(client),'education')['status']==expected

def test_checklist_empty_decisions_completion_retry_and_no_relock(client,fresh):
    s=ready(client);assert s['ready'] and s['completed']
    assert client.get('/api/applications').status_code==200 # Education unlocks immediately.
    response=client.post('/api/onboarding/complete',json=request(s));assert response.status_code==200,response.text
    assert response.json()['completed'] and not response.json()['grandfathered']
    assert client.post('/api/onboarding/complete',json=request(s)).status_code==200
    assert client.get('/api/applications').status_code==200
    for item in db.list_entities(fresh['id'],'experience'):assert client.delete('/api/records/'+item['id']).status_code==200
    assert not state(client)['completed'] and client.get('/api/applications').status_code==403
    assert not client.get('/api/me').json()['settings'].get('name')
    assert client.post('/api/auth/logout').status_code==200
    login=client.post('/api/auth/login',json={'username':'new_student','password':'fictional-setup-password'}).json()
    assert not login['onboarding']['completed']

def test_new_records_clear_empty_even_if_removed_before_reload(client,fresh):
    assert empty(client,'project').status_code==200
    item=client.post('/api/experience',json={'title':'Draft project','confirmed':False}).json()
    assert client.delete('/api/records/'+item['id']).status_code==200
    assert section(state(client),'project')['status']=='not_started'
    item=client.post('/api/experience',json={'title':'Reviewed project','confirmed':True}).json()
    assert section(state(client),'project')['status']=='complete'
    assert empty(client,'project').status_code==409
    client.put('/api/experience/'+item['id'],json={'title':'Changed draft','confirmed':False})
    assert section(state(client),'project')['status']=='needs_review'


def test_coursework_in_education_and_all_drafts_require_review(client,fresh):
    education(client,relevant_courses='Statistics; Programming')
    assert section(state(client),'coursework')['status']=='complete'
    client.post('/api/experience',json={'category':'coursework','title':'Draft course','confirmed':False})
    assert section(state(client),'coursework')['status']=='needs_review'
    assert empty(client,'coursework').status_code==409


def test_profile_signature_and_concurrent_decisions(client,fresh):
    s=state(client);body={**request(s),'section':'skills','empty':True}
    assert client.put('/api/onboarding/sections',json=body).status_code==200
    assert client.put('/api/onboarding/sections',json=body).status_code==409
    s=ready(client)
    client.put('/api/settings',json={'name':'Optional Student'}) # Optional contact edit does not invalidate evidence.
    item=db.list_entities(fresh['id'],'experience')[0]
    client.put('/api/experience/'+item['id'],json={**item['data'],'degree':'BA'})
    assert client.post('/api/onboarding/complete',json=request(s)).status_code==200
    assert state(client)['completed']


def test_project_analysis_needs_approval_before_it_counts(client,fresh):
    snap=client.post('/api/project-sources/paste',json={'title':'Course project','text':'LinearRegression is in this project.'}).json()
    # Analysis is available during setup; lack of a provider key is the only blocker.
    assert client.post('/api/project-snapshots/'+snap['id']+'/analyze',json={'mode':'economy'}).status_code==503
    draft=client.post('/api/project-snapshots/'+snap['id']+'/notes').json()
    assert section(state(client),'project')['status']=='needs_review'
    body={'expected_version':1,'title':'Course project','text':'I cleaned public data and compared regressions.','contribution':'I implemented preprocessing and checked held-out predictions.','confirmed':True}
    response=client.post('/api/profile-answers/drafts/'+draft['id']+'/review',json=body)
    assert response.status_code==200,response.text
    assert not db.list_entities(fresh['id'],'experience')
    assert section(state(client),'project')['status']=='complete'
    assert client.post('/api/project-snapshots/'+snap['id']+'/attach',json={'builder':'resume','conversation_id':'missing','expected_version':1}).status_code==403
    assert client.post('/api/work-style/prompts',json={'themes':['1'],'job_id':'missing'}).status_code==403
    assert client.post('/api/work-style/prompts',json={'themes':['1'],'job_id':''}).status_code==403


def test_migration_only_grandfathers_existing_application_users(client,fresh):
    assert not state(client)['completed']
    with db.connect() as c:c.execute("DELETE FROM entities WHERE user_id=? AND kind='onboarding'",(fresh['id'],))
    db.save(fresh['id'],'application',{'title':'Historical application'})
    s=state(client);assert not s['completed'] and not s['grandfathered']
    # The same fresh reset as the user's test workflow removes setup state and history.
    with db.connect() as c:c.execute("DELETE FROM entities WHERE user_id=? AND kind<>'board'",(fresh['id'],))
    assert not state(client)['completed']


def test_backup_progress_remapping_single_record_and_isolation(client,fresh):
    education(client);assert empty(client,'employment').status_code==200
    backup=client.get('/api/account/export').json();assert len([r for r in backup['records'] if r['kind']=='onboarding'])==1
    original_education=db.list_entities(fresh['id'],'experience')[0]['id']
    other=client.post('/api/auth/register',json={'username':'other_student','password':'fictional-setup-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
    assert not state(client)['completed']
    result=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup),'application/json')});assert result.status_code==200,result.text
    assert len(db.list_entities(other['id'],'onboarding'))==1
    assert section(state(client),'employment')['status']=='empty' and section(state(client),'education')['status']=='complete'
    assert db.list_entities(other['id'],'experience')[0]['id']!=original_education
    assert onboarding.status(fresh['id'])['completed']
    corrupt=json.loads(json.dumps(backup));next(r for r in corrupt['records'] if r['kind']=='onboarding')['data']['empty_sections']=['education']
    before=len(db.list_entities(other['id'],'experience'))
    assert client.post('/api/account/import',files={'file':('bad.json',json.dumps(corrupt),'application/json')}).status_code==400
    assert len(db.list_entities(other['id'],'experience'))==before


def test_completed_backup_retains_completion(client,fresh):
    s=ready(client);client.post('/api/onboarding/complete',json=request(s))
    backup=client.get('/api/account/export').json()
    other=client.post('/api/auth/register',json={'username':'restored_student','password':'fictional-setup-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
    response=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup),'application/json')});assert response.status_code==200,response.text
    assert state(client)['completed'] and len(db.list_entities(other['id'],'onboarding'))==1


def test_resume_import_only_counts_after_review_and_never_auto_finishes(client,fresh,monkeypatch):
    from test_resume_parser import upload,request_body
    def no_provider(*a,**k):raise AssertionError('Import and review must stay local')
    monkeypatch.setattr(ai,'call_api',no_provider)
    document=upload(client)
    assert section(state(client),'education')['status']=='required'
    response=client.post('/api/documents/'+document['id']+'/import-resume',json=request_body(document))
    assert response.status_code==200,response.text
    s=state(client);assert section(s,'education')['status']=='complete' and s['completed']
    assert client.get('/api/applications').status_code==200


def test_rejected_source_findings_can_be_marked_empty_and_restore_never_relocks(client,fresh):
    snap=client.post('/api/project-sources/paste',json={'title':'Old project','text':'Unconfirmed code.'}).json()
    draft=client.post('/api/project-snapshots/'+snap['id']+'/notes').json()
    assert section(state(client),'project')['status']=='needs_review'
    response=client.post('/api/profile-answers/drafts/'+draft['id']+'/review',json={'expected_version':1,'title':'Old project','rejected':True})
    assert response.status_code==200
    assert empty(client,'project').status_code==200
    incomplete=client.get('/api/account/export').json()
    s=ready(client);assert client.post('/api/onboarding/complete',json=request(s)).status_code==200
    response=client.post('/api/account/import',files={'file':('partial.json',json.dumps(incomplete),'application/json')})
    assert response.status_code==200,response.text
    assert state(client)['completed'] and len(db.list_entities(fresh['id'],'onboarding'))==1
