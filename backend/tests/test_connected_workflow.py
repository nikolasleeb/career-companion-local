from conftest import without_setup
from conftest import onboard_test_account
import asyncio
import copy
import json
import pytest
from fastapi import HTTPException
from app import ai,db,applications,profile_answers as library,question_answers,resume_conversation as resumes,cover_letters as letters
from app.models import *
from app.network import ServiceError
from test_cover_letters import env,generate
from test_cover_guided import guided,prepare,answer,review
from test_applications_workflow import wait_task


def save_answer(user,state,builder,text,question=None):
    qs=state['data'].get('asked_questions') if builder=='resume' else state['data']['questions']
    if not qs and builder=='resume':
        # This persistence test supplies a question independently of paid comparison.
        def seed(data,c):
            data['questions']=[{'text':'What report did you write?', 'criterion_id':None}];data['asked_questions']=copy.deepcopy(data['questions'])
        resumes.mutate(user,state['id'],state['data']['version'],seed);state=resumes.state(user,state['id']);qs=state['data']['asked_questions']
    q=question or qs[0]
    return question_answers.save(user,state['id'],builder,AnswerDraftSave(expected_version=state['data']['version'],answers=[InlineAnswer(question_id=q['id'],text=text,expected_answer_version=q.get('answer_version',0))]))


def test_start_workflow_is_preparing_repeat_safe_and_posting_scoped(guided,client):
    user,job,resume,state,calls=guided
    initial=client.post('/api/applications/start',json={'job_id':job['id']}).json()
    assert initial['data']['status']=='preparing'
    again=client.post('/api/applications/start',json={'job_id':job['id']}).json();assert again['id']==initial['id']
    another=client.post('/api/jobs',json=job['data']).json()
    second=client.post('/api/applications/start',json={'job_id':another['id']}).json()
    assert second['id']!=initial['id']
    counts=client.get('/api/applications/dashboard').json()['counts'];assert counts['preparing']==2 and counts['submitted']==0
    response=client.put('/api/applications/'+initial['id']+'/workflow',json={'expected_updated_at':initial['updated_at'],'workflow':{'step':'cover','resume_id':resume['id']}})
    assert response.status_code==200,response.text
    value=response.json();assert value['data']['submitted_resume_id']=='' and value['data']['workflow']['resume_id']==resume['id']
    assert client.put('/api/applications/'+initial['id']+'/workflow',json={'expected_updated_at':initial['updated_at'],'workflow':{'step':'resume'}}).status_code==409
    assert client.put('/api/applications/'+second['id']+'/workflow',json={'expected_updated_at':second['updated_at'],'workflow':{'step':'cover','resume_id':resume['id']}}).status_code==400


def test_agent_requires_saved_letter_or_explicit_skip_and_keeps_submission(guided,client):
    user,job,resume,_,calls=guided;app=applications.start(user,job['id'])
    submitted={**app['data'],'submitted_resume_id':resume['id'],'status':'interviewing','applied_date':'2026-10-01'};db.save(user,'application',submitted,app['id']);app=db.get(user,app['id'],'application')
    payload={'expected_updated_at':app['updated_at'],'workflow':{'step':'agent','resume_id':resume['id']}}
    assert client.put('/api/applications/'+app['id']+'/workflow',json=payload).status_code==400
    payload['workflow']['cover_skipped']=True
    response=client.put('/api/applications/'+app['id']+'/workflow',json=payload);assert response.status_code==200,response.text
    assert response.json()['data']['status']=='interviewing' and response.json()['data']['submitted_resume_id']==resume['id']
    state=generate(guided);state=letters.finalize(user,state['id'],FinalizeRevision(expected_version=state['data']['version'],revision_id=state['current']['id'],reviewed=True))
    app=db.get(user,app['id'],'application');letter=state['data']['last_saved_letter_id']
    response=client.put('/api/applications/'+app['id']+'/workflow',json={'expected_updated_at':app['updated_at'],'workflow':{'step':'agent','resume_id':resume['id'],'cover_letter_id':letter}})
    assert response.status_code==200,response.text
    assert response.json()['data']['workflow']['cover_letter_id']==letter


def test_inline_answers_save_without_ai_and_recover_with_stable_ids(guided,client,monkeypatch):
    state=prepare(guided);q=state['data']['questions'][0];calls=len(guided[-1])
    state=save_answer(guided[0],state,'cover','I am interested in analysis that supports planning.')
    assert len(guided[-1])==calls and not state['current']
    loaded=client.get('/api/cover-workspaces/'+state['id']).json()
    assert loaded['data']['questions'][0]['id']==q['id'] and loaded['data']['questions'][0]['answer'].startswith('I am interested')
    entries=client.get('/api/profile-answers').json();assert len(entries)==1 and entries[0]['data']['status']=='draft'
    assert not library.confirmed(guided[0]) and not without_setup(library.records(guided[0]))
    stale=client.put('/api/cover-workspaces/'+state['id']+'/answers',json={'expected_version':state['data']['version'],'answers':[{'question_id':q['id'],'text':'Older replacement','expected_answer_version':0}]})
    assert stale.status_code==409
    assert letters.state(guided[0],state['id'])['data']['questions'][0]['answer'].startswith('I am interested')


def test_batch_review_links_exact_answer_then_approval_creates_reusable_story(guided):
    user=guided[0];state=prepare(guided);q=state['data']['questions'][1]
    state=save_answer(user,state,'cover','I wrote a QA guide used by three classmates to review their queries.',q)
    state=asyncio.run(question_answers.review(user,state['id'],'cover',AnswerBatchReview(expected_version=state['data']['version'],question_ids=[q['id']])))
    proposal=state['data']['context_proposals'][0]
    assert proposal['question_ids']==[q['id']] and proposal['answer_versions'][q['id']]==1
    paid=len(guided[-1]);again=asyncio.run(question_answers.review(user,state['id'],'cover',AnswerBatchReview(expected_version=state['data']['version'],question_ids=[q['id']])))
    assert len(guided[-1])==paid
    state=review(guided,again,build=False);entry=library.confirmed(user)[0]
    assert entry['data']['text'].startswith('I wrote a QA guide') and entry['data']['sources'][0]['questions'][0]['id']==q['id']
    assert state['data']['questions'][1]['status']=='reviewed'
    library.migrate(user);library.migrate(user);assert len(library.confirmed(user))==1
    assert any('QA guide' in str(r['data']) for r in without_setup(library.records(user)))


def test_editing_answer_invalidates_older_pending_proposal(guided):
    state=prepare(guided);q=state['data']['questions'][1]
    state=save_answer(guided[0],state,'cover','I wrote a QA guide used by three classmates.',q)
    state=asyncio.run(question_answers.review(guided[0],state['id'],'cover',AnswerBatchReview(expected_version=state['data']['version'],question_ids=[q['id']])))
    q=state['data']['questions'][1];state=save_answer(guided[0],state,'cover','I wrote a QA guide used by two classmates.',q)
    with pytest.raises(HTTPException) as error:review(guided,state,build=False)
    assert error.value.status_code==409 and not library.confirmed(guided[0])


def test_failed_review_preserves_saved_answer_and_successful_preview(guided,monkeypatch):
    state=generate(guided);state=asyncio.run(__import__('app.cover_context',fromlist=['prepare']).prepare(guided[0],state['id'],CoverGenerate(expected_version=state['data']['version'],content=CoverContent.model_validate(state['data']['content']))))
    q=state['data']['questions'][0];state=save_answer(guided[0],state,'cover','I am interested in supporting planning with analysis.',q);head=state['current']['id']
    async def fail(*args,**kwargs):raise ServiceError('Provider unavailable')
    monkeypatch.setattr(ai,'structured',fail)
    with pytest.raises(ServiceError):asyncio.run(question_answers.review(guided[0],state['id'],'cover',AnswerBatchReview(expected_version=state['data']['version'],question_ids=[q['id']])))
    loaded=letters.state(guided[0],state['id']);assert loaded['current']['id']==head and not loaded['preview_stale']
    assert loaded['data']['questions'][0]['answer'].startswith('I am interested')


def test_manual_review_without_key_and_motivation_explicit_selection(guided,client):
    user,job,resume,_,calls=guided;state=prepare(guided);q=state['data']['questions'][0]
    state=save_answer(user,state,'cover','I am interested in using analysis for planning.',q)
    response=client.post('/api/profile-answers/review',json={'builder':'cover','conversation_id':state['id'],'question_id':q['id'],'expected_answer_version':1,'title':'Why this analytical work interests me','text':'I am interested in using analysis for planning.','answer_kind':'motivation'})
    assert response.status_code==200,response.text
    motivation=response.json();assert not without_setup(library.records(user)) and not library.reusable(user,job['id'])
    assert library.reusable(user,'another-job',[motivation['id']])[0]['id']==motivation['id']
    state=letters.state(user,state['id']);current=state['current']
    response=client.put('/api/cover-workspaces/'+state['id']+'/profile-sources',json={'expected_version':state['data']['version'],'answer_ids':[motivation['id']]});assert response.status_code==200
    state=response.json();assert state['current']==current
    # Selection is applied when an explicit AI action snapshots its sources.
    record,token=letters.begin(user,state['id'],CoverGenerate(expected_version=state['data']['version'],content=CoverContent.model_validate(state['data']['content'])))
    assert any(r['id']=='library:'+motivation['id'] for r in letters.sources(record['data']))


def test_corrections_archive_and_history_do_not_rewrite_saved_pdf(guided,client):
    state=review(guided,answer(guided,prepare(guided)));user=guided[0];original=copy.deepcopy(db.get(user,state['current']['id'],'cover_revision')['data']);entry=library.confirmed(user)[0]
    body={'expected_version':entry['data']['version'],'title':entry['data']['title'],'text':'I wrote a QA guide used by two classmates.','experience_id':''}
    changed=client.put('/api/profile-answers/'+entry['id'],json=body);assert changed.status_code==200,changed.text
    assert changed.json()['data']['history'][0]['text']==entry['data']['text']
    state=letters.state(user,state['id']);assert state['current']['data']['approved_context'][0]['text']==entry['data']['text']
    assert any(r['text']==body['text'] for r in state['sources'])
    data=changed.json()['data'];body.update({'expected_version':data['version'],'archived':True})
    assert client.put('/api/profile-answers/'+entry['id'],json=body).status_code==200
    library.migrate(user);assert not library.confirmed(user) and not without_setup(library.records(user))
    assert db.get(user,state['current']['id'],'cover_revision')['data']==original
    assert client.put('/api/profile-answers/'+entry['id'],json=body).status_code==409


def test_resume_inline_answer_approval_and_backed_profile_correction(client,account,monkeypatch):
    user=account['id'];job=client.post('/api/jobs',json={'title':'Analyst','company':'Example','description':'Requirements\nAnalytical projects and clear written communication.'}).json()
    experience=client.post('/api/experience',json={'title':'Course project','category':'project','description':'Analyzed data.','confirmed':True}).json()
    state=resumes.start(user,ConversationStart(job_id=job['id']));state=save_answer(user,state,'resume','I wrote a report for classmates.')
    async def model(schema,payload,*args,**kwargs):
        assert schema.__name__=='ResumeChatOutput'
        return {'message':'Review this detail.','questions':[],'proposals':[{'record_id':experience['id'],'category':'project','title':'Course project','fields':[{'field':'contribution','value':'I wrote a report for classmates.','user_quote':'I wrote a report for classmates.'}],'reason':'Show written communication.','criterion_ids':[]}],'action':'facts','revision_instruction':'','target_item_ids':[],'target_record_ids':[],'change_headline':False,'change_selection':False}, {'model':'test','mode':'economy','usage':{},'estimated_token_cost_usd':.001}
    monkeypatch.setattr(ai,'structured',model)
    q=state['data']['asked_questions'][0]
    state=asyncio.run(question_answers.review(user,state['id'],'resume',AnswerBatchReview(expected_version=state['data']['version'],question_ids=[q['id']])))
    # Backed-field corrections still apply to historical pending proposals.
    state['data']['proposals'][0].pop('evidence_only',None)
    db.save(user,'resume_conversation',state['data'],state['id'])
    state=resumes.approve(user,state['id'],FactApproval(expected_version=state['data']['version'],proposal_id=state['data']['proposals'][0]['id'],action='approve',update_draft=False))
    entry=library.confirmed(user)[0];assert entry['data']['experience_id']==experience['id']
    assert without_setup(library.records(user))[0]['data']['contribution'].count('I wrote a report')==1
    current=db.get(user,experience['id'],'experience');new='I wrote a report for a course supervisor.'
    body={'expected_version':1,'title':entry['data']['title'],'text':new,'values':{'contribution':new},'experience_id':experience['id'],'experience_updated_at':current['updated_at']}
    db.save(user,'experience',{**current['data'],'tools':'Excel'},experience['id'])
    assert client.put('/api/profile-answers/'+entry['id'],json=body).status_code==409
    body['experience_updated_at']=db.get(user,experience['id'],'experience')['updated_at']
    response=client.put('/api/profile-answers/'+entry['id'],json=body);assert response.status_code==200,response.text
    assert db.get(user,experience['id'],'experience')['data']['contribution']==new
    assert db.get(user,experience['id'],'experience')['data']['tools']=='Excel'


def test_backup_remaps_library_answers_workflow_and_drafts(guided,client):
    user,job,resume,_,calls=guided;state=review(guided,answer(guided,prepare(guided)));entry=library.confirmed(user)[0]
    app=applications.start(user,job['id']);applications.set_workflow(user,app['id'],ApplicationWorkflowUpdate(expected_updated_at=app['updated_at'],workflow=ApplicationWorkflow(step='cover',resume_id=resume['id'])))
    state=save_answer(user,state,'cover','I am interested in useful analysis.',state['data']['questions'][0])
    backup=client.get('/api/account/export').json();result=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')});assert result.status_code==200,result.text
    restored=next(r for r in library.confirmed(user) if r['id']!=entry['id'])
    assert restored['data']['sources'][0]['conversation_id']!=state['id'] and restored['data']['scope']['job_id']!=job['id']
    application=next(a for a in db.list_entities(user,'application') if a['data']['job_id']!=job['id'])
    assert application['data']['workflow']['resume_id']!=resume['id']
    recovered=letters.state(user,restored['data']['sources'][0]['conversation_id']);assert recovered['data']['questions'][0]['answer']=='I am interested in useful analysis.'
    assert any(r['data']['status']=='draft' for r in library.listing(user))


def test_new_routes_and_answer_sources_are_account_isolated(guided,client):
    state=review(guided,answer(guided,prepare(guided)));entry=library.confirmed(guided[0])[0];app=applications.start(guided[0],guided[1]['id'])
    other=client.post('/api/auth/register',json={'username':'another_profile_owner','password':'fictional-other-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
    onboard_test_account(other)
    assert client.get('/api/profile-answers').json()==[]
    assert client.put('/api/profile-answers/'+entry['id'],json={'expected_version':1,'title':'Changed','text':'Changed facts.'}).status_code==404
    assert client.post('/api/applications/start',json={'job_id':guided[1]['id']}).status_code==404
    assert client.put('/api/cover-workspaces/'+state['id']+'/answers',json={'expected_version':state['data']['version'],'answers':[{'question_id':state['data']['questions'][0]['id'],'text':'Other account input'}]}).status_code==404
    assert client.put('/api/applications/'+app['id']+'/workflow',json={'expected_updated_at':app['updated_at'],'workflow':{'step':'resume'}}).status_code==404


def test_multiple_inline_answers_reviewed_in_one_paid_action(guided,monkeypatch):
    user=guided[0];state=prepare(guided);questions=state['data']['questions']
    texts=['I am interested in analysis that helps colleagues plan.','I wrote a short QA guide that classmates used to check queries.']
    state=question_answers.save(user,state['id'],'cover',AnswerDraftSave(expected_version=state['data']['version'],answers=[InlineAnswer(question_id=q['id'],text=text) for q,text in zip(questions,texts)]))
    previous=ai.structured;counts=[]
    async def model(schema,payload,*args,**kwargs):
        value,meta=await previous(schema,payload,*args,**kwargs)
        if schema.__name__=='CoverChatOutput':
            counts.append(schema.__name__);value['details']=[{'kind':'motivation' if i==0 else 'experience','user_quote':a['answer'],'title':'Why this work' if i==0 else 'Report context','question_ids':[a['question_id']],'related_source_id':'' if i==0 else 'resume:0:0:1','supersedes_id':'','profile_category':'project'} for i,a in enumerate(payload['submitted_question_answers'])];value['answered_question_ids']=[q['id'] for q in questions]
        return value,meta
    monkeypatch.setattr(ai,'structured',model)
    state=asyncio.run(question_answers.review(user,state['id'],'cover',AnswerBatchReview(expected_version=state['data']['version'],question_ids=[q['id'] for q in questions])))
    assert counts==['CoverChatOutput'] and len(state['data']['context_proposals'])==2
    from app import cover_context
    state=asyncio.run(cover_context.review(user,state['id'],CoverContextReview(expected_version=state['data']['version'],content=CoverContent.model_validate(state['data']['content']),build=False,decisions=[CoverReviewDecision(proposal_id=p['id'],action='approve',text=p['text']) for p in state['data']['context_proposals']])))
    assert all(q['status']=='reviewed' for q in state['data']['questions'])
    assert len(library.confirmed(user))==2 and len(without_setup(library.records(user)))==1
    assert all('interested in analysis' not in json.dumps(r['data']) for r in without_setup(library.records(user)))


def test_reviewed_stories_reach_comparison_resume_and_interview_inputs(guided,monkeypatch):
    user=guided[0];state=review(guided,answer(guided,prepare(guided)),build=False);entry=library.confirmed(user)[0];text=entry['data']['text'];seen=[]
    async def model(schema,payload,*args,**kwargs):
        seen.append((schema.__name__,payload))
        if schema.__name__=='CatalogComparisonOutput':
            criteria=payload['criterion_catalog'];rid=next(r['id'] for r in payload['retrieved'] if r['kind']=='experience' and text in json.dumps(r['data']))
            return {'summary':'Reviewed project evidence.','requirements':[{'criterion_id':c['id'],'keyword':c['text'],'job_quote':c['source'],'importance':c['importance'],'kind':c['kind'],'status':'supported' if c['kind']=='qualification' and c['importance']=='required' else 'unknown','evidence':[{'source_id':next(s['source_id'] for s in payload['professional_evidence_catalog'] if s['record_id']==rid and ai.valid_quote(text,s['quote']))}] if c['kind']=='qualification' and c['importance']=='required' else [],'explanation':'Reviewed project information.','question':''} for c in criteria],'job_details':[],'recommendations':[],'suggestions':[],'questions':[],'keywords':[]},{'model':'test','estimated_token_cost_usd':.001}
        if schema.__name__=='PrepOutput':return {'summary':'Use your reviewed project story.','priorities':[],'resource_ids':[],'interview_questions':[]},{'model':'test','estimated_token_cost_usd':.001}
        raise AssertionError(schema.__name__)
    monkeypatch.setattr(ai,'structured',model)
    analysis=asyncio.run(ai.analyze(user,guided[1]['data'],'economy'));assert analysis['score']['groups']['required']['supported']==1
    asyncio.run(ai.prepare(user,guided[1]['data'],[],'economy'))
    assert text in json.dumps(seen[0][1]['retrieved']) and text in json.dumps(seen[1][1]['experience'])
    from app.main import build_resume
    snapshot=build_resume(user,ResumeRequest(job_id=guided[1]['id'],experience_ids=[entry['id']]))
    assert text in json.dumps(snapshot['sections'])


def test_backup_rejects_foreign_library_and_invalid_workflow_refs_before_import(guided,client):
    state=review(guided,answer(guided,prepare(guided)),build=False);backup=client.get('/api/account/export').json();before=len(db.list_entities(guided[0],'profile_answer'))
    record=next(r for r in backup['records'] if r['kind']=='profile_answer');record['data']['experience_id']='not-in-this-backup'
    result=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')});assert result.status_code==400
    assert len(db.list_entities(guided[0],'profile_answer'))==before


def test_saved_letter_workflow_matches_exact_resume_without_changing_submission(guided):
    user,job,resume,_,calls=guided;state=generate(guided);app=db.list_entities(user,'application')[0]
    newer=db.save(user,'resume',{**resume['data'],'headline':'Another historical version'});applications.attach_resume(user,newer)
    data=db.get(user,app['id'],'application')['data'];data.update({'submitted_resume_id':newer['id'],'status':'applied','applied_date':'2026-10-21'});db.save(user,'application',data,app['id'])
    state=letters.finalize(user,state['id'],FinalizeRevision(expected_version=state['data']['version'],revision_id=state['current']['id'],reviewed=True))
    current=db.get(user,app['id'],'application')['data'];assert current['workflow']['resume_id']==resume['id'] and current['workflow']['cover_letter_id']==state['data']['last_saved_letter_id']
    assert current['submitted_resume_id']==newer['id'] and current['status']=='applied'


def test_manual_review_deduplicates_same_professional_detail_and_rejects_empty(guided):
    user=guided[0];state=prepare(guided);text='I wrote a QA guide for classmates.'
    for question in state['data']['questions'][:2]:
        state=save_answer(user,state,'cover',text,question)
        body=ProfileDraftReview(builder='cover',conversation_id=state['id'],question_id=question['id'],expected_answer_version=1,title='Writing a QA guide',text=text,answer_kind='experience')
        library.confirm_draft(user,body);state=letters.state(user,state['id'])
    entries=library.confirmed(user);assert len(entries)==1 and len(entries[0]['data']['sources'])==2
    with pytest.raises(HTTPException):library.confirm_draft(user,body.model_copy(update={'text':'  '}))


def test_changed_linked_profile_facts_do_not_reenter_from_story_history(guided):
    user=guided[0];experience=db.save(user,'experience',ExperienceItem(title='Course project',category='project',description='I wrote a report for classmates.',confirmed=True).model_dump())
    data={'version':1,'status':'confirmed','answer_kind':'experience','title':'Report','text':experience['data']['description'],'experience_id':experience['id'],'backed_fields':{'description':experience['data']['description']},'sources':[],'history':[]}
    db.save(user,'profile_answer',data);assert library.confirmed(user)
    revised={**experience['data'],'description':'I presented a dashboard to classmates.'};db.save(user,'experience',revised,experience['id'])
    assert not library.confirmed(user) and 'I wrote a report' not in json.dumps(without_setup(library.records(user)))
    assert db.list_entities(user,'profile_answer')[0]['data']['text']==data['text']


@pytest.mark.parametrize('private',['I am authorized to work in the United States.','I require employer sponsorship in the future.'])
def test_authorization_answers_cannot_become_reusable_stories(guided,private):
    user=guided[0];state=prepare(guided);q=state['data']['questions'][0];state=save_answer(user,state,'cover',private,q)
    assert not library.drafts(user)
    with pytest.raises(HTTPException) as error:library.confirm_draft(user,ProfileDraftReview(builder='cover',conversation_id=state['id'],question_id=q['id'],expected_answer_version=1,title='Private answer',text=private,answer_kind='experience'))
    assert error.value.status_code==400 and not library.confirmed(user)


def test_account_deletion_removes_answers_provenance_and_workflow(guided,client):
    user=guided[0];state=review(guided,answer(guided,prepare(guided)),build=False);app=applications.start(user,guided[1]['id']);assert library.confirmed(user)
    response=client.request('DELETE','/api/account',json={'username':'student','password':'fictional-test-password'})
    assert response.status_code==200
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM entities WHERE user_id=?',(user,)).fetchone()[0]==0
    assert not db.get(user,app['id'],'application') and not db.get(user,state['id'],'cover_workspace')
