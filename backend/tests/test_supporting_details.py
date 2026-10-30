"""Supporting details are one linked fact, with explicit story and source boundaries."""
import copy,json
import pytest
from app import db,profile_answers,coach_access,interview_practice as interviews

def experience(client,category,title,**changes):
 response=client.post('/api/experience',json={'category':category,'title':title,'confirmed':True,**changes});assert response.status_code==200,response.text;return response.json()
def attempt(client,user,voice=False):
 session=client.post('/api/interview-practice/sessions',json={}).json()
 question=db.save(user,'interview_question',{'session_id':session['id'],'question':'Describe feedback and improvements.','topic':'Feedback','evaluation_focus':[],'constraints':[],'examples':[],'hints':[],'references':[]})
 quotes=['I gathered stakeholder feedback on the workbench.','I implemented and tested the requested feature.','I reduced the sampling size to fit the compute resources.']
 value={'session_id':session['id'],'question_id':question['id'],'operation':'review','answer':' '.join(quotes),'voice_id':'fictional-voice' if voice else '', 'transcript_snapshot':' '.join(quotes) if voice else '', 'star':{},'profile_revision':'fictional','source_snapshot':[],'ai':{'model':'simulated'},'feedback':{'summary':'A factual story.','strengths':[],'improvements':[],'star':[],'profile_connections':[],'claims_to_clarify':[],'follow_up':'','references':[],'useful_details':[{'title':str(i),'user_quote':q,'text':'COACHING_DO_NOT_SAVE'} for i,q in enumerate(quotes)]}}
 return db.save(user,'interview_attempt',value),quotes

def save(client,row,ids,**changes):
 return client.post('/api/interview-practice/attempts/'+row['id']+'/supporting-details',json={'expected_updated_at':row['updated_at'],'candidate_ids':[0,1,2],'title':'Used feedback to improve the workbench','text':'I gathered feedback, implemented and tested a feature, and reduced the sampling size because of compute constraints.','experience_ids':ids,'reviewed':True,**changes})

def test_one_combined_detail_multiple_jobs_and_repeat_safe(client,account):
 user=account['id'];jobs=[experience(client,'employment',name) for name in ('Fictional planning internship','Fictional research contract')]
 project=experience(client,'project','Fictional Workbench',linked_employment_ids=[j['id'] for j in jobs]);row,quotes=attempt(client,user)
 assert save(client,row,[]).status_code==422
 result=save(client,row,[project['id']]);assert result.status_code==200,result.text
 record=db.get(user,result.json()['saved_id']);assert record['data']['experience_ids']==[project['id']]
 assert record['data']['sources'][0]['user_quotes']==quotes
 assert 'COACHING_DO_NOT_SAVE' not in record['data']['text']
 assert save(client,row,[project['id']]).json()['already_saved']
 assert save(client,row,[j['id'] for j in jobs],candidate_ids=[0]).status_code==409
 effective=next(r for r in profile_answers.records(user) if r['id']==project['id'])
 assert len(effective['data']['answer_sources'])==1 and len(effective['data']['related_jobs'])==2
 assert all('answer_sources' not in r['data'] for r in profile_answers.records(user) if r['id'] in {j['id'] for j in jobs})
 assert db.get(user,project['id'])==project

def test_legacy_unlinked_and_orphaned_are_visible_but_not_reused(client,account):
 user=account['id'];detail=db.save(user,'profile_answer',{'status':'confirmed','answer_kind':'experience','title':'Legacy detail','text':'OLD_UNLINKED_CLAIM','version':1,'experience_id':'','experience_ids':[],'sources':[],'history':[],'backed_fields':{},'scope':{}})
 assert detail['id'] not in {r['id'] for r in profile_answers.confirmed(user)}
 assert all('OLD_UNLINKED_CLAIM' not in json.dumps(r) for r in profile_answers.records(user))
 row=next(r for r in client.get('/api/profile-answers').json() if r['id']==detail['id']);assert row['data']['needs_related_experience']
 assert not coach_access.source_allowed(user,{'record_id':detail['id']})
 assert db.get(user,detail['id'])==detail
 target=experience(client,'project','Real related project')
 body={'expected_version':1,'title':detail['data']['title'],'text':detail['data']['text'],'experience_ids':[target['id']]}
 response=client.put('/api/profile-answers/'+detail['id'],json=body);assert response.status_code==200,response.text
 assert detail['id'] in {r['id'] for r in profile_answers.confirmed(user)}
 assert client.put('/api/profile-answers/'+detail['id'],json={**body,'expected_version':2,'experience_ids':[]}).status_code==422
 assert client.delete('/api/records/'+target['id']).status_code==200
 assert detail['id'] not in {r['id'] for r in profile_answers.confirmed(user)}
 assert db.get(user,detail['id'])['data']['experience_ids']==[target['id']]

def test_project_relations_ownership_stale_links_and_old_client(client,account):
 user=account['id'];job=experience(client,'employment','Fictional role');project=experience(client,'project','Fictional project',linked_employment_ids=[job['id']])
 assert client.put('/api/experience/'+project['id'],json={'category':'project','title':'Renamed project','confirmed':True}).json()['data']['linked_employment_ids']==[job['id']]
 assert client.post('/api/experience',json={'category':'project','title':'Bad project','confirmed':True,'linked_employment_ids':['unowned']}).status_code==422
 assert client.post('/api/experience',json={'category':'employment','title':'Bad role','linked_employment_ids':[job['id']]}).status_code==422
 assert client.delete('/api/records/'+job['id']).status_code==200
 row,_=attempt(client,user)
 assert not coach_access.source_allowed(user,{'record_id':project['id']})
 assert save(client,row,[project['id']]).status_code==422
 assert client.put('/api/experience/'+project['id'],json={'category':'project','title':'Renamed project','confirmed':True,'linked_employment_ids':[]}).status_code==200
 assert save(client,row,[project['id']]).status_code==200

@pytest.mark.parametrize('voice',[False,True])
def test_exact_excerpts_and_consent_boundaries(client,account,voice):
 user=account['id'];target=experience(client,'project','Fictional related project');row,quotes=attempt(client,user,voice)
 assert save(client,row,[target['id']],reviewed=False).status_code==422
 if voice:
  row=db.save(user,'interview_attempt',{**row['data'],'transcript_snapshot':quotes[0]},row['id'])
  assert save(client,row,[target['id']]).status_code==422
 else:
  row['data']['feedback']['useful_details'][1]['user_quotes']=['INVENTED_EXCERPT']
  row=db.save(user,'interview_attempt',row['data'],row['id']);assert save(client,row,[target['id']]).status_code==422
 row=db.save(user,'interview_attempt',{**row['data'],'operation':'guide'},row['id']);assert save(client,row,[target['id']]).status_code==422

def test_backup_preserves_project_job_and_detail_links_including_missing_targets(client,account):
 user=account['id'];job=experience(client,'employment','Fictional internship');project=experience(client,'project','Shared fictional project',linked_employment_ids=[job['id']]);row,_=attempt(client,user)
 saved=save(client,row,[project['id']]);assert saved.status_code==200
 before=db.get(user,saved.json()['saved_id'])
 raw=client.get('/api/account/export').json()
 restored=client.post('/api/account/import',files={'file':('support.json',json.dumps(raw).encode(),'application/json')});assert restored.status_code==200,restored.text
 imported=next(r for r in db.list_entities(user,'experience') if r['data']['title']==project['data']['title'] and r['id']!=project['id'])
 assert imported['data']['linked_employment_ids']!=[job['id']]
 imported_job=db.get(user,imported['data']['linked_employment_ids'][0]);assert imported_job['data']['title']==job['data']['title']
 imported_detail=next(r for r in db.list_entities(user,'profile_answer') if r['id']!=before['id']);assert imported_detail['data']['experience_ids']==[imported['id']]
 assert db.get(user,before['id'])==before
 assert client.delete('/api/records/'+job['id']).status_code==200
 raw=client.get('/api/account/export').json()
 assert next(r for r in raw['records'] if r['id']==project['id'])['data']['unavailable_employment_ids']==[job['id']]
 restored=client.post('/api/account/import',files={'file':('orphan.json',json.dumps(raw).encode(),'application/json')});assert restored.status_code==200,restored.text
 assert profile_answers.needs_link(user,before['data'])

def test_new_link_requires_owned_experience_and_approval_is_atomic(client,account):
 user=account['id'];project=experience(client,'project','Private fictional project');row,_=attempt(client,user)
 client.post('/api/auth/logout');client.headers.pop('X-CSRF-Token')
 other=client.post('/api/auth/register',json={'username':'otherdetail','password':'fictional-test-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
 assert client.get('/api/interview-practice/sessions/'+row['data']['session_id']).status_code==404
 assert save(client,row,[project['id']]).status_code==404
 other_attempt,_=attempt(client,other['id'])
 assert save(client,other_attempt,[project['id']]).status_code==404
 assert db.list_entities(other['id'],'profile_answer')==[]
 assert db.get(user,project['id'])==project


def test_orphaned_detail_backup_remains_repairable(client,account):
 user=account['id'];target=experience(client,'project','Later unavailable project');row,_=attempt(client,user)
 saved=save(client,row,[target['id']]);assert saved.status_code==200
 assert client.delete('/api/records/'+target['id']).status_code==200
 backup=client.get('/api/account/export').json()
 record=next(r for r in backup['records'] if r['id']==saved.json()['saved_id']);assert record['data']['unavailable_experience_ids']==[target['id']]
 result=client.post('/api/account/import',files={'file':('missing-project.json',json.dumps(backup).encode(),'application/json')});assert result.status_code==200,result.text
 assert all(profile_answers.needs_link(user,r['data']) for r in db.list_entities(user,'profile_answer'))
