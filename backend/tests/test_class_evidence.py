import io,json,time
import pytest
from pypdf import PdfWriter
from app import db,course_evidence,profile_answers,resume_layout,resume_strategy,credentials

def school(client):
    r=client.post('/api/experience',json={'category':'education','title':'MS Data Science','organization':'Fictional University','degree':'MS','confirmed':True,'relevant_courses':'Cloud Computing; Data Engineering'})
    assert r.status_code==200,r.text
    return r.json()

def course(client,parent):return next(v for v in client.get('/api/profile-courses').json() if v['education_id']==parent['id'])

def detail(client,parent,c=None,token='fictional-detail',**changes):
    body={'title':'Cloud lab','text':'Configured Azure storage in a supervised class lab.','experience_ids':[parent['id']],'confirmed':True,'request_token':token,'course_refs':[{'education_id':parent['id'],'course_id':c['id']}] if c else []}
    return client.post('/api/profile-answers',json={**body,**changes})

def test_manual_detail_confirmation_idempotence_and_shared_links(client,account,monkeypatch):
    parent=school(client);other=client.post('/api/experience',json={'category':'project','title':'Fictional cloud exercise','confirmed':True}).json()
    monkeypatch.setattr(course_evidence.ai,'structured',lambda *a,**k:pytest.fail('Manual detail called AI'))
    assert detail(client,parent,confirmed=False).status_code==422
    r=detail(client,parent,experience_ids=[parent['id'],other['id']]);assert r.status_code==200,r.text
    again=detail(client,parent,experience_ids=[parent['id'],other['id']]);assert again.json()['id']==r.json()['id']
    assert len(db.list_entities(account['id'],'profile_answer'))==1
    assert detail(client,parent,text='Different details with the same save token.').status_code==409
    assert len(profile_answers.confirmed(account['id']))==1

def test_course_rename_preserves_identity_evidence_and_project_association(client,account):
    parent=school(client);c=course(client,parent)
    project=client.post('/api/experience',json={'category':'project','title':'Class project','confirmed':True,'linked_courses':[{'education_id':parent['id'],'course':c['title']}]}).json()
    r=detail(client,parent,c);assert r.status_code==200,r.text
    update={'title':'Azure Cloud Lab','status':'in_progress','expected_updated_at':parent['updated_at']}
    renamed=client.put('/api/profile-courses/'+parent['id']+'/'+c['id'],json=update)
    assert renamed.status_code==200,renamed.text
    assert renamed.json()['id']==c['id']
    assert db.get(account['id'],project['id'])['data']['linked_courses'][0]['course']=='Azure Cloud Lab'
    record=next(r for r in profile_answers.records(account['id']) if r['id']==parent['id'])
    assert 'Coursework — Azure Cloud Lab (in progress)' in record['data']['contribution']
    assert client.put('/api/profile-courses/'+parent['id']+'/'+c['id'],json=update).status_code==409
    assert len(profile_answers.confirmed(account['id']))==1

def test_class_missing_parent_and_account_isolation(client,account):
    parent=school(client);c=course(client,parent)
    assert detail(client,parent,c,experience_ids=['missing']).status_code in (404,422)
    r=client.post('/api/auth/register',json={'username':'other-student','password':'fictional-password-123'});assert r.status_code==200
    client.headers['X-CSRF-Token']=r.json()['csrf']
    school(client)
    assert not any(x['id']==c['id'] for x in client.get('/api/profile-courses').json())
    assert client.get('/api/profile-courses/'+parent['id']+'/'+c['id']+'/syllabi').status_code==404

def test_removed_class_blocks_reuse_and_manual_archive_retains_history(client,account):
    parent=school(client);c=course(client,parent);answer=detail(client,parent,c).json()
    payload={**parent['data'],'relevant_courses':'Other class'}
    assert client.put('/api/experience/'+parent['id'],json=payload).status_code==200
    assert not profile_answers.confirmed(account['id'])
    assert client.get('/api/profile-answers').json()[0]['data']['needs_related_experience'] is True
    body={'expected_version':1,'title':answer['data']['title'],'text':answer['data']['text'],'experience_ids':[parent['id']],'archived':True}
    assert client.put('/api/profile-answers/'+answer['id'],json=body).status_code==200
    assert len(db.get(account['id'],answer['id'])['data']['history'])==1

def upload(client,parent,c,content=b'Cloud Computing syllabus. Students practice Azure storage and Google Cloud BigQuery labs.'):
    return client.post('/api/profile-courses/'+parent['id']+'/'+c['id']+'/syllabi',files={'file':('syllabus.txt',content,'text/plain')})

def test_syllabus_upload_no_ai_dedup_and_scanned_manual_fallback(client,account,monkeypatch):
    parent=school(client);c=course(client,parent)
    monkeypatch.setattr(course_evidence.ai,'structured',lambda *a,**k:pytest.fail('Upload called AI'))
    r=upload(client,parent,c);assert r.status_code==200,r.text
    assert upload(client,parent,c).json()['id']==r.json()['id']
    assert not profile_answers.confirmed(account['id'])
    writer=PdfWriter();writer.add_blank_page(width=612,height=792);raw=io.BytesIO();writer.write(raw)
    scan=client.post('/api/profile-courses/'+parent['id']+'/'+c['id']+'/syllabi',files={'file':('scan.pdf',raw.getvalue(),'application/pdf')})
    assert scan.status_code==200,scan.text
    assert not scan.json()['data']['text'] and scan.json()['data']['warnings']
    assert client.get('/api/course-syllabi/'+scan.json()['id']+'/estimate').json()['readable'] is False

def wait(client,id):
    for _ in range(100):
        r=client.get('/api/tasks/'+id).json()
        if r['status'] not in ('queued','running','cancelling'):return r
        time.sleep(.01)
    pytest.fail('Task did not finish')

def test_syllabus_explicit_review_quotes_and_own_experience(client,account,monkeypatch):
    parent=school(client);c=course(client,parent);doc=upload(client,parent,c).json();calls=[]
    monkeypatch.setattr(credentials,'effective',lambda user:'fictional-key')
    async def fake(schema,payload,mode,**kw):
        calls.append(payload);assert kw['retry_allowed'] is False
        return {'topics':[{'topic':'Azure storage','quote':'Azure storage','question':'What did you personally configure in your lab?'}]},{'model':'fake','estimated_token_cost_usd':0}
    monkeypatch.setattr(course_evidence.ai,'structured',fake)
    body={'expected_version':1,'request_token':'syllabus-once','mode':'economy'}
    first=client.post('/api/course-syllabi/'+doc['id']+'/review',json=body);assert first.status_code==200,first.text
    assert wait(client,first.json()['task_id'])['status']=='completed'
    assert client.post('/api/course-syllabi/'+doc['id']+'/review',json=body).json()['task_id']==first.json()['task_id']
    assert len(calls)==1 and not profile_answers.confirmed(account['id'])
    reviewed=db.get(account['id'],doc['id'])
    approval={'expected_version':reviewed['data']['version'],'topic_id':reviewed['data']['review']['topics'][0]['id'],'title':'Azure coursework','text':'Created a storage account and uploaded sample files in a supervised Azure lab.','request_token':'approve-lab','confirmed':False}
    assert client.post('/api/course-syllabi/'+doc['id']+'/approve',json=approval).status_code==422
    result=client.post('/api/course-syllabi/'+doc['id']+'/approve',json={**approval,'confirmed':True});assert result.status_code==200,result.text
    assert len(profile_answers.confirmed(account['id']))==1
    assert client.delete('/api/course-syllabi/'+doc['id']).status_code==200
    assert len(profile_answers.confirmed(account['id']))==1
    assert client.get('/api/course-syllabi/'+doc['id']+'/download').status_code==404

def test_syllabus_rejects_unsupported_quote_without_saving(client,account,monkeypatch):
    parent=school(client);c=course(client,parent);doc=upload(client,parent,c).json()
    monkeypatch.setattr(credentials,'effective',lambda user:'fictional-key')
    async def fake(*args,**kw):return {'topics':[{'topic':'Made up tool','quote':'not in syllabus','question':'Did you use it?'}]},{}
    monkeypatch.setattr(course_evidence.ai,'structured',fake)
    task=client.post('/api/course-syllabi/'+doc['id']+'/review',json={'expected_version':1,'request_token':'bad-quote','mode':'economy'}).json()
    assert wait(client,task['task_id'])['status']=='failed'
    assert 'review' not in db.get(account['id'],doc['id'])['data']

def test_class_backup_restores_stable_references_and_private_original(client,account):
    parent=school(client);c=course(client,parent);answer=detail(client,parent,c).json();doc=upload(client,parent,c).json()
    backup=client.get('/api/account/export');assert backup.status_code==200,backup.text
    payload=backup.json();saved=next(r for r in payload['records'] if r['id']==parent['id'])
    assert any(v['id']==c['id'] for v in saved['data']['course_items'])
    assert doc['id'] in payload['files']
    restored=client.post('/api/account/import',files={'file':('backup.json',backup.content,'application/json')})
    assert restored.status_code==200,restored.text
    assert any(r['data']['course_refs'][0]['course_id']==c['id'] for r in profile_answers.confirmed(account['id']))
    assert len(db.list_entities(account['id'],'document'))==2

def test_pdf_space_excludes_bottom_margin_and_requires_two_lines():
    assert resume_layout.page_space([{'page':1,'y_max':710,'page_height':792}])['remaining_body_lines']==2
    assert resume_layout.page_space([{'page':1,'y_max':735,'page_height':792}])['remaining_body_lines']==0
    assert resume_layout.page_space([])['measured'] is False

def test_useful_space_candidates_respect_exclusions_relevance_and_generated_sources():
    rendered={'layout':{'pages':1,'page_space':{'remaining_body_lines':2}},'sections':[{'entries':[{'source_id':'school','content_items':[{'source_refs':[{'source_id':'used'}]}]}]}]}
    facts=[{'id':id,'field':field,'text':'A supported fact'} for id,field in [('used','description'),('good','contribution'),('excluded','skill'),('url','url'),('irrelevant','description')]]
    found=resume_strategy.space_candidates(rendered,{'facts':facts},{'priorities':[{'source_ids':['used','good','excluded','url']}]},{'excluded_source_ids':['excluded']})
    assert [f['id'] for f in found]==['good']
    rendered['layout']['page_space']['remaining_body_lines']=1
    assert resume_strategy.space_candidates(rendered,{'facts':facts},{'priorities':[]},{})==[]

def test_syllabus_limits_formats_stale_approval_and_private_download(client,account):
    parent=school(client);c=course(client,parent)
    assert client.post('/api/profile-courses/'+parent['id']+'/'+c['id']+'/syllabi',files={'file':('bad.csv',b'not a syllabus','text/csv')}).status_code==422
    assert upload(client,parent,c,b'x'*(10*1024*1024+1)).status_code in (413,422)
    writer=PdfWriter()
    for _ in range(31):writer.add_blank_page(width=612,height=792)
    raw=io.BytesIO();writer.write(raw)
    assert client.post('/api/profile-courses/'+parent['id']+'/'+c['id']+'/syllabi',files={'file':('long.pdf',raw.getvalue(),'application/pdf')}).status_code in (400,422)
    from docx import Document
    doc=Document();doc.add_paragraph('Course coverage includes cloud storage and supervised data pipeline labs.');raw=io.BytesIO();doc.save(raw)
    uploaded=client.post('/api/profile-courses/'+parent['id']+'/'+c['id']+'/syllabi',files={'file':('course.docx',raw.getvalue(),'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
    assert uploaded.status_code==200,uploaded.text
    id=uploaded.json()['id'];assert client.get('/api/course-syllabi/'+id+'/download').content==raw.getvalue()
    assert client.post('/api/course-syllabi/'+id+'/approve',json={'expected_version':9,'topic_id':'missing','title':'Lab','text':'My own lab work.','confirmed':True,'request_token':'stale'}).status_code==409
    other=client.post('/api/auth/register',json={'username':'other-files','password':'fictional-password-123'}).json();client.headers['X-CSRF-Token']=other['csrf'];school(client)
    for path,method in [('/download','GET'),('/estimate','GET'),('','DELETE')]:assert client.request(method,'/api/course-syllabi/'+id+path).status_code==404

def test_syllabus_cancellation_keeps_old_review_and_recovers_without_retry(client,account,monkeypatch):
    import asyncio
    parent=school(client);c=course(client,parent);doc=upload(client,parent,c).json();calls=[]
    monkeypatch.setattr(credentials,'effective',lambda user:'fictional-key')
    async def fake(*args,**kw):
        calls.append(1);await asyncio.sleep(.3)
        return {'topics':[{'topic':'Storage','quote':'Azure storage','question':'What did you personally do?'}]},{}
    monkeypatch.setattr(course_evidence.ai,'structured',fake)
    body={'expected_version':1,'request_token':'cancel-once','mode':'economy'}
    task=client.post('/api/course-syllabi/'+doc['id']+'/review',json=body).json()
    time.sleep(.03)
    assert client.delete('/api/course-syllabi/'+doc['id']).status_code==409
    assert client.post('/api/tasks/'+task['task_id']+'/cancel').status_code==200
    assert wait(client,task['task_id'])['status']=='cancelled'
    assert 'review' not in db.get(account['id'],doc['id'])['data']
    assert client.post('/api/course-syllabi/'+doc['id']+'/review',json=body).json()['task_id']==task['task_id']
    assert len(calls)<=1
    assert client.get('/api/profile-courses/'+parent['id']+'/'+c['id']+'/syllabi').json()['tasks'][0]['status']=='cancelled'

def test_class_applied_evidence_reaches_canonical_resume_once_and_renders(client,account,tmp_path):
    from app import resume_conversation
    from app.models import ConversationStart
    parent=school(client);c=course(client,parent);detail(client,parent,c)
    job=db.save(account['id'],'job',{'title':'Graduate cloud analyst','company':'Fictional Employer','description':'Use Python and cloud storage to analyze data.'})
    conversation=resume_conversation.start(account['id'],ConversationStart(job_id=job['id']))
    source=resume_conversation.source(account['id'],conversation['data']);facts=resume_strategy.catalog(source)['facts']
    matches=[f for f in facts if 'Configured Azure storage' in f['text']]
    assert len(matches)==1 and matches[0]['field']=='contribution'
    assert matches[0]['text'].startswith('Coursework — Cloud Computing (unspecified):')
    rendered=resume_layout.render(source)
    assert rendered['layout']['pages']==1 and rendered['layout']['page_space']['measured']
    assert rendered['layout']['page_space']['remaining_body_lines']>=2
    import base64
    pdf=base64.b64decode(rendered['artifacts']['pdf']);lines=resume_layout.text_lines(pdf)
    assert 'Configured Azure storage' in ' '.join(v['text'] for v in lines)
    assert not any('course-syllabi/' in v['text'] for v in lines)
    (tmp_path/'class-evidence.pdf').write_bytes(pdf)

def test_changing_only_class_link_marks_future_resume_context_stale(client,account):
    from app import resume_conversation
    from app.models import ConversationStart
    parent=school(client);courses=[v for v in client.get('/api/profile-courses').json() if v['education_id']==parent['id']]
    answer=detail(client,parent,courses[0]).json()
    job=db.save(account['id'],'job',{'title':'Analyst','company':'Example','description':'Analyze data.'})
    conversation=resume_conversation.start(account['id'],ConversationStart(job_id=job['id']))
    result=client.put('/api/profile-answers/'+answer['id'],json={'expected_version':1,'title':answer['data']['title'],'text':answer['data']['text'],'experience_ids':[parent['id']],'course_refs':[{'education_id':parent['id'],'course_id':courses[1]['id']}]})
    assert result.status_code==200,result.text
    assert db.get(account['id'],conversation['id'])['data']['profile_dirty'] is True
