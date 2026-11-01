import copy,io,json,zipfile
from docx import Document
from app import db,skill_details,profile_answers,profile_context,master_resume
from app.models import ExperienceItem

def group(client):
 r=client.post('/api/experience',json={'category':'skills','title':'Programming','confirmed':True,'skill_items':[{'name':'Python','level':'advanced'},{'name':'SQL','level':'intermediate'}]});assert r.status_code==200,r.text
 return r.json()
def state(client,g,skill=''):
 r=client.get('/api/experience/'+g['id']+'/supporting-details',params={'skill_id':skill});assert r.status_code==200,r.text;return r.json()
def save(client,g,skill,rows,revision=None):
 return client.put('/api/experience/'+g['id']+'/supporting-details',json={'revision':revision or state(client,g,skill)['revision'],'skill_id':skill,'confirmed':True,'statements':rows})
def structure(client,g):return client.get('/api/experience/'+g['id']+'/structure').json()
def update(client,s,choices=None):return client.put('/api/experience/'+s['id']+'/structure',json={'data':s['data'],'expected_updated_at':s['updated_at'],'details_revision':s['details_revision'],'removed_skill_scopes':choices or {}})
def legacy_detail(user,g):
 return db.save(user,'profile_answer',{'answer_kind':'experience','title':'Legacy group example','text':'Diagnosed a complex technical problem.','status':'confirmed','version':1,'experience_id':g['id'],'experience_ids':[g['id']],'sources':[{'builder':'manual_profile','manual_review':True}],'history':[]})

def test_isolated_lists_order_and_stale_saves(client,account):
 g=group(client);py,sql=[s['id'] for s in g['data']['skill_items']]
 r=save(client,g,py,[{'id':'one','text':'Built Python data validation.'},{'id':'two','text':'Used Python to test transformations.'}]);assert r.status_code==200,r.text
 first=r.json();assert state(client,g,sql)['statements']==[]
 r=save(client,g,sql,[{'id':'sql','text':'Used SQL to explain slow joins.'}]);assert r.status_code==200,r.text
 sql_record=db.get(account['id'],r.json()['statements'][0]['id'])
 rows=[{k:v for k,v in row.items() if k in ('id','text')} for row in reversed(first['statements'])]
 assert save(client,g,py,rows,first['revision']).status_code==409
 r=save(client,g,py,rows);assert r.status_code==200,r.text
 assert [v['text'] for v in r.json()['statements']]==[v['text'] for v in rows]
 assert db.get(account['id'],sql_record['id'])==sql_record
 assert save(client,g,py,[{'id':sql_record['id'],'text':'Try changing another skill.'}]).status_code==404
 assert client.put('/api/experience/'+g['id']+'/supporting-details',json={'revision':state(client,g)['revision'],'confirmed':True,'statements':[]}).status_code==422

def test_identity_rename_and_old_client_preservation(client,account):
 g=group(client);before=g['data']['skill_items'];s=structure(client,g)
 s['data']['skill_items']=list(reversed(s['data']['skill_items']));s['data']['skill_items'][1]['name']='Python programming'
 r=update(client,s);assert r.status_code==200,r.text
 assert r.json()['data']['skill_items'][1]['id']==before[0]['id']
 old=r.json()['data'];old['skill_items']=[{k:v for k,v in s.items() if k!='id'} for s in old['skill_items']]
 r=client.put('/api/experience/'+g['id'],json=old);assert r.status_code==200,r.text
 assert r.json()['data']['skill_items'][1]['id']==before[0]['id']

def test_legacy_projection_does_not_write(client,account):
 # Raw legacy data omits IDs. Reads must be deterministic without changing text or timestamps.
 with db.connect() as c:
  c.execute('INSERT INTO entities VALUES(?,?,?,?,?,?)',('legacy-skill',account['id'],'experience',json.dumps({'category':'skills','title':'Languages','confirmed':True,'skill_items':[{'name':'Python','level':'advanced'}]}),db.now(),db.now()))
 before=db.get(account['id'],'legacy-skill');a=structure(client,before);b=structure(client,before)
 assert a['data']['skill_items']==b['data']['skill_items'];assert db.get(account['id'],'legacy-skill')==before
 assert a['data']['skill_items'][0]['name']=='Python'
 skill=a['data']['skill_items'][0]['id'];assert save(client,before,skill,[{'id':'legacy-proof','text':'Used Python to validate imported values.'}]).status_code==200
 current=structure(client,before);current['data']['skill_items'][0]['name']='Python programming';assert update(client,current).status_code==200
 assert state(client,before,skill)['statements'][0]['text']=='Used Python to validate imported values.'

def test_legacy_assignment_and_evidence_scope(client,account):
 g=group(client);a=legacy_detail(account['id'],g);py=g['data']['skill_items'][0]['id']
 effective=next(v for v in profile_answers.records(account['id']) if v['id']==g['id'])
 assert a['data']['text'] not in effective['data'].get('contribution','')
 current=state(client,g)
 r=client.put('/api/experience/'+g['id']+'/skill-detail-assignments',json={'revision':current['revision'],'statements':[{'id':a['id'],'skill_id':py}]});assert r.status_code==200,r.text
 saved=db.get(account['id'],a['id'])['data'];assert saved['text']==a['data']['text'] and saved['sources']==a['data']['sources'] and saved['status']=='confirmed' and saved['history']
 assert state(client,g,g['data']['skill_items'][1]['id'])['statements']==[]
 effective=next(v for v in profile_answers.records(account['id']) if v['id']==g['id'])
 assert 'Skill — Python: '+a['data']['text'] in effective['data']['contribution']
 assert effective['data']['answer_sources'][0]['skill_name']=='Python'
 reusable=next(v for v in profile_answers.reusable(account['id'],'fictional-posting') if v['id']==a['id'])
 assert reusable['data']['text']=='Skill — Python: '+a['data']['text']
 sources,_=profile_context.sources(account['id']);source=next(v for v in sources if v.get('record_id')==a['id'])
 assert source['skill_ref']['skill_id']==py and source['skill_name']=='Python'

import pytest
@pytest.mark.parametrize('choice',['pending','archive','existing','new'])
def test_skill_removal_choices(client,account,choice):
 g=group(client);py,sql=[v['id'] for v in g['data']['skill_items']]
 assert save(client,g,py,[{'id':'a','text':'Developed a Python validation tool.'}]).status_code==200
 original=state(client,g,py)['statements'][0]['id'];s=structure(client,g);s['data']['skill_items']=s['data']['skill_items'][1:]
 assert update(client,s).status_code==409
 target=sql if choice=='existing' else 'new-skill-id' if choice=='new' else choice
 if choice=='new':s['data']['skill_items'].append({'id':target,'name':'Data engineering','level':'unknown'})
 r=update(client,s,{py:target});assert r.status_code==200,r.text
 d=db.get(account['id'],original)['data'];assert d['text']=='Developed a Python validation tool.' and d['history']
 assert (d.get('skill_ref') or {}).get('skill_id')==(target if choice in ('existing','new') else None)
 assert d['status']==('archived' if choice=='archive' else 'confirmed')


def test_cross_account_and_backup_remapping(client,account):
 g=group(client);py=g['data']['skill_items'][0]['id'];assert save(client,g,py,[{'id':'a','text':'Built Python validation tools.'}]).status_code==200
 backup=client.get('/api/account/export');assert backup.status_code==200
 payload=backup.json();oldref=next(v['data']['skill_ref'] for v in payload['records'] if v['kind']=='profile_answer' and v['data'].get('skill_ref'))
 client.post('/api/auth/logout',json={});r=client.post('/api/auth/register',json={'username':'another-student','password':'fictional-test-password'});assert r.status_code==200,r.text
 other=r.json();client.headers['X-CSRF-Token']=other['csrf']
 assert client.get('/api/experience/'+g['id']+'/supporting-details',params={'skill_id':py}).status_code==404
 new=group(client);assert client.get('/api/experience/'+new['id']+'/supporting-details',params={'skill_id':py}).status_code==404
 r=client.post('/api/account/import',files={'file':('backup.json',backup.content,'application/json')});assert r.status_code==200,r.text
 imported=[v for v in db.list_entities(other['id'],'profile_answer') if v['data'].get('skill_ref')];assert len(imported)==1
 ref=imported[0]['data']['skill_ref'];assert ref['experience_id']!=oldref['experience_id'] and ref['skill_id']!=oldref['skill_id']
 assert any(v['id']==ref['skill_id'] for v in db.get(other['id'],ref['experience_id'])['data']['skill_items'])
 broken=copy.deepcopy(payload);a=next(v for v in broken['records'] if v['kind']=='profile_answer' and v['data'].get('skill_ref'));a['data']['skill_ref']['skill_id']='unknown'
 before=len(db.list_entities(other['id'],'experience'));r=client.post('/api/account/import',files={'file':('backup.json',json.dumps(broken),'application/json')});assert r.status_code==400,r.text;assert len(db.list_entities(other['id'],'experience'))==before


def test_export_hierarchy_dates_course_dedup_and_skill_scope(client,account):
 g=group(client);py=g['data']['skill_items'][0]['id'];assert save(client,g,py,[{'id':'a','text':'Validated data with Python.'}]).status_code==200
 a=legacy_detail(account['id'],g)
 school=db.save(account['id'],'experience',ExperienceItem(category='education',title='Graduate study',degree='MS',organization='Example University',confirmed=True,relevant_courses='Databases; Networks',start_date='2022',expected_graduation='2028').model_dump())
 course=next(v for v in client.get('/api/profile-courses').json() if v['education_id']==school['id'])
 url='/api/experience/'+school['id']+'/supporting-details';state_=client.get(url,params={'course_id':course['id']}).json()
 r=client.put(url,json={'revision':state_['revision'],'course_id':course['id'],'confirmed':True,'statements':[{'id':'class','text':'Designed a database in my course.'}]});assert r.status_code==200,r.text
 project=db.save(account['id'],'experience',ExperienceItem(category='project',title='Nested project',confirmed=True,linked_education_ids=[school['id']],dates='January 2023 – May 2023',description='Developed the project.',project_url='https://example.com/project').model_dump())
 snap=master_resume.snapshot(account['id']);blocks=snap['blocks'];texts=[b['text'] for b in blocks]
 assert not any(v.startswith('Relevant classes:') for v in texts);assert texts.count('Databases')==1 and texts.count('Networks')==1
 i=texts.index('Databases');assert blocks[i]['kind']=='course' and blocks[i+1]['depth']>blocks[i]['depth'] and blocks[i+1]['text']=='Designed a database in my course.'
 i=texts.index('Nested project');assert blocks[i]['depth']==2 and blocks[i+1]['text']=='January 2023 – May 2023' and blocks[i+2]['depth']==3
 assert not any('Job/education dates:' in t for t in texts);assert 'https://example.com/project' in texts
 assert texts.index('Validated data with Python.')==texts.index('Python (advanced, self-rated)')+1
 assert texts.count(a['data']['text'])==1 and 'Skill details awaiting assignment' in texts
 doc=Document(io.BytesIO(master_resume.render_docx(snap)));paras=doc.paragraphs
 assert any(p.text=='Designed a database in my course.' and p.paragraph_format.left_indent.inches>.5 for p in paras)
 assert any(p.text=='Databases' and not p.paragraph_format.keep_together for p in paras)
 assert all(p.paragraph_format.first_line_indent.inches<0 for p in paras if p.text in ('Developed the project.','Designed a database in my course.'))


def test_skill_identity_collisions_are_rejected(client,account):
 g=group(client);second=group(client);s=structure(client,second)
 s['data']['skill_items'][0]['id']=g['data']['skill_items'][0]['id'];assert update(client,s).status_code==422
 s=structure(client,second);s['data']['skill_items'][0]['id']='pending';assert update(client,s).status_code==422
 s=structure(client,second);s['data']['skill_items'][0]['id']=g['id'];assert update(client,s).status_code==422
