"""Profile hierarchy, atomic detail lists, attribution and full master exports."""
import copy,io,json
from app import db,project_structure as structure,profile_answers,resume_data,resume_strategy,linked_project_evidence,master_resume
from app.models import ExperienceItem

def entry(client,category,title,**extra):
 r=client.post('/api/experience',json={'category':category,'title':title,'confirmed':True,**extra});assert r.status_code==200,r.text;return r.json()
def get(client,p):
 r=client.get('/api/experience/'+p['id']+'/structure');assert r.status_code==200,r.text;return r.json()
def save(client,p,**extra):return client.put('/api/experience/'+p['id']+'/structure',json={'expected_updated_at':p['updated_at'],'details_revision':p['details_revision'],'data':p['data'],**extra})
def setup(client):
 a=entry(client,'employment','First job',organization='Example A',start_date='2020-01',end_date='2022-01')
 b=entry(client,'education','Graduate study',organization='Example University',degree='MS',start_date='2022-01',end_date='2024-01')
 p=entry(client,'project','Shared research',description='Built the first prototype.\nPresented the later findings.',linked_employment_ids=[a['id']],linked_education_ids=[b['id']])
 return a,b,p

def test_read_only_legacy_projection_and_scoped_destinations(client,account):
 a,b,p=setup(client);before=copy.deepcopy(db.get(account['id'],p['id']))
 current=get(client,p);assert all(v['scope']['kind']=='unassigned' for v in current['data']['project_statements'])
 assert db.get(account['id'],p['id'])==before
 stages=current['data']['project_stages'];current['data']['project_statements'][0]['scope']={'kind':'stages','stage_ids':[stages[0]['id']]}
 current['data']['project_statements'][1]['scope']={'kind':'project','stage_ids':[]}
 r=save(client,current);assert r.status_code==200,r.text
 assert r.json()['data']['description']==before['data']['description']
 effective=next(r for r in profile_answers.records(account['id']) if r['id']==p['id'])
 project=resume_data.entry_snapshot(effective['data'],p['id']);jobs=[resume_data.entry_snapshot(v['data'],v['id']) for v in (a,b)]
 snap={'sections':[{'entries':[project,*jobs]}]};catalog=resume_strategy.catalog(snap)
 first=next(f for f in catalog['facts'] if f['text']=='Built the first prototype.')
 assert set(first['allowed_destinations'])=={p['id'],a['id']}
 auto=linked_project_evidence.automatic(snap);byid={v['source_id']:v for v in auto['sections'][0]['entries']}
 assert not any(i['original']=='Built the first prototype.' for i in byid[b['id']]['content_items'])
 assert any(i['original']=='Presented the later findings.' for i in byid[b['id']]['content_items'])
 row=next(v for v in linked_project_evidence.candidates(account['id']) if v['project_id']==p['id'] and v['original']=='Built the first prototype.')
 choice={k:row[k] for k in ('project_id','item_id','source_fingerprint')};choice.update(placement='employment',employment_id=a['id'],replace_overlaps=False)
 placed=linked_project_evidence.apply(snap,linked_project_evidence.checked(account['id'],[choice]))
 fact=next(f for f in resume_strategy.catalog(placed)['facts'] if f['text']=='Built the first prototype.')
 assert set(fact['allowed_destinations'])=={p['id'],a['id']}

def test_atomic_details_archive_restore_and_conflicts(client,account):
 a=entry(client,'employment','Example role');url='/api/experience/'+a['id']+'/supporting-details'
 state=client.get(url).json();body={'revision':state['revision'],'confirmed':True,'statements':[{'id':'new-a','text':'Diagnosed a difficult data issue.'},{'id':'new-b','text':'Documented the method and limitations.'}]}
 r=client.put(url,json=body);assert r.status_code==200,r.text
 saved=r.json();assert len(saved['statements'])==2
 assert client.put(url,json=body).status_code==409
 ids=[v['id'] for v in saved['statements']];body.update(revision=saved['revision'],statements=[saved['statements'][1]])
 body['statements']=[{k:v for k,v in body['statements'][0].items() if k in ('id','text','scope')}]
 r=client.put(url,json=body);assert r.status_code==200,r.text
 assert r.json()['archived_count']==1;assert db.get(account['id'],ids[0])['data']['status']=='archived'
 state=r.json();restore=state['archived_statements'][0];r=client.put(url,json={'revision':state['revision'],'confirmed':True,'statements':[{k:v for k,v in x.items() if k in ('id','text','scope')} for x in [restore,*state['statements']]]})
 assert r.status_code==200,r.text;assert r.json()['statements'][0]['id']==ids[0]
 # An invalid late item rolls the entire batch back.
 old=client.get(url).json();r=client.put(url,json={'revision':old['revision'],'confirmed':True,'statements':[{'id':ids[0],'text':'An edited professional statement.'},{'id':'late','text':'My citizenship is private.'}]})
 assert r.status_code==422;assert client.get(url).json()==old

def test_detach_is_atomic_and_retains_details(client,account):
 a,b,p=setup(client);current=get(client,p);stage=current['data']['project_stages'][0]
 url='/api/experience/'+p['id']+'/supporting-details';state=client.get(url).json()
 r=client.put(url,json={'revision':state['revision'],'confirmed':True,'statements':[{'id':'deep','text':'Investigated the original prototype during the first role.','scope':{'kind':'stages','stage_ids':[stage['id']]}}]});assert r.status_code==200,r.text
 current=get(client,p);current['data']['linked_employment_ids']=[];current['data']['project_stages']=current['data']['project_stages'][1:]
 assert save(client,current).status_code==422
 r=save(client,current,detached_stage_scopes={stage['id']:{'kind':'unassigned','stage_ids':[]}});assert r.status_code==200,r.text
 state=client.get(url).json();assert state['statements'][0]['scope']['kind']=='unassigned'
 assert state['statements'][0]['text']=='Investigated the original prototype during the first role.'
 assert db.get(account['id'],state['statements'][0]['id'])['data']['history']

def test_foreign_references_and_stale_edits_rejected(client,account):
 a,b,p=setup(client);current=get(client,p)
 with db.connect() as c:c.execute('INSERT INTO users VALUES(?,?,?,?,?)',('foreign-account','other-student','unused-test-hash','{}',db.now()))
 foreign=db.save('foreign-account','experience',ExperienceItem(category='employment',title='Foreign job',confirmed=True).model_dump())
 bad=copy.deepcopy(current);bad['data']['linked_employment_ids']=[foreign['id']];bad['data']['project_stages'][0]['parent_id']=foreign['id']
 assert save(client,bad).status_code==422
 assert client.get('/api/experience/'+foreign['id']+'/supporting-details').status_code==404
 current['data']['title']='Updated project';assert save(client,current).status_code==200
 assert save(client,current).status_code==409
 assert client.delete('/api/records/'+a['id']).status_code==409

def test_course_statements_are_not_education_statements(client,account):
 school=entry(client,'education','Degree',organization='Example',degree='BS',relevant_courses='Databases; Networks')
 courses=client.get('/api/profile-courses').json();course=next(c for c in courses if c['education_id']==school['id'])
 url='/api/experience/'+school['id']+'/supporting-details';state=client.get(url+'?course_id='+course['id']).json()
 r=client.put(url,json={'revision':state['revision'],'course_id':course['id'],'confirmed':True,'statements':[{'id':'course-detail','text':'Implemented a query planner in a class assignment.'}]});assert r.status_code==200,r.text
 assert client.get(url).json()['statements']==[]
 assert len(client.get(url+'?course_id='+course['id']).json()['statements'])==1

def test_backup_remaps_stages_and_scopes_without_losing_text(client,account):
 a,b,p=setup(client);current=get(client,p);current['data']['project_statements'][0]['scope']={'kind':'stages','stage_ids':[current['data']['project_stages'][0]['id']]};assert save(client,current).status_code==200
 url='/api/experience/'+p['id']+'/supporting-details';state=client.get(url).json();r=client.put(url,json={'revision':state['revision'],'confirmed':True,'statements':[{'id':'backup-detail','text':'A detailed example with preserved source history.','scope':current['data']['project_statements'][0]['scope']}]});assert r.status_code==200,r.text
 backup=client.get('/api/account/export').json();r=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')});assert r.status_code==200,r.text
 projects=[r for r in db.list_entities(account['id'],'experience') if r['data']['title']=='Shared research'];assert len(projects)==2
 imported=next(v for v in projects if v['id']!=p['id']);stage=imported['data']['project_stages'][0]
 assert stage['parent_id']!=a['id'];assert stage['id']==stage['parent_id']+':stage'
 assert imported['data']['project_statements'][0]['scope']['stage_ids']==[stage['id']]
 imported_detail=client.get('/api/experience/'+imported['id']+'/supporting-details').json()['statements'][0]
 assert imported_detail['scope']['stage_ids']==[stage['id']]


def test_master_export_complete_scoped_private_free_and_versioned(client,account):
 a,b,p=setup(client);current=get(client,p);current['data']['project_statements'][0]['scope']={'kind':'stages','stage_ids':[current['data']['project_stages'][0]['id']]};current['data']['project_statements'][1]['scope']={'kind':'project','stage_ids':[]};assert save(client,current).status_code==200
 db.update_settings(account['id'],{'name':'Fictional Applicant','email':'fictional@example.invalid','citizenship':'NEVER EXPORT','openai_key':'NEVER EXPORT'})
 draft=entry(client,'project','Unreviewed project',confirmed=False)
 value=master_resume.snapshot(account['id']);text='\n'.join(b['text'] for b in value['blocks']);assert text.count('Built the first prototype.')==1;assert text.count('Presented the later findings.')==2
 assert 'NEVER EXPORT' not in json.dumps(value);assert 'Unreviewed project' not in text;assert value['omitted']['draft_entries']==1
 r=client.get('/api/profile/master-resume/export/docx?revision='+value['revision']);assert r.status_code==200,r.text
 from docx import Document
 paragraphs=[p.text for p in Document(io.BytesIO(r.content)).paragraphs]
 assert paragraphs.count('Presented the later findings.')==2
 entry(client,'volunteering','New confirmed role');assert client.get('/api/profile/master-resume/export/docx?revision='+value['revision']).status_code==409

def test_master_pdf_flows_multiple_pages_and_pending_statements_once(client,account):
 a,b,p=setup(client);project=get(client,p);project['data']['project_statements']=[{'id':'long-'+str(i),'field':'description','text':('Detailed statement '+str(i)+': documented the experimental procedure and its supported limitations. ')*4,'scope':{'kind':'unassigned','stage_ids':[]}} for i in range(30)];assert save(client,project).status_code==200
 value=master_resume.snapshot(account['id']);raw=master_resume.render_docx(value)
 from app import documents
 from pypdf import PdfReader
 reader=PdfReader(io.BytesIO(documents.docx_pdf(raw)));assert len(reader.pages)>2
 text='\n'.join(p.extract_text() for p in reader.pages);assert 'Timeline assignment pending' in text;assert 'Detailed statement 29:' in text;assert 'Page 1' in text


def test_attaching_parent_preserves_implicit_legacy_detail_scope(client,account):
 a=entry(client,'employment','Original role');b=entry(client,'employment','Later role')
 p=entry(client,'project','Continuing project',description='Built the original tool.',linked_employment_ids=[a['id']])
 r=client.post('/api/profile-answers',json={'title':'Original detail','text':'Evaluated the first prototype during the original role.','experience_ids':[p['id']],'confirmed':True,'request_token':'legacy-before-parent-attachment'});assert r.status_code==200,r.text
 current=get(client,p);original_stage=current['data']['project_stages'][0]['id']
 current['data']['linked_employment_ids'].append(b['id']);current['data']['project_stages'].append({'id':b['id']+':stage','parent_id':b['id'],'start_date':'','end_date':''})
 saved=save(client,current);assert saved.status_code==200,saved.text
 detail=client.get('/api/experience/'+p['id']+'/supporting-details').json()['statements'][0]
 assert detail['scope']=={'kind':'stages','stage_ids':[original_stage]}
 assert saved.json()['data']['project_statements'][0]['scope']['stage_ids']==[original_stage]
