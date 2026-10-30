from conftest import without_setup
from conftest import cached_posting_fixture
import asyncio
import copy
import json
import pytest
from fastapi import HTTPException
from app import ai,db,config,project_context as pc,project_sources as ps,profile_answers as library,resume_conversation as resumes,question_answers,cover_context,cover_letters
from app.models import ConversationStart,ConversationMessage,AnswerBatchReview,FactApproval,CoverGenerate,CoverContent,CoverContextReview,CoverReviewDecision,ResumeChatOutput
from app.network import ServiceError
from test_connected_workflow import save_answer
from test_comparison_catalog_contract import POSTING,wire
from test_applications_workflow import wait_task
from test_cover_letters import env
from test_cover_guided import guided

def project(client,user,title='Demand study',linked=True):
    record=client.post('/api/experience',json={'category':'project','title':title,'description':'Prepared data.','gpa':'4.0','confirmed':True}).json()
    snapshot=client.post('/api/project-sources/paste',json={'title':title,'text':'Notebook contains a fitted model and a validation report.','experience_id':record['id'] if linked else ''}).json()
    finding={'file_path':snapshot['data']['files'][0]['file_path'],'quote':'a fitted model','observation':'Contains model-fitting code.','line_start':1,'line_end':1}
    analysis=db.save(user,'project_analysis',{'snapshot_id':snapshot['id'],'summary':'Project materials document modeling and validation.','findings':[finding],'schema_version':2})
    return record,snapshot,analysis

def resume_with_question(client,user,refs):
    job=client.post('/api/jobs',json={'title':'ML Engineer','description':POSTING}).json()
    job=cached_posting_fixture(user,job)
    state=resumes.start(user,ConversationStart(job_id=job['id']))
    def seed(data,c):
        q={'text':'Which validation checks did you personally run for this modeling project?','reason':'Clarify model validation for this posting.','project_refs':refs}
        data['questions']=[q];data['asked_questions']=[copy.deepcopy(q)]
    state=resumes.mutate(user,state['id'],state['data']['version'],seed)
    return resumes.state(user,state['id']),job

def answer_model(monkeypatch,record,calls):
    async def fake(schema,payload,*args,**kwargs):
        calls.append(payload);text=payload['submitted_question_answers'][0]['answer']
        return {'message':'Review your project detail.','questions':[],'project_questions':[],'proposals':[{'record_id':record['id'],'category':'project','title':record['data']['title'],'fields':[{'field':'contribution','value':text,'user_quote':text}],'reason':'Clarifies validation.','criterion_ids':[]}],'action':'facts','revision_instruction':'','target_item_ids':[],'target_record_ids':[],'change_headline':False,'change_selection':False},{'model':'mock','estimated_token_cost_usd':0}
    monkeypatch.setattr(ai,'structured',fake)

def test_profile_analysis_has_no_questions_no_new_draft_and_one_dispatch(client,account,monkeypatch):
    monkeypatch.setattr(config,'OPENAI_KEY','fictional-no-network');record,snap,old=project(client,account['id'])
    legacy=db.save(account['id'],'answer_draft',{'version':1,'status':'draft','builder':'project','title':'Old notes','text':'My typed notes.','contribution':'','experience_id':record['id'],'snapshot_id':snap['id'],'analysis_id':old['id'],'questions':[{'id':'old','text':'What did you do?'}],'question_answers':{'old':'I wrote the report.'},'findings':[],'history':[]})
    calls=[]
    async def provider(body,**kwargs):
        assert kwargs.get('retry_allowed') is False
        calls.append(body);payload=json.loads(body['input']);assert 'Do not ask applicant questions' in payload['task']
        assert set(body['text']['format']['schema']['properties'])=={'summary','findings'}
        return {'output':[{'content':[{'type':'output_text','text':json.dumps({'summary':'Materials describe modeling.','findings':old['data']['findings'] and [{k:v for k,v in old['data']['findings'][0].items() if k in ('file_path','quote','observation')}]})}]}]}
    monkeypatch.setattr(ai,'call_api',provider)
    endpoint='/api/project-snapshots/'+snap['id']+'/analyze';body={'request_token':'one-analysis-only'}
    result=wait_task(client,client.post(endpoint,json=body));assert result['status']=='completed',result
    assert result['result']['draft'] is None and 'questions' not in result['result']['analysis']['data']
    assert wait_task(client,client.post(endpoint,json=body))['id']==result['id'] and len(calls)==1
    assert db.list_entities(account['id'],'answer_draft')==[legacy]
    assert db.get(account['id'],record['id'],'experience')==record and not library.confirmed(account['id'])

def test_automatic_context_latest_linked_analysis_not_unlinked_or_unconfirmed(client,account,monkeypatch):
    user=account['id'];record,snap,analysis=project(client,user)
    _,unlinked,_=project(client,user,'Unlinked materials',False)
    other,other_snap,_=project(client,user,'Unconfirmed')
    db.save(user,'experience',{**other['data'],'confirmed':False},other['id'])
    newer=db.save(user,'project_analysis',{**analysis['data'],'summary':'Most recent analysis.'})
    async def forbidden(*args,**kwargs):raise AssertionError('No network or AI for saved context')
    monkeypatch.setattr(ps,'github',forbidden);monkeypatch.setattr(ai,'structured',forbidden)
    rows=pc.catalog(user,{})
    assert len(rows)==1 and rows[0]['analysis_id']==newer['id'] and rows[0]['experience_id']==record['id']
    assert not rows[0]['files'] and rows[0]['findings'] and 'not confirmed' in rows[0]['notice']
    explicit=pc.catalog(user,{'project_snapshot_ids':[unlinked['id']]})
    assert any(r['snapshot_id']==unlinked['id'] and r['files'] and not r['experience_id'] for r in explicit)
    db.save(user,'project_snapshot',{**snap['data'],'archived':True},snap['id'])
    assert not pc.catalog(user,{})

def test_material_context_and_refs_are_account_owned(client,account):
    _,snap,analysis=project(client,account['id']);old=pc.catalog(account['id'],{})
    other=client.post('/api/auth/register',json={'username':'other-context','password':'fictional-other-password'}).json()
    assert not pc.catalog(other['id'],{'project_snapshot_ids':[snap['id']]})
    with pytest.raises(ServiceError):pc.references([analysis['id']],pc.catalog(other['id'],{}))
    with pytest.raises(ServiceError):pc.references([analysis['id'],analysis['id']],old)

def test_project_observations_inform_comparison_questions_but_never_evidence(client,account,monkeypatch):
    user=account['id'];record,snap,analysis=project(client,user);monkeypatch.setattr(config,'OPENAI_KEY','fictional-no-network')
    job=client.post('/api/jobs',json={'title':'ML Engineer','description':POSTING}).json();calls=[]
    job=cached_posting_fixture(user,job)
    async def provider(body):
        calls.append(body);payload=json.loads(body['input']);context=payload['project_material_for_questions_only'];assert context[0]['analysis_id']==analysis['id']
        assert not any(s['quote']=='Contains model-fitting code.' for s in payload['professional_evidence_catalog'])
        value=wire(payload,record);duty=value['duty_assessments'][0]
        duty.update(question='What model validation did you personally run in Demand study?',project_context_ids=[context[0]['context_id']])
        return {'output':[{'content':[{'type':'output_text','text':json.dumps(value)}]}]}
    monkeypatch.setattr(ai,'call_api',provider)
    task=wait_task(client,client.post('/api/analyses',json={'job_id':job['id']}));assert task['status']=='completed',task
    result=task['result'];duty=result['data']['duty_assessments'][0]
    assert len(calls)==1 and duty['status']=='unknown' and duty['evidence']==[] and duty['project_refs'][0]['snapshot_id']==snap['id']
    state=resumes.start(user,ConversationStart(job_id=job['id'],analysis_id=result['id']))
    assert any(q.get('project_refs') and q['project_refs'][0]['experience_id']==record['id'] for q in state['data']['questions'])
    assert not library.confirmed(user)

@pytest.mark.parametrize('ambiguous',[False,True])
def test_resume_review_saves_linked_evidence_without_mutating_project(client,account,monkeypatch,ambiguous):
    user=account['id'];record,snap,analysis=project(client,user);context=pc.catalog(user,{})
    target=record
    if ambiguous:
        target,_,_=project(client,user,'Extension study');context=pc.catalog(user,{})
    refs=pc.references([r['context_id'] for r in context],context)
    state,job=resume_with_question(client,user,refs);text='I ran time-ordered validation and inspected residual plots.'
    state=save_answer(user,state,'resume',text);q=state['data']['asked_questions'][0]
    assert not library.confirmed(user) and db.get(user,record['id'],'experience')==record
    calls=[];answer_model(monkeypatch,record,calls)
    state=asyncio.run(question_answers.review(user,state['id'],'resume',AnswerBatchReview(expected_version=state['data']['version'],question_ids=[q['id']])))
    p=state['data']['proposals'][0];assert p['evidence_only'] and p['project_refs']==refs
    assert p['evidence_experience_id']==('' if ambiguous else record['id'])
    if ambiguous:
        with pytest.raises(HTTPException,match='Choose the confirmed'):
            resumes.approve(user,state['id'],FactApproval(expected_version=state['data']['version'],proposal_id=p['id'],action='approve',update_draft=False))
    state=resumes.approve(user,state['id'],FactApproval(expected_version=state['data']['version'],proposal_id=p['id'],action='approve',evidence_experience_id=target['id'],update_draft=False))
    entry=library.confirmed(user)[0]
    assert entry['data']['experience_id']==target['id'] and entry['data']['backed_fields']=={}
    assert entry['data']['sources'][0]['questions'][0]['id']==q['id'] and entry['data']['sources'][0]['project_refs']==refs
    assert db.get(user,record['id'],'experience')==record and db.get(user,target['id'],'experience')==target
    assert text in next(r['data']['contribution'] for r in without_setup(library.records(user)) if r['id']==target['id'])
    asyncio.run(question_answers.review(user,state['id'],'resume',AnswerBatchReview(expected_version=state['data']['version'],question_ids=[q['id']])))
    assert len(calls)==1

def test_resume_followup_uses_saved_project_ids_without_profile_edit(client,account,monkeypatch):
    user=account['id'];record,snap,analysis=project(client,user);state,_=resume_with_question(client,user,[])
    async def model(schema,payload,*args,**kwargs):
        context=payload['unreviewed_project_material_for_questions_only'];assert context[0]['analysis_id']==analysis['id']
        return {'message':'Clarify the validation.','questions':[],'project_questions':[{'text':'What validation did you personally run for this model?','project_context_ids':[analysis['id']]}],'proposals':[],'action':'question','revision_instruction':'','target_item_ids':[],'target_record_ids':[],'change_headline':False,'change_selection':False},{'model':'mock'}
    monkeypatch.setattr(ai,'structured',model)
    state=asyncio.run(resumes.send(user,state['id'],ConversationMessage(expected_version=state['data']['version'],text='Which project details would help?')))
    assert state['data']['questions'][0]['project_refs'][0]['experience_id']==record['id'] and not library.confirmed(user)

def test_cover_question_answer_and_review_keep_project_link_and_motivation_separate(guided,client,monkeypatch):
    user,job,resume,state,_=guided;record,snap,analysis=project(client,user);calls=[]
    async def model(schema,payload,*args,**kwargs):
        calls.append(payload)
        if schema.__name__=='CoverQuestionsOutput':
            assert payload['unreviewed_project_material_for_questions_only'][0]['analysis_id']==analysis['id']
            return {'message':'A project example could help.','questions':[{'text':'Which validation work was yours in Demand study?','purpose':'Develop a relevant project story.','topic':'contribution','source_ids':[],'guidance_ids':[],'job_quote':'','project_context_ids':[analysis['id']]}]},{'model':'mock'}
        text=payload['submitted_question_answers'][0]['answer'];q=payload['questions'][0]
        return {'action':'collect','reply':'Review this project detail.','answered_question_ids':[q['id']],'skipped_question_ids':[],'details':[{'kind':'experience','user_quote':text,'title':'Validation work','question_ids':[q['id']],'related_source_id':'','supersedes_id':'','profile_category':'project'}],'followup_questions':[],'revision_instruction':'','paragraph_indices':[],'revise_all':False,'header_style':'unchanged','subject':'unchanged'},{'model':'mock'}
    monkeypatch.setattr(ai,'structured',model)
    state=asyncio.run(cover_context.prepare(user,state['id'],CoverGenerate(expected_version=state['data']['version'],content=CoverContent.model_validate(state['data']['content']))))
    assert state['data']['questions'][0]['project_refs'][0]['experience_id']==record['id']
    state=save_answer(user,state,'cover','I ran the validation notebook and reviewed its errors.')
    q=state['data']['questions'][0]
    state=asyncio.run(question_answers.review(user,state['id'],'cover',AnswerBatchReview(expected_version=state['data']['version'],question_ids=[q['id']])))
    p=state['data']['context_proposals'][0];assert p['evidence_only'] and p['evidence_experience_id']==record['id']
    state=asyncio.run(cover_context.review(user,state['id'],CoverContextReview(expected_version=state['data']['version'],content=CoverContent.model_validate(state['data']['content']),build=False,decisions=[CoverReviewDecision(proposal_id=p['id'],action='approve')])))
    entry=library.confirmed(user)[0]
    assert entry['data']['experience_id']==record['id'] and entry['data']['sources'][0]['project_refs'][0]['analysis_id']==analysis['id']
    assert db.get(user,record['id'],'experience')==record and db.get(user,resume['id'],'resume')==resume
    assert len(calls)==2

def test_project_evidence_backup_restores_provenance_and_rejects_foreign_reference(client,account,monkeypatch):
    test_resume_review_saves_linked_evidence_without_mutating_project(client,account,monkeypatch,False)
    backup=client.get('/api/account/export').json();source=next(r for r in backup['records'] if r['kind']=='profile_answer')['data']['sources'][0]
    assert source['project_refs'][0]['analysis_id']
    bad=copy.deepcopy(backup);next(r for r in bad['records'] if r['kind']=='profile_answer')['data']['sources'][0]['project_refs'][0]['snapshot_id']='foreign-snapshot'
    assert client.post('/api/account/import',files={'file':('bad.json',json.dumps(bad),'application/json')}).status_code==400
    other=client.post('/api/auth/register',json={'username':'project-restore','password':'fictional-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
    restored=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup),'application/json')});assert restored.status_code==200,restored.text
    entry=library.confirmed(other['id'])[0];ref=entry['data']['sources'][0]['project_refs'][0]
    assert db.get(other['id'],ref['snapshot_id'],'project_snapshot') and db.get(other['id'],ref['analysis_id'],'project_analysis')
    assert db.get(other['id'],entry['data']['experience_id'],'experience')

def test_reuse_approved_answer_suppresses_same_project_question_but_not_new_followup(client,account,monkeypatch):
    test_resume_review_saves_linked_evidence_without_mutating_project(client,account,monkeypatch,False)
    entry=library.confirmed(account['id'])[0];question=entry['data']['sources'][0]['questions'][0]
    refs=entry['data']['sources'][0]['project_refs']
    repeated={'text':question['text'],'project_refs':refs}
    useful={'text':'What other validation decision could support the new posting?','project_refs':refs}
    assert pc.fresh_questions(account['id'],[repeated,useful])==[useful]
    another={**repeated,'project_refs':[{**refs[0],'experience_id':'different-project'}]}
    assert pc.fresh_questions(account['id'],[another])==[another]
    assert entry in library.reusable(account['id'],'another-opportunity')

def test_project_destination_requires_current_owned_confirmed_project(client,account):
    user=account['id'];record,_,_=project(client,user)
    p={'record_id':record['id'],'evidence_experience_id':record['id'],'expected_updated_at':record['updated_at']}
    db.save(user,'experience',{**record['data'],'description':'Newer manual edit.'},record['id'])
    with db.connect() as c:
        with pytest.raises(HTTPException,match='changed'):pc.destination(c,user,p)
        with pytest.raises(HTTPException,match='Choose the confirmed'):pc.destination(c,user,p,'foreign-project')

def test_motivation_is_not_bound_as_project_experience(client,account):
    record,_,_=project(client,account['id']);context=pc.catalog(account['id'],{});refs=pc.references([context[0]['context_id']],context)
    proposal={'kind':'motivation','question_ids':['why'],'profile_record_id':record['id']}
    pc.bind_proposal(account['id'],{'questions':[{'id':'why','text':'Why this company?','project_refs':refs}]},proposal,'cover')
    assert not proposal.get('evidence_only')

def test_changed_repository_links_do_not_automatically_reuse_another_snapshot(client,account):
    user=account['id'];record,snap,analysis=project(client,user)
    db.save(user,'project_snapshot',{**snap['data'],'provider':'github','urls':['https://github.com/example/old']},snap['id'])
    db.save(user,'experience',{**record['data'],'project_url':'https://github.com/example/new','project_urls':['https://github.com/example/new']},record['id'])
    assert not pc.catalog(user,{})
    assert pc.catalog(user,{'project_snapshot_ids':[snap['id']]})[0]['analysis_id']==analysis['id']

def test_foreign_project_question_ids_and_fabricated_material_evidence_fail_closed(client,account):
    record,_,_=project(client,account['id']);context=pc.catalog(account['id'],{})
    with pytest.raises(ServiceError):pc.attach_assessments({'duty_assessments':[{'kind':'responsibility','question':'What did you do?','project_context_ids':['foreign-analysis']}]},context)
    with pytest.raises(ServiceError):
        pc.attach_assessments({'requirements':[{'kind':'eligibility','question':'Are you eligible?','project_context_ids':[context[0]['context_id']]}]},context)
    from app import comparison
    with pytest.raises(ServiceError):comparison.attach_evidence_sources({'duty_assessments':[{'evidence':[{'source_id':context[0]['context_id']}]}]},comparison.evidence_catalog([record],{}))

def test_explicit_unlinked_material_requires_a_related_project(client,account,monkeypatch):
    user=account['id'];record,snap,analysis=project(client,user,linked=False)
    context=pc.catalog(user,{'project_snapshot_ids':[snap['id']]});refs=pc.references([analysis['id']],context)
    state,_=resume_with_question(client,user,refs)
    state=save_answer(user,state,'resume','I ran the validation checks for my independent study.')
    calls=[];answer_model(monkeypatch,{'id':'','data':{'title':'Independent validation'}},calls)
    q=state['data']['asked_questions'][0]
    state=asyncio.run(question_answers.review(user,state['id'],'resume',AnswerBatchReview(expected_version=state['data']['version'],question_ids=[q['id']])))
    p=state['data']['proposals'][0];assert p['evidence_only'] and p['allow_standalone']
    with pytest.raises(HTTPException):resumes.approve(user,state['id'],FactApproval(expected_version=state['data']['version'],proposal_id=p['id'],action='approve',keep_standalone=True,update_draft=False))
    assert not library.confirmed(user)
    assert without_setup(db.list_entities(user,'experience'))==[record] and len(calls)==1
