from conftest import without_setup
"""Human-reviewed wording and shared experience relationships, with mocked AI only."""
import asyncio
import copy
import json
import pytest
from fastapi import HTTPException
from app import ai,db,cover_context as context,cover_letters as letters,profile_answers as library
from app.models import CoverMessage,CoverContextReview,CoverContent,CoverReviewDecision,ProfileAnswerEdit
from app.network import ServiceError
from test_cover_guided import guided,prepare,answer
from test_cover_letters import env,META

RAW='I annotated more drawings to help improve extraction. The feature was not fully implemented.'
POLISHED='I added drawing annotations to support extraction improvements; the feature remained unfinished.'

def role(user,title):return db.save(user,'experience',{'title':title,'category':'employment','confirmed':True,'contribution':'Original contribution.'})
def approve(user,state,**kw):
 p=next(p for p in state['data']['context_proposals'] if p['status']=='pending')
 return asyncio.run(context.review(user,state['id'],CoverContextReview(expected_version=state['data']['version'],content=CoverContent.model_validate(state['data']['content']),build=False,decisions=[CoverReviewDecision(proposal_id=p['id'],action='approve',**kw)])))
def polish(user,state,ids=None):
 return asyncio.run(letters.send(user,state['id'],CoverMessage(expected_version=state['data']['version'],content=CoverContent.model_validate(state['data']['content']),text='Suggest polished wording.',polish_proposal_ids=ids or [state['data']['context_proposals'][0]['id']])))

def test_review_proposes_edited_wording_and_preserves_original_before_approval(guided,monkeypatch):
 user=guided[0];original=ai.structured;calls=[]
 async def model(schema,payload,*args,**kwargs):
  result,meta=await original(schema,payload,*args,**kwargs)
  if schema.__name__=='CoverChatOutput':
   calls.append(payload);result['details'][0].update(suggested_text=POLISHED,editing_note='Removed repetition while retaining the unfinished status.',improvement_suggestions=['Which extraction errors did the added annotations target?'])
  return result,meta
 monkeypatch.setattr(ai,'structured',model)
 state=answer(guided,prepare(guided),RAW);p=state['data']['context_proposals'][0]
 assert len(calls)==1 and 'Never add tools, metrics' in calls[0]['task']
 assert p['text']==POLISHED and p['user_quote']==RAW and p['status']=='pending'
 assert not state['current'] and not db.list_entities(user,'profile_answer')
 state=approve(user,state,text=POLISHED)
 evidence=db.list_entities(user,'profile_answer')[0]['data']
 assert evidence['text']==POLISHED and evidence['sources'][0]['user_quote']==RAW
 assert evidence['sources'][0]['improvement_suggestions']==p['improvement_suggestions']
 assert letters.state(user,state['id'])['data']['messages'][1]['text']==RAW


def test_pending_legacy_answers_can_be_polished_without_approving_or_rendering(guided,monkeypatch):
 user=guided[0];state=answer(guided,prepare(guided),RAW);p=state['data']['context_proposals'][0];dispatch=[]
 async def model(schema,payload,*args,**kwargs):
  dispatch.append(schema.__name__);assert payload['details'][0]['user_quote']==RAW
  return {'details':[{'proposal_id':p['id'],'suggested_text':POLISHED,'editing_note':'Made the action concise; kept its limit.','improvement_suggestions':['What was incomplete?']}]},META
 monkeypatch.setattr(ai,'structured',model)
 state=polish(user,state);edited=state['data']['context_proposals'][0]
 assert dispatch==['CoverPolishOutput']
 assert edited['text']==RAW and edited['suggested_text']==POLISHED and edited['status']=='pending'
 assert not state['current'] and not db.list_entities(user,'profile_answer')
 # Original/candidate remain separate, and the human can choose the original.
 state=approve(user,state,text=RAW)
 assert db.list_entities(user,'profile_answer')[0]['data']['text']==RAW
 with pytest.raises(HTTPException):polish(user,state)
 assert dispatch==['CoverPolishOutput']

@pytest.mark.parametrize('suggestion',['I improved accuracy by 42%.','I am a U.S. citizen.'])
def test_unsupported_numbers_and_private_eligibility_do_not_replace_pending_wording(guided,monkeypatch,suggestion):
 user=guided[0];state=answer(guided,prepare(guided),RAW);p=state['data']['context_proposals'][0]
 async def model(*args,**kwargs):return {'details':[{'proposal_id':p['id'],'suggested_text':suggestion,'editing_note':'Bad suggestion','improvement_suggestions':[]}]},META
 monkeypatch.setattr(ai,'structured',model)
 with pytest.raises(ServiceError):polish(user,state)
 current=letters.state(user,state['id'])
 assert current['data']['context_proposals'][0]==p and not current['current']


def test_one_story_links_two_roles_without_changing_either_profile_or_duplicating_credit(guided,client):
 user=guided[0];intern=role(user,'VDOT Business Intern');contractor=role(user,'UVA/CTS Contractor')
 state=answer(guided,prepare(guided),RAW);state=approve(user,state,experience_ids=[contractor['id'],intern['id']])
 records=db.list_entities(user,'profile_answer');assert len(records)==1
 data=records[0]['data'];assert data['experience_ids']==[contractor['id'],intern['id']] and data['experience_id']==contractor['id']
 assert db.get(user,intern['id'],'experience')==intern and db.get(user,contractor['id'],'experience')==contractor
 effective={r['id']:r['data'] for r in without_setup(library.records(user))}
 assert RAW not in effective[intern['id']]['contribution'] and RAW in effective[contractor['id']]['contribution']
 source=effective[contractor['id']]['answer_sources'][0]
 assert source['experience_ids']==data['experience_ids'] and len(source['linked_experiences'])==2
 # The same approval cannot be retried to silently change its associations.
 p=state['data']['context_proposals'][0]
 with pytest.raises(HTTPException):asyncio.run(context.review(user,state['id'],CoverContextReview(expected_version=state['data']['version'],content=CoverContent.model_validate(state['data']['content']),build=False,decisions=[CoverReviewDecision(proposal_id=p['id'],action='approve',experience_ids=[intern['id']])])))
 backup=client.get('/api/account/export').json();response=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')})
 assert response.status_code==200,response.text
 restored=next(r for r in db.list_entities(user,'profile_answer') if r['id']!=records[0]['id'])['data']
 assert len(restored['experience_ids'])==2 and not set(restored['experience_ids'])&set(data['experience_ids'])
 assert restored['experience_id']==restored['experience_ids'][0]
 assert restored['sources'][0]['message']==RAW


def test_append_is_explicit_and_only_changes_chosen_record(guided):
 user=guided[0];a=role(user,'Intern');b=role(user,'Contractor');state=answer(guided,prepare(guided),RAW)
 state=approve(user,state,experience_ids=[b['id'],a['id']],save_to_profile=True,profile_record_id=b['id'],profile_expected_updated_at=b['updated_at'])
 assert db.get(user,a['id'],'experience')==a
 assert RAW in db.get(user,b['id'],'experience')['data']['contribution']
 assert len(db.list_entities(user,'profile_answer'))==1

@pytest.mark.parametrize('invalid',['missing','draft','duplicate','foreign'])
def test_link_validation_rolls_back_whole_approval(guided,client,invalid):
 user=guided[0];a=role(user,'Intern');state=answer(guided,prepare(guided),RAW)
 if invalid=='missing':ids=['missing']
 elif invalid=='draft':ids=[db.save(user,'experience',{'title':'Draft','category':'employment','confirmed':False})['id']]
 elif invalid=='duplicate':ids=[a['id'],a['id']]
 else:
  other=client.post('/api/auth/register',json={'username':'other-person','password':'fictional-other-password'}).json()
  ids=[role(other['id'],'Private role')['id']]
 with pytest.raises(HTTPException):approve(user,state,experience_ids=ids)
 assert not db.list_entities(user,'profile_answer')
 assert letters.state(user,state['id'])['data']['context_proposals'][0]['status']=='pending'


def test_motivation_cannot_be_linked_to_roles(guided):
 user=guided[0];a=role(user,'Intern');state=answer(guided,prepare(guided),'I am interested in transportation engineering.')
 with pytest.raises(HTTPException):approve(user,state,experience_ids=[a['id']])
 state=approve(user,state,experience_ids=[])
 result=db.list_entities(user,'profile_answer')[0]['data'];assert result['answer_kind']=='motivation' and result['experience_ids']==[]
 assert not any(r['id'].startswith('library:') for r in letters.state(user,state['id'])['sources'])


def test_link_editing_clearing_and_legacy_compatibility(guided):
 user=guided[0];a=role(user,'Intern');b=role(user,'Contractor');state=approve(user,answer(guided,prepare(guided),RAW),experience_ids=[a['id'],b['id']]);r=db.list_entities(user,'profile_answer')[0]
 # Older clients can archive without discarding additional links.
 r=library.edit(user,r['id'],ProfileAnswerEdit(expected_version=r['data']['version'],title=r['data']['title'],text=RAW,experience_id=a['id'],archived=True))
 assert library.experience_ids(r['data'])==[a['id'],b['id']]
 r=library.edit(user,r['id'],ProfileAnswerEdit(expected_version=r['data']['version'],title=r['data']['title'],text=RAW,experience_id=a['id'],experience_ids=[]))
 assert r['data']['experience_ids']==[] and r['data']['experience_id']=='' and r['data']['history'][0]['text']==RAW
 assert library.experience_ids({'experience_id':a['id']})==[a['id']]
 assert library.experience_ids({'experience_id':a['id'],'experience_ids':[]})==[]


def test_restore_rejects_unknown_plural_link_without_importing_anything(guided,client):
 user=guided[0];a=role(user,'Intern');approve(user,answer(guided,prepare(guided),RAW),experience_ids=[a['id']])
 backup=client.get('/api/account/export').json();before=len(db.list_entities(user,'profile_answer'))
 next(r for r in backup['records'] if r['kind']=='profile_answer')['data']['experience_ids'].append('not-owned')
 response=client.post('/api/account/import',files={'file':('bad.json',json.dumps(backup).encode(),'application/json')})
 assert response.status_code!=200 and len(db.list_entities(user,'profile_answer'))==before


def test_resume_review_has_separate_polished_candidate_and_exact_original(client,account,monkeypatch):
 from app import resume_conversation as resumes
 from app.models import ConversationStart,ConversationMessage,FactApproval
 user=account['id'];job=client.post('/api/jobs',json={'title':'Analyst','company':'Example','description':'Responsibilities\nExplain analytical methods.'}).json();target=role(user,'Analytical Intern')
 state=resumes.start(user,ConversationStart(job_id=job['id']));calls=[]
 async def model(schema,payload,*args,**kwargs):
  calls.append(payload);return {'message':'Review the polished candidate.','questions':[],'proposals':[{'record_id':target['id'],'category':'employment','title':target['data']['title'],'fields':[{'field':'contribution','value':RAW,'user_quote':RAW,'suggested_value':POLISHED}],'reason':'Explain the extraction work.','criterion_ids':[],'editing_note':'Removed repetition; retained the unfinished state.','improvement_suggestions':['Which errors did you target?']}],'action':'facts','revision_instruction':'','target_item_ids':[],'target_record_ids':[],'change_headline':False,'change_selection':False},META
 monkeypatch.setattr(ai,'structured',model)
 state=asyncio.run(resumes.send(user,state['id'],ConversationMessage(expected_version=state['data']['version'],text=RAW)))
 p=state['data']['proposals'][0];assert len(calls)==1 and p['fields'][0]['value']==RAW and p['fields'][0]['suggested_value']==POLISHED
 assert db.get(user,target['id'],'experience')==target
 state=resumes.approve(user,state['id'],FactApproval(expected_version=state['data']['version'],proposal_id=p['id'],action='approve',values={'contribution':POLISHED},update_draft=False))
 assert POLISHED in db.get(user,target['id'],'experience')['data']['contribution']
 source=db.list_entities(user,'profile_answer')[0]['data']['sources'][0]
 assert source['proposed_fields'][0]['user_quote']==RAW


def test_pending_wording_review_rejects_stale_answer_instead_of_replacing_it(guided,monkeypatch):
 user=guided[0];state=answer(guided,prepare(guided),RAW);p=state['data']['context_proposals'][0]
 def change(data,c):
  for q in data['questions']:
   if q['id'] in p['question_ids']:q['answer_version']=2
  for proposal in data['context_proposals']:proposal['answer_versions']={qid:1 for qid in p['question_ids']}
 letters.mutate(user,state['id'],state['data']['version'],change)
 async def forbidden(*args,**kwargs):raise AssertionError('Stale review must not dispatch')
 monkeypatch.setattr(ai,'structured',forbidden)
 with pytest.raises(HTTPException) as error:polish(user,letters.state(user,state['id']))
 assert error.value.status_code==409


def test_manual_answer_review_links_two_roles_without_provider(guided,client,monkeypatch):
 from test_connected_workflow import save_answer
 user=guided[0];a=role(user,'Intern');b=role(user,'Contractor');state=prepare(guided);q=state['data']['questions'][1];state=save_answer(user,state,'cover',RAW,q)
 def forbidden(*args,**kw):raise AssertionError('Manual approval never calls AI')
 monkeypatch.setattr(ai,'structured',forbidden)
 response=client.post('/api/profile-answers/review',json={'builder':'cover','conversation_id':state['id'],'question_id':q['id'],'expected_answer_version':1,'title':'Shared workflow','text':POLISHED,'experience_ids':[a['id'],b['id']]})
 assert response.status_code==200,response.text
 assert response.json()['data']['experience_ids']==[a['id'],b['id']]
 assert db.get(user,a['id'],'experience')==a and db.get(user,b['id'],'experience')==b
