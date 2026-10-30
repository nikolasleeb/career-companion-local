from conftest import without_setup
from conftest import onboard_test_account
import asyncio
import base64
import copy
import io
import json
from urllib.parse import urlparse
import pytest
from fastapi import HTTPException
from pypdf import PdfReader
from app import ai,db,guidance,cover_context as context,cover_letters as letters
from app.models import CoverGenerate,CoverMessage,CoverContent,CoverContextReview,CoverReviewDecision,CoverQuestionSkip,FinalizeRevision,CoverEdit
from app.network import ServiceError
from test_cover_letters import env,META,generate
from test_applications_workflow import wait_task

@pytest.fixture
def guided(env,monkeypatch):
    user,job,resume,state,calls=env;original=ai.structured
    async def model(schema,payload,*args,**kwargs):
        if schema.__name__=='CoverQuestionsOutput':
            calls.append((schema.__name__,payload))
            return {'message':'These questions can add motivation and a useful story.','questions':[{'text':'What interests you about the analytical work in this role?','purpose':'Add your own reason for choosing this opportunity.','topic':'motivation','source_ids':[],'job_quote':'Analyst Intern','guidance_ids':['guide_harvard_motivation']},{'text':'What did you write for classmates, and how did they use it?','purpose':'Develop the story behind your report rather than restating its resume bullet.','topic':'story','source_ids':['resume:0:0:1'],'job_quote':'Analytical project experience.','guidance_ids':['guide_ua_story']}]},META
        if schema.__name__=='CoverChatOutput':
            calls.append((schema.__name__,payload));text=payload['latest_user_message'];questions=payload['questions']
            kind='motivation' if 'interested' in text else 'experience'
            return {'action':'collect','reply':'Review this detail before I use it.','revision_instruction':'Use the newly reviewed context to explain the story.','paragraph_indices':[1],'revise_all':False,'header_style':'unchanged','subject':'unchanged','answered_question_ids':[q['id'] for q in questions if q['topic']==('motivation' if kind=='motivation' else 'story')],'skipped_question_ids':[],'followup_questions':[],'details':[{'kind':kind,'user_quote':text,'title':'Report audience and use','question_ids':[q['id'] for q in questions if q['topic']=='story'],'related_source_id':'resume:0:0:1','supersedes_id':'','profile_category':'project'}]},META
        if schema.__name__=='CoverLetterOutput':
            answers=[r for r in payload['saved_resume_sources'] if r['id'].startswith('answer:')]
            if answers:
                calls.append((schema.__name__,payload));answer=answers[-1];source=next(r for r in payload['saved_resume_sources'] if r['id']=='resume:0:0:0')
                return {'paragraphs':[{'text':'I am applying for the Analyst Intern position.','evidence':[{'source_id':'posting','quote':'Analyst Intern'}]},{'text':answer['text'],'evidence':[{'source_id':answer['id'],'quote':answer['text']}]},{'text':source['text'],'evidence':[{'source_id':source['id'],'quote':source['text']}]}],'summary':'Developed your reviewed report example.'},META
        return await original(schema,payload,*args,**kwargs)
    monkeypatch.setattr(ai,'structured',model)
    return env

def prepare(env):
    user,job,resume,state,calls=env
    return asyncio.run(context.prepare(user,state['id'],CoverGenerate(expected_version=state['data']['version'],content=CoverContent.model_validate(state['data']['content']))))

def answer(env,state,text='I wrote a QA guide used by three classmates to review their queries.'):
    return asyncio.run(letters.send(env[0],state['id'],CoverMessage(expected_version=state['data']['version'],content=CoverContent.model_validate(state['data']['content']),text=text,request_token='answer-'+str(state['data']['version']))))

def review(env,state,build=True,**extra):
    p=next(p for p in state['data']['context_proposals'] if p['status']=='pending')
    if p['kind']=='experience' and not extra.get('save_to_profile') and 'experience_ids' not in extra:
        target=next((r for r in db.list_entities(env[0],'experience') if r['data'].get('title')=='Fictional report project'),None) or db.save(env[0],'experience',{'title':'Fictional report project','category':'project','confirmed':True})
        extra['experience_ids']=[target['id']]
    return asyncio.run(context.review(env[0],state['id'],CoverContextReview(expected_version=state['data']['version'],content=CoverContent.model_validate(state['data']['content']),build=build,decisions=[CoverReviewDecision(proposal_id=p['id'],text=p['text'],action='approve',**extra)])))

def test_questions_first_no_draft_and_dedup(guided):
    state=prepare(guided);calls=guided[-1]
    assert len(state['data']['questions'])==2 and not state['current']
    assert state['data']['question_guidance']['version']==guidance.catalog()['version']
    before=len(calls);again=asyncio.run(context.prepare(guided[0],state['id'],CoverGenerate(expected_version=state['data']['version'],content=CoverContent.model_validate(state['data']['content']))))
    assert len(calls)==before and again['data']['questions']==state['data']['questions']
    assert not context.make_questions([{k:v for k,v in q.items() if k not in ('id','status','created_at')} for q in state['data']['questions']],state['data'],state['data']['question_guidance'])


def test_answer_review_directly_supports_letter_without_new_resume(guided):
    user,job,resume,_,calls=guided;original=copy.deepcopy(resume['data']);state=answer(guided,prepare(guided))
    assert not state['current'] and state['data']['context_proposals'][0]['status']=='pending'
    assert not any(r['id'].startswith('answer:') for r in state['sources'])
    with pytest.raises(HTTPException):asyncio.run(letters.generate(user,state['id'],CoverGenerate(expected_version=state['data']['version'],content=CoverContent.model_validate(state['data']['content']))))
    state=review(guided,state);current=state['current']['data']
    assert current['approved_context'][0]['text'].startswith('I wrote a QA guide')
    assert current['content']['paragraphs'][1].startswith('I wrote a QA guide')
    assert db.get(user,resume['id'],'resume')['data']==original and len(db.list_entities(user,'resume'))==1
    assert [r['data']['title'] for r in without_setup(db.list_entities(user,'experience'))]==['Fictional report project'] # Approval links the existing fixture rather than creating another record.
    assert any(e['source_id'].startswith('answer:') for e in current['evidence'][1]['evidence'])
    pdf=base64.b64decode(db.get(user,state['current']['id'],'cover_revision')['data']['artifacts']['pdf'])
    assert 'QA guide' in PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
    assert current['writing_guidance']['version']==guidance.catalog()['version']


def test_correction_rejection_skip_and_build_with_existing(guided):
    state=answer(guided,prepare(guided));p=state['data']['context_proposals'][0]
    state=asyncio.run(context.review(guided[0],state['id'],CoverContextReview(expected_version=state['data']['version'],content=CoverContent.model_validate(state['data']['content']),build=False,decisions=[CoverReviewDecision(proposal_id=p['id'],action='approve',text='I wrote a QA guide used by two classmates.',experience_ids=[db.save(guided[0],'experience',{'title':'Fictional report project','category':'project','confirmed':True})['id']])])) )
    assert context.approved(state['data'])[0]['text'].endswith('two classmates.')
    state=answer(guided,state,'I am interested in learning how analysis supports planning.')
    p=next(p for p in state['data']['context_proposals'] if p['status']=='pending')
    state=asyncio.run(context.review(guided[0],state['id'],CoverContextReview(expected_version=state['data']['version'],content=CoverContent.model_validate(state['data']['content']),build=False,decisions=[CoverReviewDecision(proposal_id=p['id'],action='reject')])) )
    state=asyncio.run(letters.generate(guided[0],state['id'],CoverGenerate(expected_version=state['data']['version'],content=CoverContent.model_validate(state['data']['content']),skip_questions=True)))
    assert all(q['status']!='open' for q in state['data']['questions'])
    assert 'learning how' not in json.dumps(state['current']['data']['content'])


def test_optional_profile_new_record_and_motivation_stays_private_to_letter(guided):
    state=answer(guided,prepare(guided));state=review(guided,state,build=False,save_to_profile=True,profile_title='Query review guide',profile_category='project')
    record=without_setup(db.list_entities(guided[0],'experience'))[0]
    assert record['data']['confirmed'] and 'QA guide' in record['data']['contribution']
    assert state['data']['context_proposals'][0]['applied_record_id']==record['id']
    state=answer(guided,state,'I am interested in analytical work that helps colleagues plan.')
    with pytest.raises(HTTPException):review(guided,state,build=False,save_to_profile=True)
    assert len(without_setup(db.list_entities(guided[0],'experience')))==1


def test_profile_concurrent_change_rolls_back_approval(guided):
    user=guided[0];target=db.save(user,'experience',{'category':'project','title':'Demand analysis','confirmed':True,'contribution':'Original.'})
    state=answer(guided,prepare(guided));db.save(user,'experience',{**target['data'],'contribution':'Newer edit.'},target['id'])
    with pytest.raises(HTTPException) as e:review(guided,state,build=False,save_to_profile=True,profile_record_id=target['id'],profile_expected_updated_at=target['updated_at'])
    assert e.value.status_code==409
    assert letters.state(user,state['id'])['data']['context_proposals'][0]['status']=='pending'
    assert db.get(user,target['id'],'experience')['data']['contribution']=='Newer edit.'


def test_review_retry_does_not_duplicate_profile_after_draft_failure(guided,monkeypatch):
    state=answer(guided,prepare(guided));original=letters.draft
    async def fail(*args,**kwargs):raise ServiceError('Provider unavailable')
    monkeypatch.setattr(letters,'draft',fail)
    with pytest.raises(ServiceError):review(guided,state,save_to_profile=True,profile_title='Query review guide')
    state=letters.state(guided[0],state['id']);p=state['data']['context_proposals'][0];assert p['status']=='approved'
    monkeypatch.setattr(letters,'draft',original)
    state=asyncio.run(context.review(guided[0],state['id'],CoverContextReview(expected_version=state['data']['version'],content=CoverContent.model_validate(state['data']['content']),decisions=[CoverReviewDecision(proposal_id=p['id'],action='approve',text=p['text'],save_to_profile=True,profile_title='Query review guide')])))
    assert state['current'] and len(without_setup(db.list_entities(guided[0],'experience')))==1


def test_forged_quotes_question_refs_private_details_and_guidance_not_evidence(guided,monkeypatch):
    state=prepare(guided);original=ai.structured
    async def bad(schema,payload,*args,**kwargs):
        output,meta=await original(schema,payload,*args,**kwargs)
        if schema.__name__=='CoverChatOutput':output['details'][0]['user_quote']='Invented source statement.'
        return output,meta
    monkeypatch.setattr(ai,'structured',bad)
    with pytest.raises(ServiceError):answer(guided,state)
    state=letters.state(guided[0],state['id']);assert not state['data']['context_proposals']
    monkeypatch.setattr(ai,'structured',original)
    with pytest.raises(ServiceError):answer(guided,state,'I have work authorization and need no sponsorship.')
    with pytest.raises(ServiceError):letters.validate_output({'paragraphs':[{'text':'I have expertise.','evidence':[{'source_id':'guide_ua_story','quote':'A cover letter'}]}]},letters.sources(state['data']),guided[1]['data'])
    with pytest.raises(ServiceError):context.make_questions([{'text':'Are you available to work onsite?','purpose':'Check the schedule.','topic':'story','source_ids':[],'job_quote':'','guidance_ids':[]}],state['data'],guidance.selected('cover'))


def test_history_context_restore_and_backups_snapshot_approved_answers(guided,client):
    state=review(guided,answer(guided,prepare(guided)));user=guided[0]
    current=state['current'];content=CoverContent.model_validate(state['data']['content']);content.closing='Kind regards,'
    state=asyncio.run(letters.render(user,state['id'],CoverEdit(expected_version=state['data']['version'],content=content)))
    assert state['current']['data']['approved_context']==current['data']['approved_context']
    backup=client.get('/api/account/export').json();response=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')});assert response.status_code==200,response.text
    other=next(r for r in db.list_entities(user,'cover_workspace') if r['id']!=state['id'])
    restored=letters.state(user,other['id'])
    assert restored['data']['resume_id']!=state['data']['resume_id']
    assert restored['data']['context_proposals'][0]['source_message_id']==restored['data']['messages'][1]['id']
    assert restored['current']['data']['approved_context'][0]['text']==current['data']['approved_context'][0]['text']
    assert restored['current']['data']['writing_guidance']==current['data']['writing_guidance']


def test_guidance_no_provider_catalog_filter_and_legacy_ids(client,account,monkeypatch):
    def no_provider(*args,**kwargs):raise AssertionError('No AI calls when opening the guide')
    monkeypatch.setattr(ai,'structured',no_provider)
    result=client.get('/api/guidance');assert result.status_code==200;catalog=result.json();items=catalog['items']
    assert {'guide_evidence','guide_format','guide_ats','guide_master'}<=set(r['id'] for r in items)
    assert len(set(r['id'] for r in items))==len(items)
    assert {r['topic'] for r in items}=={'resume','cover','formatting','examples'}
    assert any('Harvard' in r['publisher'] for r in items) and any('Arizona' in r['publisher'] for r in items) and any('MIT' in r['publisher'] for r in items)
    for r in items:assert urlparse(r['url']).scheme=='https' and r['reviewed_at']=='2026-10-21'
    for r in items:
        if r.get('example'):assert 'fictional' in r['example']['label'].lower() and r['example']['facts']
    assert all(r['topic'] in ('cover','formatting') or r['id']=='guide_evidence' for r in guidance.selected('cover')['items'])


def test_questions_tasks_account_scope_and_skip(guided,client):
    user,job,resume,state,calls=guided
    task=wait_task(client,client.post('/api/cover-workspaces/'+state['id']+'/questions',json={'expected_version':state['data']['version'],'content':state['data']['content']}));assert task['status']=='completed',task
    state=task['result'];qid=state['data']['questions'][0]['id']
    response=client.post('/api/cover-workspaces/'+state['id']+'/questions/skip',json={'expected_version':state['data']['version'],'question_ids':[qid]});assert response.status_code==200
    assert response.json()['data']['questions'][0]['status']=='skipped'
    other=client.post('/api/auth/register',json={'username':'other_guided_student','password':'fictional-other-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
    onboard_test_account(other)
    assert client.get('/api/cover-workspaces/'+state['id']).status_code==404
    response=client.post('/api/cover-workspaces/'+state['id']+'/context/review',json={'expected_version':0,'content':state['data']['content'],'build':False,'decisions':[{'proposal_id':'fake','action':'approve'}]});assert response.status_code==404


def test_pending_profile_target_backup_and_provenance_validation(guided,client):
    user=guided[0]
    target=db.save(user,'experience',{'category':'project','title':'Demand analysis','confirmed':True,'contribution':'Original.'})
    state=answer(guided,prepare(guided));p=state['data']['context_proposals'][0]
    assert p['profile_original']==target['data']
    backup=client.get('/api/account/export').json()
    invalid=copy.deepcopy(backup)
    workspace=next(r for r in invalid['records'] if r['id']==state['id'])
    workspace['data']['context_proposals'][0]['source_message_id']='missing-message'
    response=client.post('/api/account/import',files={'file':('backup.json',json.dumps(invalid).encode(),'application/json')})
    assert response.status_code==400
    assert len(db.list_entities(user,'cover_workspace'))==1
    response=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')});assert response.status_code==200,response.text
    restored=next(r for r in db.list_entities(user,'cover_workspace') if r['id']!=state['id'])
    state=letters.state(user,restored['id']);p=state['data']['context_proposals'][0]
    assert p['profile_record_id']!=target['id']
    state=review(guided,state,build=False,save_to_profile=True,profile_record_id=p['profile_record_id'],profile_expected_updated_at=p['profile_expected_updated_at'])
    assert 'QA guide' in db.get(user,p['profile_record_id'],'experience')['data']['contribution']
    assert db.get(user,target['id'],'experience')['data']['contribution']=='Original.'


def test_preparation_failure_keeps_successful_preview(guided,monkeypatch):
    state=generate(guided);prior=state['current'];original=ai.structured
    async def fail(schema,*args,**kwargs):
        if schema.__name__=='CoverQuestionsOutput':raise ServiceError('Temporary provider failure')
        return await original(schema,*args,**kwargs)
    monkeypatch.setattr(ai,'structured',fail)
    with pytest.raises(ServiceError):asyncio.run(context.prepare(guided[0],state['id'],CoverGenerate(expected_version=state['data']['version'],content=CoverContent.model_validate(state['data']['content']))))
    state=letters.state(guided[0],state['id'])
    assert state['current']==prior and not state['preview_stale']


def test_context_correction_preserves_historical_sources(guided,monkeypatch):
    state=review(guided,answer(guided,prepare(guided)));prior=state['current'];old=context.approved(state['data'])[0];original=ai.structured
    async def correction(schema,*args,**kwargs):
        value,meta=await original(schema,*args,**kwargs)
        if schema.__name__=='CoverChatOutput':value['details'][0]['supersedes_id']=old['id']
        return value,meta
    monkeypatch.setattr(ai,'structured',correction)
    state=answer(guided,state,'Correction: two classmates used my QA guide to review queries.')
    state=review(guided,state,build=False)
    assert state['current']['id']==prior['id'] and state['data']['context_dirty']
    assert next(r for r in state['current_sources'] if r['id']=='answer:'+old['id'])['text']==old['text']
    assert not any(r['id']=='answer:'+old['id'] for r in state['sources'])
    assert db.get(guided[0],prior['id'],'cover_revision')['data']['approved_context'][0]['text']==old['text']


def test_questions_keep_their_own_guidance_snapshot(guided):
    state=prepare(guided);q=state['data']['questions'][0]
    assert q['writing_guidance']['version']==guidance.catalog()['version']
    assert [r['id'] for r in q['writing_guidance']['items']]==q['guidance_ids']
    assert state['data']['messages'][0]['writing_guidance']['version']==q['writing_guidance']['version']


def test_approved_correction_updates_paragraph_using_superseded_source(guided,monkeypatch):
    state=review(guided,answer(guided,prepare(guided)));old=context.approved(state['data'])[0];original=ai.structured
    async def correction(schema,*args,**kwargs):
        value,meta=await original(schema,*args,**kwargs)
        if schema.__name__=='CoverChatOutput':
            value['details'][0]['supersedes_id']=old['id']
            value['paragraph_indices']=[0] # The source itself identifies another affected paragraph.
        return value,meta
    monkeypatch.setattr(ai,'structured',correction)
    state=answer(guided,state,'Correction: two classmates used my QA guide to review queries.')
    state=review(guided,state)
    assert state['current']['data']['content']['paragraphs'][1].startswith('Correction: two classmates')
    assert all(e['source_id']!='answer:'+old['id'] for p in state['current']['data']['evidence'] for e in p['evidence'])
