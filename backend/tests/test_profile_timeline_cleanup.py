"""Timeline eligibility, nonduplicated ownership and master export hierarchy."""
import copy,io,json
from docx import Document
from app import db,master_resume,project_structure as structure,profile_answers,resume_data,resume_strategy
from test_profile_structure import entry,get,save


def add_detail(client,project,text,scope=None):
 url=f"/api/experience/{project['id']}/supporting-details";state=client.get(url).json()
 row={'id':'example-detail','text':text}
 if scope is not None:row['scope']=scope
 response=client.put(url,json={'revision':state['revision'],'confirmed':True,'statements':[row]})
 assert response.status_code==200,response.text
 return response.json()


def test_timelines_count_distinct_owners_not_courses(client,account):
 school=entry(client,'education','Graduate degree',degree='MS',relevant_courses='Networks; Databases')
 job=entry(client,'employment','Research job')
 p=entry(client,'project','Academic project',linked_education_ids=[school['id']],linked_courses=[{'education_id':school['id'],'course':'Networks'},{'education_id':school['id'],'course':'Databases'}])
 assert not get(client,p)['timeline_enabled']
 assert not client.get(f"/api/experience/{p['id']}/supporting-details").json()['timeline_enabled']
 current=get(client,p);current['data']['linked_employment_ids']=[job['id']]
 response=save(client,current);assert response.status_code==200,response.text
 assert response.json()['timeline_enabled']
 standalone=entry(client,'project','Independent project');assert not get(client,standalone)['timeline_enabled']


def test_simple_project_splits_use_sole_parent_without_changing_unchanged_ids(client,account):
 job=entry(client,'employment','Research job')
 p=entry(client,'project','Tool',linked_employment_ids=[job['id']],description='Built and tested the tool.\nWrote documentation.')
 current=get(client,p);assert save(client,current).status_code==200
 old=get(client,p);kept=old['data']['project_statements'][1]
 old['data']['description']='Built the tool.\nTested the tool.\nWrote documentation.'
 response=save(client,old);assert response.status_code==200,response.text
 rows=response.json()['data']['project_statements'];assert rows[-1]==kept
 assert all(structure.permits(v['scope'],response.json()['data'],job['id']) for v in rows)
 assert all(v['scope']['kind']!='unassigned' for v in rows)
 assert master_resume.snapshot(account['id'])['pending_projects']==0


def test_second_parent_freezes_explicit_whole_project_content(client,account):
 first=entry(client,'employment','First job');second=entry(client,'employment','Second job')
 p=entry(client,'project','Tool',linked_employment_ids=[first['id']],description='Built the tool.')
 current=get(client,p);current['data']['project_statements'][0]['scope']={'kind':'project','stage_ids':[]};assert save(client,current).status_code==200
 detail=add_detail(client,p,'Investigated a repeatable processing failure.',{'kind':'project','stage_ids':[]})['statements'][0]
 before=copy.deepcopy(db.get(account['id'],detail['id']))
 current=get(client,p);current['data']['linked_employment_ids'].append(second['id'])
 response=save(client,current);assert response.status_code==200,response.text
 data=response.json()['data'];row=data['project_statements'][0]
 assert structure.destinations(row['scope'],data)==[first['id']]
 saved=db.get(account['id'],detail['id']);scope=saved['data']['project_scopes'][p['id']]
 assert structure.destinations(scope,data)==[first['id']]
 assert saved['data']['history'][-1]['project_scopes']==before['data']['project_scopes']
 assert saved['data']['experience_ids']==[p['id']]
 # Existing consumer contracts allow the first job through the project, not the second.
 effective=next(r for r in profile_answers.records(account['id']) if r['id']==p['id'])
 snapshot=resume_data.entry_snapshot(effective['data'],p['id']);catalog=resume_strategy.catalog({'sections':[{'entries':[snapshot]}]})
 fact=next(f for f in catalog['facts'] if f['text']==row['text'])
 assert first['id'] in fact['allowed_destinations'] and second['id'] not in fact['allowed_destinations']
 detail_fact=next(f for f in catalog['facts'] if f['text']=='Investigated a repeatable processing failure.')
 assert first['id'] in detail_fact['allowed_destinations'] and second['id'] not in detail_fact['allowed_destinations']


def test_simple_project_dates_and_legacy_restrictions_are_preserved(client,account):
 school=entry(client,'education','MS degree',degree='MS',start_date='2021',expected_graduation='2028')
 p=entry(client,'project','Class project',linked_education_ids=[school['id']],description='Documented the class experiment.',start_date='2023-01',end_date='2023-05')
 current=get(client,p);current['data']['project_stages'][0].update(start_date='2022-01',end_date='2024-01')
 current['data']['project_statements'][0]['scope']={'kind':'unassigned','stage_ids':[]}
 response=save(client,current);assert response.status_code==200,response.text
 detail=add_detail(client,p,'Preserved project-only legacy restriction.',{'kind':'unassigned','stage_ids':[]})
 # A compatibility save omitting scope preserves explicit project-only restrictions.
 row=detail['statements'][0];url=f"/api/experience/{p['id']}/supporting-details"
 r=client.put(url,json={'revision':detail['revision'],'confirmed':True,'statements':[{'id':row['id'],'text':row['text']}]});assert r.status_code==200,r.text
 assert r.json()['statements'][0]['scope']['kind']=='unassigned'
 value=master_resume.snapshot(account['id']);texts=[b['text'] for b in value['blocks']]
 assert value['pending_projects']==0 and not any('Timeline assignment' in t for t in texts)
 assert texts.count(row['text'])==1 and texts.count('Documented the class experiment.')==1
 i=texts.index('Class project');assert '2023' in texts[i+1] and '2022' not in texts[i+1] and '2028' not in texts[i+1]
 assert get(client,p)['data']['project_stages'][0]['start_date']=='2022-01'
 effective=get(client,p)['data'];assert structure.destinations(effective['project_statements'][0]['scope'],effective)==[]
 # With no project dates the stage and graduation dates still must not leak in.
 current=get(client,p);current['data'].update(start_date='',end_date='',dates='');assert save(client,current).status_code==200
 blocks=master_resume.snapshot(account['id'])['blocks'];i=next(i for i,b in enumerate(blocks) if b['text']=='Class project')
 assert blocks[i+1]['kind']=='bullet'


def test_one_detail_per_parent_subtree_without_changing_legacy_links(client,account):
 first=entry(client,'employment','First job');second=entry(client,'employment','Second job')
 project=entry(client,'project','Shared tool',linked_employment_ids=[first['id'],second['id']])
 text='Measured a repeatable result and documented the limitations.'
 r=client.post('/api/profile-answers',json={'title':'Shared evidence','text':text,'experience_ids':[project['id'],first['id'],second['id']],'confirmed':True,'request_token':'shared-identity-dedup'});assert r.status_code==200,r.text
 row=r.json();data=copy.deepcopy(row['data']);data['project_scopes']={project['id']:{'kind':'project','stage_ids':[]}}
 db.save(account['id'],'profile_answer',data,row['id']);before=db.get(account['id'],row['id'])
 blocks=master_resume.snapshot(account['id'])['blocks'];assert sum(b['text']==text for b in blocks)==2
 assert all(blocks[i-1]['text']=='Supporting Details' and b['depth']==4 for i,b in enumerate(blocks) if b['text']==text)
 assert db.get(account['id'],row['id'])==before
 # A separately saved, identical job detail is a separate record and is retained.
 r=client.post('/api/profile-answers',json={'title':'Separate job evidence','text':text,'experience_ids':[first['id']],'confirmed':True,'request_token':'separate-job-evidence'});assert r.status_code==200,r.text
 assert sum(b['text']==text for b in master_resume.snapshot(account['id'])['blocks'])==3


def test_project_detail_connection_staleness_and_backup_history(client,account):
 first=entry(client,'employment','First job');second=entry(client,'employment','Second job')
 p=entry(client,'project','Tool',linked_employment_ids=[first['id']],description='Built the prototype.')
 state=add_detail(client,p,'Investigated a processing issue and documented the result.')
 current=get(client,p);current['data']['linked_employment_ids'].append(second['id']);assert save(client,current).status_code==200
 url=f"/api/experience/{p['id']}/supporting-details"
 r=client.put(url,json={'revision':state['revision'],'confirmed':True,'statements':[{'id':state['statements'][0]['id'],'text':'Stale changed detail.'}]});assert r.status_code==409
 assert client.get(url).json()['statements'][0]['text']==state['statements'][0]['text']
 backup=client.get('/api/account/export').json();r=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')});assert r.status_code==200,r.text
 imported=next(v for v in db.list_entities(account['id'],'experience') if v['data']['title']=='Tool' and v['id']!=p['id'])
 original_detail=db.get(account['id'],state['statements'][0]['id'])['data']
 imported_detail=client.get(f"/api/experience/{imported['id']}/supporting-details").json()['statements'][0]
 assert imported_detail['text']==original_detail['text'] and len(imported_detail['scope']['stage_ids'])==1
 assert len(structure.destinations(imported_detail['scope'],imported['data']))==1


def test_export_semantic_styles_and_regular_skills_details(client,account):
 school=entry(client,'education','Graduate degree',degree='MS',relevant_courses='Cloud; Databases')
 p=entry(client,'project','Research project',linked_education_ids=[school['id']],description='Built the research pipeline.')
 skills=entry(client,'skills','Programming',skill_items=[{'name':'Python','level':'unknown'}])
 add_detail(client,p,'Documented the project limitations.')
 blocks=master_resume.snapshot(account['id'])['blocks'];doc=Document(io.BytesIO(master_resume.render_docx(master_resume.snapshot(account['id']))));paragraphs={p.text:p for p in doc.paragraphs}
 assert paragraphs['Education'].style.font.size.pt==16
 assert paragraphs[resume_data.entry_snapshot(school['data'],school['id'])['title']].style.font.size.pt==14
 assert paragraphs['Projects'].style.font.size.pt==12.5
 assert paragraphs['Coursework'].style.font.size.pt==12.5
 assert paragraphs['Research project'].style.font.size.pt==11.5
 for text in ['Cloud','Python','Built the research pipeline.','Documented the project limitations.']:
  paragraph=paragraphs[text];assert not paragraph.style.font.bold and not any(r.bold for r in paragraph.runs)
 assert paragraphs['Research project'].paragraph_format.left_indent>paragraphs['Projects'].paragraph_format.left_indent
 assert paragraphs['Documented the project limitations.'].paragraph_format.left_indent>paragraphs['Research project'].paragraph_format.left_indent
 assert sum(b['text']=='Cloud' for b in blocks)==1


def test_deliberate_whole_project_review_can_accompany_second_connection(client,account):
 first=entry(client,'employment','Original role');second=entry(client,'employment','Later role')
 p=entry(client,'project','Continuing tool',linked_employment_ids=[first['id']],description='Built a reusable workflow.')
 current=get(client,p);current['data']['project_statements'][0]['scope']={'kind':'project','stage_ids':[]};assert save(client,current).status_code==200
 current=get(client,p);current['data']['linked_employment_ids'].append(second['id']);ids=[row['id'] for row in current['data']['project_statements']]
 r=save(client,current,reviewed_project_scope_ids=['foreign-statement']);assert r.status_code==422
 r=save(client,current,reviewed_project_scope_ids=ids);assert r.status_code==200,r.text
 assert set(structure.destinations(r.json()['data']['project_statements'][0]['scope'],r.json()['data']))=={first['id'],second['id']}


def test_old_editor_parent_attachment_retains_legacy_overview_destinations(client,account):
 first=entry(client,'employment','Original role');second=entry(client,'employment','Later role')
 p=entry(client,'project','Legacy tool',linked_employment_ids=[first['id']],description='Built a data preparation tool.')
 response=client.put('/api/experience/'+p['id'],json={**p['data'],'linked_employment_ids':[first['id'],second['id']]})
 assert response.status_code==200,response.text
 data=get(client,p)['data'];assert structure.destinations(data['project_statements'][0]['scope'],data)==[first['id']]


def test_employment_saves_keep_hidden_legacy_academic_links(client,account):
 school=entry(client,'education','Academic degree',degree='MS',relevant_courses='Internship')
 job=entry(client,'employment','Research job',linked_education_ids=[school['id']],linked_courses=[{'education_id':school['id'],'course':'Internship'}])
 current=get(client,job);current['data']['description']='Updated responsibilities.';response=save(client,current)
 assert response.status_code==200,response.text
 assert response.json()['data']['linked_education_ids']==[school['id']]
 assert response.json()['data']['linked_courses']==job['data']['linked_courses']


def test_editing_restricted_simple_legacy_bullet_uses_implicit_connection(client,account):
 job=entry(client,'employment','Original role');p=entry(client,'project','Single tool',linked_employment_ids=[job['id']],description='Built a prototype.')
 current=get(client,p);current['data']['project_statements'][0]['scope']={'kind':'unassigned','stage_ids':[]};assert save(client,current).status_code==200
 current=get(client,p);identity=current['data']['project_statements'][0]['id'];current['data']['description']='Built an improved prototype.'
 response=save(client,current);assert response.status_code==200,response.text
 row=response.json()['data']['project_statements'][0]
 assert row['id']==identity and structure.destinations(row['scope'],response.json()['data'])==[job['id']]
