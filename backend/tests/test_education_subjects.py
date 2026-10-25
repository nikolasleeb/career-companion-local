from conftest import without_setup
import io
import json
import pytest
from pydantic import ValidationError
from app import ai,db,resume_data,resume_parser
from app.models import ExperienceItem


def test_subject_normalization_and_explicit_clearing():
    old=ExperienceItem(category='education',title='BS',major='Economics & Politics',minor='Music')
    assert old.majors==['Economics & Politics'] and old.minors==['Music']
    data=ExperienceItem(title='BS',major='Stale',majors=[' Mathematics ','Computer Science','mathematics'],minor='Stale',minors=[])
    assert data.majors==['Mathematics','Computer Science'] and data.major=='Mathematics'
    assert data.minors==[] and data.minor==''
    assert ExperienceItem(title='BS',major='Old',majors=[]).major==''
    for fields in [{'majors':['x']*6},{'minors':['x'*201]},{'majors':'Math'}]:
        with pytest.raises(ValidationError):ExperienceItem(title='BS',**fields)


def test_all_subjects_survive_endpoints_exports_backup_and_import(client,account):
    response=client.post('/api/experience',json={'category':'education','title':'BS','degree':'BS','organization':'Example University','confirmed':True,'majors':['Computer Science','Mathematics'],'minors':['Music','History']})
    assert response.status_code==200,response.text
    record=response.json();data=record['data']
    snapshot=resume_data.entry_snapshot(data,record['id'])
    assert snapshot['title']=='BS in Computer Science & Mathematics'
    assert 'Minors: Music; History' in snapshot['bullets']
    assert all(subject in ai.experience_text(data) for subject in data['majors']+data['minors'])
    version=client.post('/api/resumes',json={'experience_ids':[record['id']]}).json()
    text=client.get('/api/resumes/'+version['id']+'/export/txt').text
    assert all(subject in text for subject in data['majors']+data['minors'])
    backup=client.get('/api/account/export').json()
    assert next(r for r in backup['records'] if r['id']==record['id'])['data']['minors']==['Music','History']
    restored=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup),'application/json')})
    assert restored.status_code==200,restored.text
    rows=without_setup(db.list_entities(account['id'],'experience'))
    assert len(rows)==2 and all(r['data']['majors']==data['majors'] for r in rows)
    changed=client.put('/api/experience/'+record['id'],json={**data,'majors':['Physics'],'minors':[]})
    assert changed.status_code==200 and changed.json()['data']['minor']==''
    assert client.get('/api/resumes/'+version['id']+'/export/txt').text==text


def test_legacy_reads_keep_every_combined_subject_and_do_not_rewrite(client,account):
    legacy={'category':'education','title':'BS','degree':'BS','major':'Economics & Politics','minor':'Music & History','confirmed':True}
    record=db.save(account['id'],'experience',legacy)
    snapshot=resume_data.entry_snapshot(record['data'],record['id'])
    assert snapshot['title']=='BS in Economics & Politics'
    assert 'Minor: Music & History' in snapshot['bullets']
    assert db.get(account['id'],record['id'])==record


def test_multiple_subjects_in_reviewed_resume_import(client,account):
    upload=client.post('/api/documents?purpose=resume',files={'file':('resume.txt',b'EDUCATION\nBachelor of Science in Mathematics | Example University\nMinor: Music','text/plain')})
    assert upload.status_code==200,upload.text
    doc=upload.json();parsed=doc['data']['resume_parse'];entry=next(e for e in parsed['entries'] if e['data']['category']=='education')
    data={**entry['data'],'majors':['Mathematics','Computer Science'],'minors':['Music','History']}
    result=client.post('/api/documents/'+doc['id']+'/import-resume',json={'text_hash':parsed['text_hash'],'profile_updates':{},'entries':[{'id':entry['id'],'data':data}],'reviewed':True})
    assert result.status_code==200,result.text
    saved=without_setup(db.list_entities(account['id'],'experience'))[0]['data'];assert saved['majors']==data['majors'] and saved['minors']==data['minors']
    assert doc['data']['resume_parse']['entries'][0]['data']['majors']==['Mathematics']


def test_transcript_course_punctuation_remains_whole_in_new_exports():
    snapshot=resume_data.entry_snapshot({'category':'education','title':'BS','relevant_courses':'Ethics, Policy and Law; Statistics'},'education',granular=True)
    assert 'Relevant class: Ethics, Policy and Law' in snapshot['bullets']


def test_project_upload_association_and_account_isolation(client,account,monkeypatch):
    async def no_ai(*args,**kwargs):raise AssertionError('No provider calls for file preparation')
    monkeypatch.setattr(ai,'structured',no_ai)
    project=db.save(account['id'],'experience',ExperienceItem(title='Project',category='project',confirmed=True).model_dump())
    result=client.post('/api/project-sources/upload',data={'experience_id':project['id']},files={'files':('README.md',b'Fictional project material','text/plain')})
    assert result.status_code==200,result.text
    assert result.json()['data']['experience_id']==project['id']
    other=client.post('/api/auth/register',json={'username':'other_student','password':'fictional-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
    rejected=client.post('/api/project-sources/upload',data={'experience_id':project['id']},files={'files':('README.md',b'Fictional','text/plain')})
    assert rejected.status_code==404
    assert not db.list_entities(other['id'],'project_source')
