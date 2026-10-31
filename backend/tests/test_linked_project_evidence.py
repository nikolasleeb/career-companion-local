"""Fictional source, role-boundary, version and provider contract checks."""
import asyncio
import copy
import json
import pytest
from fastapi import HTTPException
from app import db, linked_project_evidence as linked, resume_conversation as guided, resume_builder, resume_layout, optimization, ai
from app.models import ExperienceItem, ConversationStart, LinkedEvidenceReview, RevisionAction, WorkingRender, ResumeRequest
from app.network import ServiceError

@pytest.fixture
def env(client,account,monkeypatch):
    user=account['id']
    def record(**values):return db.save(user,'experience',ExperienceItem(confirmed=True,**values).model_dump())
    intern=record(category='employment',title='Business Intern',organization='Fictional Transport',start_date='2026-06',end_date='2026-08',description='Prepared sponsor demonstrations and recorded feedback.')
    contractor=record(category='employment',title='Research Contractor',organization='Fictional University',start_date='2026-08',description='Expanded review rules after the internship.')
    project=record(category='project',title='Roadway review prototype',description='Built an on-device prototype using local language models and retrieval.',contribution='Initially tested the prototype on approximately 10 roadway documents.',linked_employment_ids=[intern['id'],contractor['id']])
    job=db.save(user,'job',{'title':'Analyst','description':'Analyze data using Python.','company':'Fictional Employer'})
    session=guided.start(user,ConversationStart(job_id=job['id']))
    def render(snapshot):return {**copy.deepcopy(snapshot),'layout':{'pages':1,'validated':True},'artifacts':{'pdf':'fictional-pdf','docx':'fictional-docx'}}
    monkeypatch.setattr(resume_layout,'render',render)
    monkeypatch.setattr(resume_builder,'fit',lambda snap,rows,*args,**kw:{'omitted':[],'experience_ids':[r['id'] for r in rows if r['items'] or r['category']=='education'],'content':{r['id']:list(range(len(r['items']))) for r in rows}})
    return user,intern,contractor,project,job,session

def choices(env,placement='employment',destination=None):
    user,intern,contractor,project,job,session=env
    return [{k:r[k] for k in ('project_id','item_id','source_fingerprint')}|{'placement':placement,'employment_id':destination if destination is not None else intern['id'] if placement=='employment' else '', 'replace_overlaps':False} for r in linked.candidates(user) if r['project_id']==project['id']]

def apply(env,state,placements):
    return guided.place_project_evidence(env[0],state['id'],LinkedEvidenceReview(expected_version=state['data']['version'],placements=placements))

def initial(env):
    session=env[-1]
    return asyncio.run(guided.build(env[0],session['id'],session['data']['version'],'economy',manual=True))

def test_review_is_read_only_and_multi_job_requires_exact_destination(env):
    user,intern,contractor,project,job,session=env
    before=db.get(user,session['id'],'resume_conversation')
    rows=linked.candidates(user)
    assert len(rows)==2 and {j['id'] for j in rows[0]['jobs']}=={intern['id'],contractor['id']}
    assert db.get(user,session['id'],'resume_conversation')==before
    for destination in ('', 'another-account-role', project['id']):
        with pytest.raises(HTTPException):apply(env,session,choices(env,destination=destination))
    assert not db.list_entities(user,'resume_revision')
    state=apply(env,session,choices(env))
    assert not state['current'] and len(state['data']['linked_project_placements'])==2
    snapshot=guided.source(user,state['data']);entries=linked.entries(snapshot)
    assert not entries[project['id']]['content_items']
    assert len([i for i in entries[intern['id']]['content_items'] if i.get('project_source')])==2
    assert not any(i.get('project_source') for i in entries[contractor['id']]['content_items'])
    ref=entries[intern['id']]['content_items'][-1]['project_source']
    assert ref['original'].startswith('Initially tested') and ref['employment_id']==intern['id']
    assert db.get(user,intern['id'],'experience')==intern


def test_single_job_and_each_bullet_has_one_catalog_destination(env):
    user,intern,contractor,project,job,session=env
    db.save(user,'experience',{**project['data'],'linked_employment_ids':[intern['id']]},project['id'])
    c=choices(env);c[1].update(placement='project',employment_id='')
    state=apply(env,session,c);entries=linked.entries(guided.source(user,state['data']))
    assert len(entries[project['id']]['content_items'])==1
    assert len([i for i in entries[intern['id']]['content_items'] if i.get('project_source')])==1
    with pytest.raises(HTTPException):apply(env,state,[c[0],c[0]])


def test_overlap_requires_explicit_replacement_and_restores_history(env):
    user,intern,contractor,project,job,session=env
    text=project['data']['description']
    db.save(user,'experience',{**intern['data'],'description':text},intern['id'])
    state=initial(env);old=copy.deepcopy(db.get(user,state['current']['id'],'resume_revision'))
    c=choices(env);assert linked.candidates(user)[0]['jobs'][0]['overlaps']
    with pytest.raises(HTTPException):apply(env,state,c)
    c[0]['replace_overlaps']=True
    changed=apply(env,state,c);snap=changed['current']['data']['snapshot']
    assert sum(text in i['text'] for e in linked.entries(snap).values() for i in e['content_items'])==1
    assert db.get(user,old['id'],'resume_revision')==old
    assert guided.restore(user,state['id'],RevisionAction(expected_version=changed['data']['version'],revision_id=old['id']))['current']['id']==old['id']


def test_existing_draft_unchanged_until_apply_failed_render_keeps_head(env,monkeypatch):
    user,intern,contractor,project,job,session=env
    state=initial(env);before=copy.deepcopy(db.get(user,state['current']['id'],'resume_revision'))
    assert not before['data']['snapshot'].get('linked_project_placements')
    linked.candidates(user)
    assert guided.state(user,state['id'])['current']['id']==before['id']
    def fail(snap):raise ServiceError('Fictional render failure')
    monkeypatch.setattr(resume_layout,'render',fail)
    with pytest.raises(ServiceError):apply(env,state,choices(env))
    assert db.get(user,before['id'],'resume_revision')==before
    assert guided.state(user,state['id'])['current']['id']==before['id']


@pytest.mark.parametrize('change',['source','links','job','unconfirm'])
def test_changed_source_or_relationship_requires_review_before_provider(env,monkeypatch,change):
    user,intern,contractor,project,job,session=env
    state=apply(env,session,choices(env));old=choices(env)
    if change=='source':db.save(user,'experience',{**project['data'],'contribution':'Tested approximately 12 documents, with incomplete validation.'},project['id'])
    if change=='links':db.save(user,'experience',{**project['data'],'linked_employment_ids':[contractor['id']]},project['id'])
    if change=='job':db.save(user,'experience',{**intern['data'],'title':'Changed role'},intern['id'])
    if change=='unconfirm':db.save(user,'experience',{**project['data'],'confirmed':False},project['id'])
    with pytest.raises(HTTPException) as error:linked.checked(user,old)
    assert error.value.status_code==409
    async def forbidden(*a,**k):pytest.fail('Provider must not run for stale placements')
    monkeypatch.setattr(ai,'structured',forbidden)
    with pytest.raises(HTTPException):asyncio.run(guided.build(user,state['id'],state['data']['version'],'economy',manual=True))


def test_unrelated_selection_and_wording_preserved_and_omit_reset(env):
    user,intern,contractor,project,job,session=env
    state=initial(env);old=linked.entries(state['current']['data']['snapshot'])
    c=choices(env);c[1].update(placement='omit',employment_id='')
    changed=apply(env,state,c);snap=changed['current']['data']['snapshot'];rows=linked.entries(snap)
    assert rows[contractor['id']]['content_items']==old[contractor['id']]['content_items']
    assert not any(i['original'].startswith('Initially tested') for e in rows.values() for i in e['content_items'])
    restored=apply(env,changed,[])
    assert not any(i.get('project_source') for e in linked.entries(restored['current']['data']['snapshot']).values() for i in e['content_items'])
    assert len(linked.entries(restored['current']['data']['source_snapshot']) if 'source_snapshot' in restored['current']['data'] else restored['current']['data']['catalog'])>0


def test_duplicate_source_and_text_gate(env):
    user,intern,contractor,project,job,session=env
    state=apply(env,session,choices(env));snapshot=guided.source(user,state['data']);rows=linked.entries(snapshot)
    moved=next(i for i in rows[intern['id']]['content_items'] if i.get('project_source'))
    rows[contractor['id']]['content_items'].append(copy.deepcopy(moved))
    with pytest.raises(ServiceError):linked.validate_selected(snapshot)
    rows[contractor['id']]['content_items'][-1].pop('project_source')
    with pytest.raises(ServiceError):linked.validate_selected(snapshot)


def test_api_account_isolation_and_no_paid_calls(env,client,monkeypatch):
    user,intern,contractor,project,job,session=env
    async def forbidden(*a,**k):pytest.fail('Local review never dispatches a provider request')
    monkeypatch.setattr(ai,'structured',forbidden)
    assert client.get('/api/resume-conversations/'+session['id']+'/linked-evidence').status_code==200
    assert client.get('/api/resume-conversations/not-owned/linked-evidence').status_code==404
    other=client.post('/api/auth/register',json={'username':'other','password':'fictional-test-password'}).json()
    from conftest import onboard_test_account
    onboard_test_account(other)
    client.headers['X-CSRF-Token']=other['csrf']
    assert client.get('/api/resume-conversations/'+session['id']+'/linked-evidence').status_code==404
    assert linked.candidates(other['id'])==[]
    with pytest.raises(HTTPException):linked.checked(other['id'],choices(env))


def test_provider_payload_preserves_project_provenance_and_permissions(env,monkeypatch):
    user,intern,contractor,project,job,session=env
    state=apply(env,session,choices(env));snapshot=guided.source(user,state['data'])
    db.update_settings(user,{'authorized_us':'yes','sponsorship_now':'no','career_goals':'PRIVATE_GOAL_SENTINEL'})
    calls=[]
    async def model(schema,payload,*a,**kw):
        calls.append(payload)
        if schema.__name__=='DraftAudit':return {'approved':True,'issues':[]},{'estimated_token_cost_usd':0}
        rows=payload['catalog'];entries=[{'record_id':r['id'],'reason':'Relevant confirmed evidence','items':[{'item_id':i['item_id'],'text':i['text'],'priority':80,'reason':'Posting relevance'} for i in r['items']]} for r in rows if r['items'] or r['category']=='education']
        return {'headline':'','headline_evidence':[],'entries':entries,'omissions':[],'keywords':[]},{'estimated_token_cost_usd':0}
    monkeypatch.setattr(ai,'structured',model)
    asyncio.run(optimization.create(user,snapshot,None,'economy'))
    assert len(calls)==2
    row=next(r for r in calls[0]['catalog'] if r['id']==intern['id'])
    assert len([i for i in row['items'] if i.get('project_source')])==2
    assert all(i['project_source']['employment_id']==intern['id'] for i in row['items'] if i.get('project_source'))
    wire=json.dumps(calls)
    assert 'internship versus contractor' in wire and 'PRIVATE_GOAL_SENTINEL' not in wire and 'authorized_us' not in wire
    assert any(project['data']['description'] in text for text in calls[0]['evidence_sources'][project['id']])


def test_source_fingerprint_and_selected_version_survive_local_render(env):
    user,intern,contractor,project,job,session=env
    state=apply(env,initial(env),choices(env));old=state['current']['id'];snap=state['current']['data']['snapshot']
    db.save(user,'experience',{**project['data'],'contribution':'Updated source after this historical review.'},project['id'])
    rows=state['current']['data']['catalog'];included=linked.entries(snap)
    content={r['id']:[n for n,i in enumerate(r['items']) if any(v['item_id']==i['item_id'] for v in included.get(r['id'],{}).get('content_items',[]))] for r in rows}
    body=ResumeRequest(job_id=job['id'],experience_ids=snap['experience_ids'],content=content,headline=snap['headline'])
    rendered=guided.render(user,state['id'],WorkingRender(expected_version=state['data']['version'],request_token='local-edit',resume=body))
    assert rendered['current']['data']['snapshot']['linked_project_placements']==snap['linked_project_placements']
    assert db.get(user,old,'resume_revision')['data']['snapshot']==snap|{'artifacts':{'pdf':'fictional-pdf','docx':'fictional-docx'}}


def test_backup_remaps_placement_sources_and_preserves_frozen_history(env,client):
    user,intern,contractor,project,job,session=env
    state=apply(env,initial(env),choices(env))
    backup=client.get('/api/account/export').json()
    response=client.post('/api/account/import',files={'file':('linked.json',json.dumps(backup).encode(),'application/json')})
    assert response.status_code==200,response.text
    imported=next(r for r in db.list_entities(user,'resume_revision') if r['id']!=state['current']['id'] and r['data']['snapshot'].get('linked_project_placements'))
    snap=imported['data']['snapshot'];choice=snap['linked_project_placements'][0]
    assert choice['project_id']!=project['id'] and choice['employment_id']!=intern['id']
    assert db.get(user,choice['project_id'],'experience')['data']['title']==project['data']['title']
    ref=next(i['project_source'] for e in linked.entries(snap).values() for i in e['content_items'] if i.get('project_source'))
    assert ref['project_id']==choice['project_id'] and ref['employment_id']==choice['employment_id']
    assert 'linked_project_originals' not in snap
    with pytest.raises(HTTPException):linked.checked(user,snap['linked_project_placements']) # Re-imported live links require review, frozen PDF remains valid.


def test_real_document_export_retains_evidence_once(env):
    from app import documents
    user,intern,contractor,project,job,session=env
    state=apply(env,initial(env),choices(env));snap=state['current']['data']['snapshot']
    text=documents.export_resume(snap,'txt')[0].decode()
    assert text.count(project['data']['description'])==1
    assert 'project_source' not in text and 'source_fingerprint' not in text
    assert 'Business Intern' in text and 'approximately 10' in text


def test_production_pdf_contains_linked_detail_once(client,account):
    import base64,shutil
    if not shutil.which('pdftotext') or not shutil.which('soffice'):pytest.skip('Production PDF tools required')
    user=account['id']
    job=db.save(user,'experience',ExperienceItem(category='employment',title='Example Intern',organization='Fictional Employer',confirmed=True,description='Presented research findings to sponsors.').model_dump())
    project=db.save(user,'experience',ExperienceItem(category='project',title='Fictional Pipeline',confirmed=True,description='Built a local retrieval prototype for reviewing roadway documents.',linked_employment_ids=[job['id']]).model_dump())
    posting=db.save(user,'job',{'title':'Example role','description':'Review data and build tools.'})
    session=guided.start(user,ConversationStart(job_id=posting['id']))
    row=linked.candidates(user)[0]
    state=guided.place_project_evidence(user,session['id'],LinkedEvidenceReview(expected_version=session['data']['version'],placements=[{k:row[k] for k in ('project_id','item_id','source_fingerprint')}|{'placement':'employment','employment_id':job['id']}]))
    snap=guided.source(user,state['data']);content={r['id']:list(range(len(r['items']))) for r in resume_builder.catalog(snap)}
    rendered=resume_layout.render(resume_builder.select(snap,content,[job['id']]))
    lines=resume_layout.text_lines(base64.b64decode(rendered['artifacts']['pdf']));text=' '.join(line['text'] for line in lines)
    assert rendered['layout']['pages']==1 and text.count('local retrieval prototype')==1
    assert 'Fictional Pipeline' not in text and 'project_source' not in text


def test_cancelling_local_placement_never_publishes_late_render(env,client,monkeypatch):
    import threading,time
    state=initial(env);head=state['current']['id'];entered=threading.Event();release=threading.Event()
    def slow(snapshot):
        entered.set();release.wait(5)
        return {**snapshot,'layout':{'pages':1,'validated':True},'artifacts':{}}
    monkeypatch.setattr(resume_layout,'render',slow)
    task=client.post('/api/resume-conversations/'+state['id']+'/linked-evidence',json={'expected_version':state['data']['version'],'placements':choices(env)}).json()
    try:
        assert entered.wait(3)
        result=client.post('/api/tasks/'+task['task_id']+'/cancel',json={});assert result.status_code==200
    finally:release.set()
    for _ in range(100):
        value=client.get('/api/tasks/'+task['task_id']).json()
        if value['status']=='cancelled':break
        time.sleep(.01)
    assert value['status']=='cancelled'
    time.sleep(.05)
    assert guided.state(env[0],state['id'])['current']['id']==head
