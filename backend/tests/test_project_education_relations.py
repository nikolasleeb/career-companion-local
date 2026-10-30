"""Explicit project education/course/job links preserve provenance and ownership."""
import json
from app import db,profile_answers
from test_supporting_details import experience

def fixture(client):
 education=experience(client,'education','Fictional BS',organization='Example University',relevant_courses='CS 101 — Foundations\nCS 202 — Databases; Statistics')
 job=experience(client,'employment','Fictional engineer')
 course=experience(client,'coursework','Standalone course')
 return education,job,course

def test_multiselect_degree_without_course_old_clients_and_context(client,account):
 education,job,course=fixture(client)
 links={'linked_employment_ids':[job['id']],'linked_education_ids':[education['id'],course['id']],'linked_courses':[{'education_id':education['id'],'course':'CS 202 — Databases'}]}
 project=experience(client,'project','Fictional shared project',organization='Preserved old wording',**links)
 updated=client.put('/api/experience/'+project['id'],json={'category':'project','title':'Updated project','organization':'Preserved old wording','confirmed':True});assert updated.status_code==200,updated.text
 for key,value in links.items():assert updated.json()['data'][key]==value
 effective=next(r for r in profile_answers.records(account['id']) if r['id']==project['id'])
 assert len(effective['data']['related_jobs'])==1 and len(effective['data']['related_education'])==3
 degree_only=experience(client,'project','Degree alone',linked_education_ids=[education['id']]);assert not degree_only['data']['linked_courses']
 for invalid in ({'linked_education_ids':[job['id']]},{'linked_employment_ids':[education['id']]},{'linked_courses':[{'education_id':education['id'],'course':'Invented course'}]},{'linked_education_ids':['unowned']}):
  assert client.post('/api/experience',json={'category':'project','title':'Invalid',**invalid}).status_code==422
 assert client.post('/api/experience',json={'category':'skills','title':'Invalid','linked_education_ids':[education['id']]}).status_code==422
 unconfirmed=experience(client,'education','Unconfirmed degree',confirmed=False)
 assert client.post('/api/experience',json={'category':'project','title':'Invalid','linked_education_ids':[unconfirmed['id']]}).status_code==422
 assert client.post('/api/experience',json={'category':'project','title':'Invalid','linked_education_ids':[education['id'],education['id']]}).status_code==422

def test_course_edit_and_deleted_education_preserve_but_exclude_until_resolved(client,account):
 education,_,_=fixture(client)
 project=experience(client,'project','Course project',linked_courses=[{'education_id':education['id'],'course':'Statistics'}])
 assert client.put('/api/experience/'+education['id'],json={**education['data'],'relevant_courses':'CS 101 — Foundations'}).status_code==200
 assert project['id'] not in {r['id'] for r in profile_answers.records(account['id'])}
 # Old client still saves without dropping the unresolved historical association.
 assert client.put('/api/experience/'+project['id'],json={'category':'project','title':'Edited project','confirmed':True}).status_code==200
 assert client.put('/api/experience/'+project['id'],json={'category':'project','title':'Resolved project','confirmed':True,'linked_courses':[]}).status_code==200
 assert project['id'] in {r['id'] for r in profile_answers.records(account['id'])}

def test_backup_remaps_nested_course_and_education_ids_and_orphans(client,account):
 education,job,_=fixture(client)
 project=experience(client,'project','Backup linked project',linked_education_ids=[education['id']],linked_employment_ids=[job['id']],linked_courses=[{'education_id':education['id'],'course':'Statistics'}])
 def restore():
  raw=client.get('/api/account/export').json();response=client.post('/api/account/import',files={'file':('backup.json',json.dumps(raw).encode(),'application/json')});assert response.status_code==200,response.text
 restore()
 imported=next(r for r in db.list_entities(account['id'],'experience') if r['id']!=project['id'] and r['data']['title']=='Backup linked project')
 new_id=imported['data']['linked_education_ids'][0];assert new_id!=education['id']
 assert imported['data']['linked_courses'][0]['education_id']==new_id
 assert db.get(account['id'],new_id)['data']['title']=='Fictional BS'
 assert client.delete('/api/records/'+education['id']).status_code==200
 raw=client.get('/api/account/export').json();assert next(r for r in raw['records'] if r['id']==project['id'])['data']['unavailable_education_ids']==[education['id']]
 restore();assert db.get(account['id'],project['id'])['data']==project['data']

def test_cross_account_and_total_limit(client,account):
 education,job,_=fixture(client)
 schools=[experience(client,'education','Degree '+str(i)) for i in range(9)]
 assert client.post('/api/experience',json={'category':'project','title':'Too many','linked_education_ids':[r['id'] for r in schools]+[education['id']],'linked_employment_ids':[job['id']]}).status_code==422
 client.post('/api/auth/logout');client.headers.pop('X-CSRF-Token')
 other=client.post('/api/auth/register',json={'username':'projectother','password':'fictional-test-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
 assert client.post('/api/experience',json={'category':'project','title':'Other','linked_courses':[{'education_id':education['id'],'course':'Statistics'}]}).status_code==422


def test_internship_job_links_to_education_and_course_without_copying(client,account):
 education,job,course=fixture(client)
 body={**job['data'],'organization':'Fictional VDOT','linked_education_ids':[education['id'],course['id']],'linked_courses':[{'education_id':education['id'],'course':'Statistics'}]}
 response=client.put('/api/experience/'+job['id'],json=body);assert response.status_code==200,response.text
 saved=response.json();effective=next(r for r in profile_answers.records(account['id']) if r['id']==job['id'])
 assert len(effective['data']['related_education'])==3
 assert db.get(account['id'],education['id'])==education
 assert client.put('/api/experience/'+job['id'],json={'category':'employment','title':'Renamed internship','confirmed':True}).json()['data']['linked_courses']==body['linked_courses']
 assert client.post('/api/experience',json={'category':'employment','title':'Invalid','linked_employment_ids':[job['id']]}).status_code==422
 raw=client.get('/api/account/export').json();result=client.post('/api/account/import',files={'file':('internship.json',json.dumps(raw).encode(),'application/json')});assert result.status_code==200,result.text
 imported=next(r for r in db.list_entities(account['id'],'experience') if r['id']!=job['id'] and r['data']['title']=='Renamed internship')
 assert imported['data']['linked_courses'][0]['education_id']!=education['id']
 assert db.get(account['id'],imported['data']['linked_courses'][0]['education_id'])['data']['title']==education['data']['title']
