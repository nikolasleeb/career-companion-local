import base64
import io
from datetime import date,timedelta
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from app import db,ai,documents,resume_data,resume_parser
from app.main import app
from app.models import ExperienceItem,CertificationItem


def certificate_pdf():
    from reportlab.pdfgen import canvas
    stream=io.BytesIO();pdf=canvas.Canvas(stream);pdf.drawString(50,750,'Fictional training certificate');pdf.save();return stream.getvalue()


def upload(client):
    response=client.post('/api/certificates',files={'file':('fictional.pdf',certificate_pdf(),'application/pdf')})
    assert response.status_code==200,response.text
    return response.json()


def credential(document=''):
    return {'category':'skills','title':'Certifications','confirmed':True,'certification_items':[{'name':'Fictional Cloud Credential','issuer':'Example Training','earned_date':'2024-05-15','valid_from':'2024-06-01','expiration_date':'2027-05-15','credential_id':'EXAMPLE-123','credential_url':'https://example.org/credential','document_id':document}]}


def test_credential_dates_and_links():
    CertificationItem(name='Example',expiration_date='2020-01-01') # expired credentials can be retained
    for values in [dict(earned_date=(date.today()+timedelta(days=1)).isoformat()),dict(earned_date='2023-02-29'),dict(earned_date='2024'),dict(does_not_expire=True,expiration_date='2027-01-01'),dict(earned_date='2024-01-01',expiration_date='2023-01-01'),dict(valid_from='2025-01-01',expiration_date='2024-01-01'),dict(credential_url='javascript:alert(1)'),dict(level='advanced')]:
        with pytest.raises(ValidationError):CertificationItem(name='Example',**values)
    CertificationItem(name='Example',does_not_expire=True)
    for payload in [dict(category='education',certification_items=[{'name':'Example'}]),dict(category='skills',certification_items=[{'name':'Example'}],skill_items=[{'name':'Example','level':'advanced'}])]:
        with pytest.raises(ValidationError):ExperienceItem(title='Example',**payload)


def test_upload_requires_authentication(client):
    assert client.post('/api/certificates',files={'file':('example.pdf',certificate_pdf())}).status_code==401


def test_store_download_and_duplicate_certificate(client,account):
    document=upload(client)
    assert document['data']['purpose']=='certificate' and not document['data']['reviewed']
    assert document['data']['text']==''
    assert client.get('/api/certificates/'+document['id']+'/download').content==(db.config.DATA_DIR/'uploads'/account['id']/document['id']).read_bytes()
    # The fixture PDF carries a timestamp; reuse exact saved bytes for duplicate check.
    raw=(db.config.DATA_DIR/'uploads'/account['id']/document['id']).read_bytes()
    duplicate=client.post('/api/certificates',files={'file':('copy.pdf',raw)})
    assert duplicate.json()['id']==document['id']
    assert not db.list_entities(account['id'],'experience')


@pytest.mark.parametrize('name,raw',[('certificate.exe',b'hello'),('certificate.pdf',b'not pdf'),('certificate.png',b'%PDF-1.0'),('certificate.svg',b'<svg onload="alert(1)"/>'),('empty.jpg',b''),('big.pdf',b'x'*(10*1024*1024+1))])
def test_reject_unsupported_malformed_or_large_files(client,account,name,raw):
    assert client.post('/api/certificates',files={'file':(name,raw)}).status_code in (400,413)
    assert not db.list_entities(account['id'],'document')


def test_certificate_image_upload(client,account):
    from PIL import Image
    stream=io.BytesIO();Image.new('RGB',(50,30),'white').save(stream,'PNG')
    assert client.post('/api/certificates',files={'file':('certificate.png',stream.getvalue())}).status_code==200


def test_linked_uploads_owned_and_cannot_be_deleted(client,account):
    document=upload(client)
    response=client.post('/api/experience',json=credential(document['id']))
    assert response.status_code==200,response.text
    assert client.delete('/api/records/'+document['id']).status_code==409
    assert client.post('/api/documents/'+document['id']+'/parse').status_code==400
    with TestClient(app,base_url='http://localhost') as other:
        user=other.post('/api/auth/register',json={'username':'other','password':'fictional-test-password'}).json();other.headers['X-CSRF-Token']=user['csrf']
        assert other.get('/api/certificates/'+document['id']+'/download').status_code==404
        assert other.post('/api/experience',json=credential(document['id'])).status_code==400
    entry=response.json()
    assert client.put('/api/experience/'+entry['id'],json=credential()).status_code==200
    assert client.delete('/api/records/'+document['id']).status_code==200


def test_backup_remaps_attachments_and_rejects_missing_references(client,account):
    document=upload(client);client.post('/api/experience',json=credential(document['id']))
    backup=client.get('/api/account/export').json()
    assert document['id'] in backup['files']
    import json
    response=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup))})
    assert response.status_code==200,response.text
    entries=db.list_entities(account['id'],'experience')
    attachments={e['data']['certification_items'][0]['document_id'] for e in entries}
    assert len(attachments)==2 and document['id'] in attachments
    assert all(client.get('/api/certificates/'+identity+'/download').status_code==200 for identity in attachments)
    backup['files'].pop(document['id'])
    count=len(db.list_entities(account['id'],'experience'))
    assert client.post('/api/account/import',files={'file':('bad.json',json.dumps(backup))}).status_code==400
    assert len(db.list_entities(account['id'],'experience'))==count


def test_approved_import_and_exports_do_not_use_proficiency(client,account):
    doc=client.post('/api/documents?purpose=resume',files={'file':('resume.txt','CERTIFICATIONS\nFictional Cloud Credential; Example Analytics Credential')}).json()
    parsed=doc['data']['resume_parse'];entry=parsed['entries'][0]
    assert len(entry['data']['certification_items'])==2
    assert not entry['data']['confirmed']
    entry['data']=credential(upload(client)['id'])
    response=client.post('/api/documents/'+doc['id']+'/import-resume',json={'text_hash':parsed['text_hash'],'entries':[{'id':entry['id'],'data':entry['data']}],'profile_updates':{},'reviewed':True})
    assert response.status_code==200,response.text
    record=db.list_entities(account['id'],'experience')[0]
    snapshot=resume_data.entry_snapshot(record['data'],record['id'])
    text=documents.resume_plain({'name':'Fictional Student','sections':[{'title':'Skills','entries':[snapshot]}]})
    assert 'Earned 2024-05-15' in text and 'Expires 2027-05-15' in text and 'Example Training' in text
    assert 'EXAMPLE-123' in text and record['data']['certification_items'][0]['document_id'] not in text
    assert all(item['field']=='certification' for item in snapshot['content_items'])
    assert 'self-rated' not in text and 'unknown' not in text
    assert 'Example Training' in ai.experience_text(record['data'])
    assert record['data']['certification_items'][0]['document_id'] not in ai.experience_text(record['data'])


def test_legacy_certificate_groups_do_not_export_proficiency():
    data={'category':'skills','title':'Certifications','skill_items':[{'name':'Example Certificate','level':'advanced'}]}
    snapshot=resume_data.entry_snapshot(data,'legacy')
    assert snapshot['bullets']==['Example Certificate']
    assert 'advanced' not in ai.experience_text(data)
    assert resume_data.entry_snapshot({'category':'skills','title':'Certifications','description':'Example Certificate'},'old')['bullets']==['Example Certificate']
