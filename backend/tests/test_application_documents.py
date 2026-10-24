import io
import json
import hashlib
import pytest
from reportlab.pdfgen import canvas
from app import applications,db,config,application_documents
from test_app import wait
from test_upload_compare import provider,pdf_document

TEXT='Fictional Applicant\nData analysis internship\nBuilt SQL reports using Python and confirmed source data.'

def pdf(blank=False):
    stream=io.BytesIO();c=canvas.Canvas(stream)
    if not blank:
        for i,line in enumerate(TEXT.splitlines()):c.drawString(40,750-i*20,line)
    c.showPage();c.save();return stream.getvalue()

def application(client):
    job=client.post('/api/jobs',json={'title':'Example analyst','company':'Fictional Employer','description':'SQL and Python data analysis with reports.'}).json()
    response=client.post('/api/applications/start',json={'job_id':job['id']});assert response.status_code==200,response.text
    return job,response.json()

def upload(client,app,category='resume',raw=None,name='custom.pdf',token='upload-test-request'):
    return client.post('/api/applications/'+app['id']+'/documents',data={'category':category,'request_token':token},files={'file':(name,pdf() if raw is None else raw)})

def test_posting_only_ai_import_no_profile_comparison_or_resume(client,account,monkeypatch):
    monkeypatch.setattr(config,'OPENAI_KEY','fictional-key-never-sent');calls=provider(monkeypatch)
    response=client.post('/api/jobs/from-document',data={'request_token':'posting-only-upload','mode':'economy'},files={'file':('posting.pdf',pdf_document())})
    assert response.status_code==200,response.text
    result=wait(client,response.json()['task_id']);assert result['status']=='completed',result
    assert result['result']['kind']=='job'
    assert [c['text']['format']['name'] for c in calls]==['PostingExtractionOutput']
    assert not db.list_entities(account['id'],'analysis') and not db.list_entities(account['id'],'resume')
    retry=client.post('/api/jobs/from-document',data={'request_token':'posting-only-upload','mode':'economy'},files={'file':('posting.pdf',pdf_document())})
    # PDF metadata may vary, so status recovery is the reliable retry boundary.
    assert client.get('/api/jobs/from-document/status?request_token=posting-only-upload').json()['task_id']==response.json()['task_id']
    job=result['result'];a=client.post('/api/applications/start',json={'job_id':job['id']}).json()
    assert client.post('/api/applications/start',json={'job_id':job['id']}).json()['id']==a['id']
    assert a['data']['resume_ids']==[] and a['data']['status']=='preparing'

def test_upload_original_review_cover_and_background_selection(client,account):
    job,app=application(client);raw=pdf();response=upload(client,app,raw=raw);assert response.status_code==200,response.text
    value=response.json();resume=value['resume'];doc=value['document'];app=value['application']
    assert resume['data']['origin']=='uploaded' and app['data']['workflow']['resume_id']==resume['id']
    assert app['data']['submitted_resume_id']=='' and app['data']['status']=='preparing'
    assert client.get('/api/resumes/'+resume['id']+'/export/original').content==raw
    path='/api/applications/'+app['id']+'/documents/'+doc['id']
    assert client.get(path+'/download').content==raw
    assert upload(client,app,raw=raw).json()['resume']['id']==resume['id']
    assert len(db.list_entities(account['id'],'document'))==1
    assert client.post('/api/cover-letters/workspace',json={'job_id':job['id'],'resume_id':resume['id']}).status_code==409
    text=client.get(path+'/text').json();assert 'SQL reports' in text['text']
    reviewed=client.put(path+'/review',json={'expected_updated_at':text['resume_updated_at'],'text':text['text']});assert reviewed.status_code==200,reviewed.text
    assert client.get('/api/resumes/'+resume['id']+'/export/pdf').content==raw
    cover=client.post('/api/cover-letters/workspace',json={'job_id':job['id'],'resume_id':resume['id']});assert cover.status_code==200,cover.text
    assert any('SQL reports' in source['text'] for source in cover.json()['sources'])
    generated=db.save(account['id'],'resume',{'job_id':job['id'],'posting_snapshot':job['data'],'title':'Generated later'})
    applications.attach_resume(account['id'],generated)
    after=db.get(account['id'],app['id'],'application')['data']
    assert after['workflow']['resume_id']==resume['id'] and generated['id'] in after['resume_ids']
    assert client.delete(path).status_code==409
    assert client.delete('/api/records/'+doc['id']).status_code==409
    assert client.put('/api/documents/'+doc['id']+'/review',json={'text':'Profile contamination attempt'}).status_code==400
    assert client.post('/api/documents/'+doc['id']+'/parse').status_code==400
    assert not db.list_entities(account['id'],'experience')

def test_scanned_pdf_supporting_files_and_removal(client,account):
    _,app=application(client);value=upload(client,app,raw=pdf(True)).json();doc=value['document'];app=value['application']
    path='/api/applications/'+app['id']+'/documents/'+doc['id']
    assert client.get(path+'/text').json()['error']
    text=client.get(path+'/text').json()
    assert client.put(path+'/review',json={'text':TEXT,'expected_updated_at':text['resume_updated_at']}).status_code==200
    # A reviewed resume can still be removed before anything references its source.
    assert client.delete(path).status_code==200
    assert not db.list_entities(account['id'],'document') and not db.list_entities(account['id'],'resume')
    email_raw=pdf(True);value=upload(client,app,'email',raw=email_raw,token='email-upload-test').json();doc=value['document'];path='/api/applications/'+app['id']+'/documents/'+doc['id']
    assert client.get(path+'/text').status_code==400
    assert client.put(path,json={'display_name':'Interview invitation'}).status_code==200
    assert client.get(path+'/download').content==email_raw
    assert client.delete('/api/applications/'+app['id']).status_code==409
    assert client.delete(path).status_code==200
    assert not db.list_entities(account['id'],'usage_event')

def test_uploaded_submitted_version_backup_restores_original_bytes(client,account):
    _,app=application(client);raw=pdf();value=upload(client,app,raw=raw).json();app=value['application'];rid=value['resume']['id'];doc=value['document']
    data=app['data'];data.update(status='applied',applied_date='2026-10-24',submitted_resume_id=rid)
    response=client.put('/api/applications/'+app['id'],json=data);assert response.status_code==200,response.text
    assert client.delete('/api/applications/'+app['id']+'/documents/'+doc['id']).status_code==409
    backup=client.get('/api/account/export').json()
    response=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode())});assert response.status_code==200,response.text
    apps=db.list_entities(account['id'],'application');assert len(apps)==2
    restored=next(a for a in apps if a['id']!=app['id']);new_id=restored['data']['submitted_resume_id'];assert new_id!=rid
    assert client.get('/api/resumes/'+new_id+'/export/original').content==raw
    bad=json.loads(json.dumps(backup));r=next(r for r in bad['records'] if r['kind']=='resume');r['data']['document_id']='foreign-document'
    assert client.post('/api/account/import',files={'file':('bad.json',json.dumps(bad).encode())}).status_code==400

@pytest.mark.parametrize('name,raw',[('bad.pdf',b'not a pdf'),('bad.exe',b'not a file'),('big.txt',b'x'*(10*1024*1024+1)),('blank.txt',b'')])
def test_reject_invalid_upload(client,account,name,raw):
    _,app=application(client);r=upload(client,app,raw=raw,name=name);assert r.status_code in (400,413)
    assert not db.list_entities(account['id'],'document')

def test_account_and_application_boundaries(client,account):
    _,app=application(client);value=upload(client,app).json();doc=value['document']
    _,other=application(client)
    assert client.get('/api/applications/'+other['id']+'/documents/'+doc['id']+'/download').status_code==404
    from fastapi.testclient import TestClient
    from app.main import app as api
    from conftest import onboard_test_account
    with TestClient(api,base_url='http://localhost') as outsider:
        u=outsider.post('/api/auth/register',json={'username':'outsider','password':'fictional-test-password'}).json();onboard_test_account(u);outsider.headers['X-CSRF-Token']=u['csrf']
        assert outsider.get('/api/applications/'+app['id']+'/documents/'+doc['id']+'/download').status_code==404
    assert len(db.list_entities(account['id'],'document'))==1


def test_extension_approves_exact_uploaded_original_and_excludes_supporting_files(client,account):
    from test_application_agent import pair
    _,app=application(client);raw=pdf();value=upload(client,app,raw=raw).json();resume=value['resume'];app=value['application']
    note=upload(client,app,'email',raw=b'Private fictional email attachment.',name='email.txt',token='second-upload-token');assert note.status_code==200
    connection=pair(client)
    context=client.post('/api/application-agent/relay/context',json=connection).json()
    assert context['applications'][0]['cover_letter_ids']==[]
    payload={**connection,'application_id':app['id'],'allowed_origin':'https://employer.example','tab_id':12,'resume_id':resume['id'],'documents_approved':True,'document_versions':{resume['id']:resume['updated_at']}}
    response=client.post('/api/application-agent/runs',json=payload);assert response.status_code==200,response.text
    run=response.json()
    path='/api/application-agent/runs/'+run['id']+'/documents/'+resume['id']
    # This is an authenticated same-origin relay, still bound to tab and origin.
    response=client.get(path)
    assert response.status_code==200,response.text
    assert response.content==raw
    assert db.get(account['id'],app['id'],'application')['data']['status']=='preparing'


def test_stale_editor_cannot_drop_upload_or_resume_references(client,account):
    _,app=application(client);old=app['data'];uploaded=upload(client,app).json()
    assert client.put('/api/applications/'+app['id'],json=old).status_code==409
    assert client.delete('/api/records/'+app['id']).status_code==409
    assert len(db.list_entities(account['id'],'document'))==1


def test_docx_and_txt_originals_preserve_bytes(client,account,monkeypatch):
    from docx import Document
    from app import documents
    monkeypatch.setattr(documents,'docx_pages',lambda raw:1)
    _,app=application(client);stream=io.BytesIO();d=Document();d.add_paragraph(TEXT);d.save(stream)
    for index,(name,raw) in enumerate([('custom.docx',stream.getvalue()),('custom.txt',TEXT.encode())]):
        value=upload(client,app,raw=raw,name=name,token='format-token-'+str(index)).json();rid=value['resume']['id']
        assert client.get('/api/resumes/'+rid+'/export/original').content==raw
        assert client.get('/api/resumes/'+rid+'/export/pdf').status_code==400


def test_cover_draft_uses_reviewed_uploaded_source_only(client,account,monkeypatch):
    import asyncio
    from app import ai,cover_letters
    from app.models import CoverGenerate,CoverContent
    _,app=application(client);value=upload(client,app).json();resume=value['resume'];doc=value['document'];path='/api/applications/'+app['id']+'/documents/'+doc['id']
    extracted=client.get(path+'/text').json();assert client.put(path+'/review',json={'text':extracted['text'],'expected_updated_at':extracted['resume_updated_at']}).status_code==200
    assert upload(client,app,'email',raw=b'PRIVATE EMAIL NOT EVIDENCE',name='email.txt',token='email-context-token').status_code==200
    state=client.post('/api/cover-letters/workspace',json={'job_id':app['data']['job_id'],'resume_id':resume['id']}).json();calls=[]
    async def fake(schema,payload,*args,**kwargs):
        calls.append(payload)
        if schema.__name__=='DraftAudit':return {'approved':True,'issues':[]},{'model':'fixture','usage':{}}
        source=next(r for r in payload['saved_resume_sources'] if 'SQL reports' in r['text'])
        return {'paragraphs':[{'text':'I am interested in the Example analyst position.','evidence':[{'source_id':'posting','quote':'Example analyst'}]},{'text':source['text'],'evidence':[{'source_id':source['id'],'quote':source['text']}]}],'summary':'Used the reviewed original.'},{'model':'fixture','usage':{}}
    monkeypatch.setattr(ai,'structured',fake);monkeypatch.setattr(config,'OPENAI_KEY','fictional-not-sent')
    result=asyncio.run(cover_letters.generate(account['id'],state['id'],CoverGenerate(expected_version=state['data']['version'],content=CoverContent.model_validate(state['data']['content']))))
    assert result['current']['data']['layout']['pages']==1
    assert 'PRIVATE EMAIL NOT EVIDENCE' not in json.dumps(calls)
    assert len(calls)==2
