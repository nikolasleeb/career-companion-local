from conftest import comparison_wire
from conftest import onboard_test_account
import asyncio
import copy
import json
import pytest
from app import ai, comparison, config, db, job_parser, role_alignment, resume_conversation as guided, optimization, profile_answers
from app.main import build_resume
from app.models import ConversationStart, ConversationMessage, ResumeRequest
from app.network import ServiceError

POSTING='''Junior Machine Learning Engineer
Requirements
Minimum GPA: 3.0
What you will do
Build, train and validate machine learning models.
Prepare and analyze large datasets.
Document your work clearly and present findings to technical audiences.
Work authorization
To be considered, you must also be a U.S. Citizen.
'''

@pytest.fixture
def role(client,account):
    job=client.post('/api/jobs',json={'title':'Machine Learning Engineer','company':'Fictional Example','description':POSTING}).json()
    record=client.post('/api/experience',json={'category':'project','title':'Fictional demand project','description':'Prepared demand data using Python and presented findings to classmates.','contribution':'I have not trained or validated a machine learning model.','gpa':'4.0','confirmed':True}).json()
    return account['id'],job,record

def output(job,record):
    qualifications=[{'criterion_id':c['id'],'keyword':c['text'],'job_quote':c['source'],'kind':c['kind'],'importance':c['importance'],'status':'supported' if c['kind']=='qualification' else 'unknown','evidence':[{'record_id':record['id'],'quote':'4.0'}] if c['kind']=='qualification' else [],'explanation':'Documented GPA.' if c['kind']=='qualification' else 'Private answer not supplied.','question':''} for c in job_parser.criteria(job)]
    duties=[]
    for c in role_alignment.catalog(job):
        status='unknown' if 'train' in c['text'] else 'partial' if 'Document' in c['text'] else 'supported'
        duties.append({'criterion_id':c['id'],'keyword':c['text'],'job_quote':c['source'],'kind':'responsibility','importance':'unclear','status':status,'evidence':[] if status=='unknown' else [{'record_id':record['id'],'quote':record['data']['description']}],'explanation':'The confirmed example shows relevant work; additional methods or writing detail may help.','question':''})
    return {'summary':'Fictional evidence review.','requirements':qualifications,'duty_assessments':duties,'job_details':[],'recommendations':[],'suggestions':[],'keywords':[],'questions':[]}

def validate(job,record,value=None,profile=None):
    value=value or output(job,record)
    return comparison.validate(value,job,[record],profile or {})

def test_sparse_qualifications_and_duties_remain_separate(role):
    _,job,record=role;result=validate(job['data'],record)
    assert result['score']['value']==100 and result['score']['coverage']['total']==1
    assert len(result['duty_assessments'])==3
    assert {d['status'] for d in result['duty_assessments']}=={'supported','partial','unknown'}
    assert all(d['assessment_complete'] and d['kind']=='responsibility' for d in result['duty_assessments'])
    assert all(c['title']=='Minimum GPA: 3.0' for c in result['score']['contributions'])
    assert result['requirements'][-1]['status']=='unknown' and result['requirements'][-1]['question']==''
    questions=role_alignment.initial_questions(result,job['data'])
    assert len(questions)==2 and all(q['topic']=='job_duty' for q in questions)
    assert any('model' in q['text'] for q in questions) and any('written documentation' in q['text'] for q in questions)
    assert not any('citizen' in q['text'] for q in questions)


def test_no_qualifications_uses_unheaded_job_duties_without_score(role):
    _,_,record=role
    job={'description':'You will build analytical tools for engineers.\nYou will document the workflow and present findings.\nWe offer great benefits.'}
    duties=role_alignment.catalog(job)
    assert len(duties)==2 and all(d['source'] in job['description'] for d in duties)
    value=output(job,record)
    for duty in value['duty_assessments']:duty.update(status='unknown',evidence=[])
    result=validate(job,record,value)
    assert result['score']['value'] is None and result['score']['coverage']['total']==0
    assert len(result['duty_assessments'])==2 and role_alignment.initial_questions(result,job)

@pytest.mark.parametrize('tamper',['reference','posting','profile','private','missing','conflict'])
def test_duty_sources_and_statuses_fail_closed(role,tamper):
    _,job,record=role;value=output(job['data'],record);d=value['duty_assessments'][0]
    if tamper=='reference':d['criterion_id']='not-in-posting'
    elif tamper=='posting':d['job_quote']='Invented company duty.'
    elif tamper=='profile':d.update(status='supported',evidence=[{'record_id':record['id'],'quote':'Invented work.'}])
    elif tamper=='private':d.update(status='supported',evidence=[{'record_id':'profile:us_citizen','quote':'us_citizen = yes'}])
    elif tamper=='missing':d.update(status='supported',evidence=[])
    elif tamper=='conflict':d.update(status='not_met',evidence=[{'record_id':record['id'],'quote':record['data']['description']}])
    with pytest.raises(ServiceError):validate(job['data'],record,value,{'us_citizen':'yes'})


def test_explicit_duty_limitation_never_reduces_qualification_score(role):
    _,job,record=role;value=output(job['data'],record)
    value['duty_assessments'][0].update(status='not_met',evidence=[{'record_id':record['id'],'quote':record['data']['contribution']}])
    result=validate(job['data'],record,value)
    assert result['duty_assessments'][0]['status']=='not_met' and result['score']['value']==100

@pytest.mark.parametrize('answer,status',[('yes','supported'),('no','not_met'),('unsure','unknown'),('','unknown')])
def test_citizenship_is_explicit_private_eligibility_not_authorization(role,client,answer,status):
    user,job,record=role
    assert client.put('/api/settings',json={'us_citizen':answer,'authorized_us':'yes'}).status_code==200
    result=validate(job['data'],record,profile=db.settings(user))
    citizen=next(r for r in result['requirements'] if 'Citizen' in r['keyword'])
    assert citizen['status']==status and citizen['question']=='' and result['score']['value']==100
    assert all(e['record_id']=='profile:us_citizen' for e in citizen['evidence'])
    assert client.put('/api/settings',json={'us_citizen':'inferred'}).status_code==422


def test_private_citizenship_backup_isolated_and_absent_from_employer_sources(role,client):
    user,job,record=role
    client.put('/api/settings',json={'us_citizen':'yes'})
    snapshot=build_resume(user,ResumeRequest(job_id=job['id'],experience_ids=[record['id']]))
    assert 'us_citizen' not in json.dumps(snapshot) and 'citizenship' not in json.dumps(profile_answers.records(user)).lower()
    backup=client.get('/api/account/export').json();assert backup['profile']['us_citizen']=='yes'
    client.put('/api/settings',json={'us_citizen':''})
    assert client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')}).status_code==200
    assert db.settings(user)['us_citizen']=='yes'
    other=client.post('/api/auth/register',json={'username':'role-other','password':'fictional-password'}).json()
    assert other['settings'].get('us_citizen','')==''


def test_legacy_review_is_read_only_and_account_scoped(role,client):
    user,job,record=role;value=output(job['data'],record);value.pop('duty_assessments')
    saved=db.save(user,'analysis',{**value,'job_id':job['id'],'posting_snapshot':job['data'],'schema_version':3})
    before=copy.deepcopy(saved)
    response=client.get('/api/analyses/'+saved['id']+'/role-alignment').json()
    assert not response['assessed'] and len(response['duties'])==3
    assert all(d['status']=='unknown' and not d['evidence'] for d in response['duties'])
    assert db.get(user,saved['id'],'analysis')==before
    other=client.post('/api/auth/register',json={'username':'role-endpoint-other','password':'fictional-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
    onboard_test_account(other)
    assert client.get('/api/analyses/'+saved['id']+'/role-alignment').status_code==404


def test_question_upgrade_preserves_existing_answers_and_deduplicates(role):
    user,job,record=role
    legacy=guided.start(user,ConversationStart(job_id=job['id']))
    def old(data,c):
        data['questions']=[{'text':'Is there a relevant project or accomplishment you want this resume to emphasize? What did you personally do, and who used the work?','criterion_id':None}]
        data['asked_questions']=copy.deepcopy(data['questions'])
    guided.mutate(user,legacy['id'],legacy['data']['version'],old)
    result=validate(job['data'],record)
    saved=db.save(user,'analysis',{**result,'job_id':job['id']})
    state=guided.start(user,ConversationStart(job_id=job['id'],analysis_id=saved['id']))
    assert len([q for q in state['data']['asked_questions'] if q.get('topic')=='job_duty'])==2
    assert state['data']['asked_questions'][0]['status']=='superseded'
    before=state['data']['asked_questions']
    again=guided.start(user,ConversationStart(job_id=job['id'],analysis_id=saved['id']))
    assert again['data']['asked_questions']==before
    def answered(data,c):
        q=data['asked_questions'][1];q.update(answer='My saved draft answer.',answer_version=1)
    state=guided.mutate(user,state['id'],state['data']['version'],answered)
    newer=db.save(user,'analysis',{**result,'job_id':job['id']})
    after=guided.start(user,ConversationStart(job_id=job['id'],analysis_id=newer['id']))
    assert len(after['data']['asked_questions'])==3
    assert after['data']['asked_questions'][1]['answer']=='My saved draft answer.'


def test_comparison_prompt_has_separate_catalogs_and_no_external_tools(role,client,monkeypatch):
    user,job,record=role;calls=[]
    client.put('/api/settings',json={'us_citizen':'yes'})
    async def fake(body):
        calls.append(body)
        return {'output':[{'content':[{'type':'output_text','text':json.dumps(comparison_wire(output(job['data'],record),job['data'],json.loads(body['input'])))}]}]}
    monkeypatch.setattr(ai,'call_api',fake)
    token=ai.set_user_context(user)
    try:result=asyncio.run(ai.analyze(user,job['data'],'economy'))
    finally:ai.reset_user_context(token)
    payload=json.loads(calls[0]['input'])
    assert len(payload['duty_catalog'])==3 and len(payload['criterion_catalog'])==2
    assert payload['private_eligibility_catalog'][0]['record_id']=='profile:us_citizen'
    assert payload['private_eligibility_catalog'][0]['quote']=='us_citizen = yes'
    assert 'tools' not in calls[0] and result['duty_alignment_version']==1


def test_duty_gaps_reach_resume_drafting_and_chat_without_private_eligibility(role,monkeypatch):
    user,job,record=role;result=validate(job['data'],record,profile={'us_citizen':'yes'})
    saved=db.save(user,'analysis',{**result,'job_id':job['id']})
    session=guided.start(user,ConversationStart(job_id=job['id'],analysis_id=saved['id']))
    snapshot=build_resume(user,ResumeRequest(job_id=job['id'],analysis_id=saved['id'],experience_ids=[record['id']]))
    calls=[]
    async def inspect(schema,payload,*args,**kwargs):
        calls.append((schema.__name__,payload))
        if schema.__name__=='ResumeChatOutput':return {'message':'Please describe the model validation work.','questions':[],'proposals':[],'action':'question','revision_instruction':'','target_item_ids':[],'target_record_ids':[],'change_headline':False,'change_selection':False,'template':'unchanged'},{}
        raise ServiceError('Stop after inspecting deterministic test payload.')
    monkeypatch.setattr(ai,'structured',inspect)
    with pytest.raises(ServiceError):asyncio.run(optimization.create(user,snapshot,result,'economy'))
    payload=calls[-1][1]
    assert len(payload['duty_alignment'])==3
    assert all(r['kind']=='qualification' for r in payload['qualifications'])
    assert 'us_citizen' not in json.dumps(payload)
    asyncio.run(guided.send(user,session['id'],ConversationMessage(expected_version=session['data']['version'],text='What model details would help?')))
    payload=calls[-1][1]
    assert len(payload['duty_alignment'])==3 and len(payload['criterion_catalog'])==5
    assert any('model' in q['text'] for q in role_alignment.initial_questions(result,job['data']))


def test_question_seeding_waits_for_an_active_draft_task(role):
    user,job,record=role
    session=guided.start(user,ConversationStart(job_id=job['id']))
    saved=db.save(user,'analysis',{**validate(job['data'],record),'job_id':job['id']})
    stamp=db.now()
    with db.connect() as c:
        c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',('pending-duty-draft',user,'resume_guided','running',json.dumps({'inputs':{'conversation_id':session['id']}}),None,stamp,stamp))
    same=guided.start(user,ConversationStart(job_id=job['id'],analysis_id=saved['id']))
    assert same['data']['version']==session['data']['version'] and same['data']['analysis_id'] is None
    with db.connect() as c:c.execute("UPDATE tasks SET status='completed' WHERE id='pending-duty-draft'")
    later=guided.start(user,ConversationStart(job_id=job['id'],analysis_id=saved['id']))
    assert later['data']['analysis_id']==saved['id'] and later['data']['version']>same['data']['version']


def test_initial_questions_wait_for_comparison_and_reading_is_free(role,monkeypatch):
    user,job,record=role
    assert role_alignment.initial_questions(None,job['data'])==[]
    async def forbidden(*args,**kwargs):raise AssertionError('No provider calls before comparison')
    monkeypatch.setattr(ai,'structured',forbidden)
    state=guided.start(user,ConversationStart(job_id=job['id']))
    assert state['data']['asked_questions']==[] and state['data']['questions']==[]


def test_completed_comparison_replaces_legacy_generic_gaps_and_keeps_typed_answers(role):
    user,job,record=role
    state=guided.start(user,ConversationStart(job_id=job['id']))
    duties=role_alignment.catalog(job['data'])
    def old(data,c):
        prompts=[role_alignment.question(d) for d in duties]
        # Include an answer that must stay editable, even when its duty is now supported.
        prompts[1].update(answer='Retain this typed answer.',answer_version=1)
        data['questions']=prompts;data['asked_questions']=copy.deepcopy(prompts)
        data['question_context']='old-comparison:duties:1'
    state=guided.mutate(user,state['id'],state['data']['version'],old)
    result=validate(job['data'],record)
    result['duty_assessments'][0]['question']='Which regression model and validation split did you personally implement?'
    saved=db.save(user,'analysis',{**result,'job_id':job['id']})
    after=guided.start(user,ConversationStart(job_id=job['id'],analysis_id=saved['id']))
    questions=after['data']['asked_questions']
    assert questions[0]['status']=='superseded'
    assert questions[1]['answer']=='Retain this typed answer.' and questions[1]['status']!='superseded'
    assert any(q['text'].startswith('Which regression') and q['status']!='superseded' for q in questions)
    writing=next(q for q in questions if 'written documentation' in q['text'] and q['status']!='superseded')
    assert writing['profile_evidence'][0]['record_id']==record['id']
    assert writing['profile_evidence'][0]['quote']==record['data']['description']
    assert guided.start(user,ConversationStart(job_id=job['id'],analysis_id=saved['id']))['data']['asked_questions']==questions


def test_fully_supported_comparison_retires_unanswered_seed_prompts(role):
    user,job,record=role;state=guided.start(user,ConversationStart(job_id=job['id']))
    def old(data,c):
        q=role_alignment.question(role_alignment.catalog(job['data'])[0]);data['questions']=[q];data['asked_questions']=[copy.deepcopy(q)]
    state=guided.mutate(user,state['id'],state['data']['version'],old)
    value=output(job['data'],record)
    for r in value['duty_assessments']:r.update(status='supported',evidence=[{'record_id':record['id'],'quote':record['data']['description']}],question='')
    saved=db.save(user,'analysis',{**validate(job['data'],record,value),'job_id':job['id']})
    result=guided.start(user,ConversationStart(job_id=job['id'],analysis_id=saved['id']))
    assert result['data']['questions']==[]
    assert result['data']['asked_questions'][0]['status']=='superseded'


def test_ai_first_actions_require_comparison_before_starting_tasks(role,client,monkeypatch):
    user,job,record=role;state=guided.start(user,ConversationStart(job_id=job['id']))
    monkeypatch.setattr(config,'OPENAI_KEY','fictional-never-sent')
    async def forbidden(*args,**kwargs):raise AssertionError('Locked action must not reach a provider')
    monkeypatch.setattr(ai,'structured',forbidden)
    for action,body in [('build',{'expected_version':state['data']['version']}),('messages',{'expected_version':state['data']['version'],'text':'Write a draft'}),('answers/review',{'expected_version':state['data']['version'],'question_ids':['not-yet-created']})]:
        result=client.post('/api/resume-conversations/'+state['id']+'/'+action,json=body)
        assert result.status_code==409 and 'Compare your Profile' in result.text
    with db.connect() as c:assert c.execute('SELECT count(*) FROM tasks WHERE user_id=?',(user,)).fetchone()[0]==0


def test_saved_profile_picker_only_returns_confirmed_owned_professional_evidence(role,client):
    user,job,record=role
    db.save(user,'experience',{'title':'Unreviewed secret','category':'project','confirmed':False})
    client.put('/api/settings',json={'us_citizen':'yes','sponsorship_now':'no'})
    result=client.get('/api/profile-evidence');assert result.status_code==200
    assert [r['id'] for r in result.json()]==[record['id']]
    assert 'Unreviewed secret' not in result.text and 'us_citizen' not in result.text
    other=client.post('/api/auth/register',json={'username':'evidence-picker-other','password':'fictional-password'}).json()
    client.headers['X-CSRF-Token']=other['csrf']
    assert client.get('/api/profile-evidence').json()==[]
    client.post('/api/auth/logout');assert client.get('/api/profile-evidence').status_code==401


def test_starting_with_a_comparison_never_duplicates_question_ids(role):
    user,job,record=role
    saved=db.save(user,'analysis',{**validate(job['data'],record),'job_id':job['id']})
    state=guided.start(user,ConversationStart(job_id=job['id'],analysis_id=saved['id']))
    qs=state['data']['asked_questions']
    assert len(qs)==len({q['id'] for q in qs})==2
    assert all(q['status']=='open' for q in qs)
