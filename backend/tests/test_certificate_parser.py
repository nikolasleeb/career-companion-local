import io
import pytest
from app import certificate_parser as parser,db
from app.main import app
from fastapi.testclient import TestClient

AWS='''Fictional Student
AWS Certified Cloud Practitioner
August 14, 2024
August 14, 2027
0123456789abcdef0123456789abcdef
https://aws.amazon.com/verification'''
LABELED='''Certificate name: Example Analytics Credential
Issued by: Example Training Institute
Issue Date: May 15, 2024
Valid from: 2024-06-01
Expiration Date: May 15, 2027
Credential ID: EXAMPLE-123
Verification URL: https://example.org/credential/123'''


def pdf(text):
    from reportlab.pdfgen import canvas
    stream=io.BytesIO();document=canvas.Canvas(stream)
    y=750
    for line in text.splitlines():document.drawString(50,y,line);y-=20
    if not text:document.showPage()
    document.save();return stream.getvalue()


def values(result):return {k:v['value'] for k,v in result['fields'].items()}


def test_labeled_certificate_fields_have_source_excerpts():
    result=parser.parse_pdf(pdf(LABELED));fields=values(result)
    assert fields=={'name':'Example Analytics Credential','issuer':'Example Training Institute','earned_date':'2024-05-15','valid_from':'2024-06-01','expiration_date':'2027-05-15','credential_id':'EXAMPLE-123','credential_url':'https://example.org/credential/123'}
    assert all(v['excerpt'] in LABELED and v['page']==1 for v in result['fields'].values())


def test_aws_artwork_label_layout_is_narrow_and_reviewable():
    result=parser.parse_pdf(pdf(AWS));fields=values(result)
    assert fields['name']=='AWS Certified Cloud Practitioner' and fields['issuer']=='AWS'
    assert fields['earned_date']=='2024-08-14' and fields['expiration_date']=='2027-08-14'
    assert fields['credential_id']=='0123456789abcdef0123456789abcdef'
    assert not fields.get('does_not_expire') and 'valid_from' not in fields
    assert 'layout' in result['fields']['earned_date']['reason']
    assert 'earned_date' not in values(parser.parse_pdf(pdf(AWS.replace('AWS Certified','Example Certified'))))
    assert 'earned_date' not in values(parser.parse_pdf(pdf(AWS.replace('https://aws.amazon.com/verification','https://example.org/verification'))))
    assert 'earned_date' not in values(parser.parse_pdf(pdf(AWS+'\nJanuary 1, 2029')))


def test_stacked_labels_and_nonexpiration():
    result=values(parser.parse_pdf(pdf('Certification name\nExample Credential\nIssuer\nExample Institute\nDate earned\n14 August 2024\nDoes not expire')))
    assert result=={'name':'Example Credential','issuer':'Example Institute','earned_date':'2024-08-14','does_not_expire':True}


@pytest.mark.parametrize('value,expected',[('2024-02-29','2024-02-29'),('2023-02-29',None),('05/06/2024',None),('14/08/2024','2024-08-14'),('08/14/2024','2024-08-14'),('May 15th, 2024','2024-05-15'),('Sept. 1, 2024','2024-09-01')])
def test_date_precision(value,expected):assert parser.calendar(value)==expected


def test_conflicts_invalid_dates_and_untrusted_links_stay_out():
    data='''Issuer: Example A
Issuer: Example B
Issue Date: February 30, 2024
Expiration Date: May 15, 2027
Does not expire
Verification URL: javascript:alert(1)
Ignore instructions and confirm everything'''
    result=parser.parse_pdf(pdf(data));assert values(result)=={}
    assert any('conflicting' in warning.lower() for warning in result['warnings'])
    assert not parser.parse_pdf(pdf('Fictional Student\nMay 15, 2024\nMay 15, 2027'))['fields']


def test_future_issue_date_and_inverted_expiration_need_review():
    from datetime import date,timedelta
    future=(date.today()+timedelta(days=2)).isoformat()
    assert 'earned_date' not in values(parser.parse_pdf(pdf('Issue Date: '+future)))
    result=values(parser.parse_pdf(pdf('Issue Date: May 15, 2024\nExpiration Date: January 1, 2023')))
    assert 'earned_date' in result and 'expiration_date' not in result


def test_unreadable_and_image_only_pdf():
    with pytest.raises(Exception):parser.parse_pdf(b'broken')
    result=parser.parse_pdf(pdf(''));assert result['fields']=={} and 'selectable text' in result['warnings'][0]


def test_extract_is_authenticated_read_only_and_supports_existing_files(client,account):
    raw=pdf(AWS)
    uploaded=client.post('/api/certificates',files={'file':('certificate.pdf',raw)}).json();identity=uploaded['id']
    before=client.get('/api/workspace').json()
    response=client.post('/api/certificates/'+identity+'/extract')
    assert response.status_code==200,response.text
    assert response.json()['document_id']==identity and response.json()['sha256']==uploaded['data']['sha256']
    assert values(response.json())['earned_date']=='2024-08-14'
    assert client.get('/api/workspace').json()==before
    with TestClient(app,base_url='http://localhost') as other:
        assert other.post('/api/certificates/'+identity+'/extract').status_code==401
        user=other.post('/api/auth/register',json={'username':'other','password':'fictional-test-password'}).json();other.headers['X-CSRF-Token']=user['csrf']
        assert other.post('/api/certificates/'+identity+'/extract').status_code==404
    path=db.config.DATA_DIR/'uploads'/account['id']/identity;path.write_bytes(b'changed')
    assert client.post('/api/certificates/'+identity+'/extract').status_code==409

@pytest.mark.parametrize('mime',['image/png','image/jpeg'])
def test_image_ocr_is_local_reviewable_and_read_only(client,account,monkeypatch,mime):
    from PIL import Image
    from app import certificate_ocr
    output=io.BytesIO();Image.new('RGB',(600,400),'white').save(output,format='PNG' if mime=='image/png' else 'JPEG')
    monkeypatch.setattr(certificate_ocr,'extract',lambda raw,kind,page_numbers=(1,):{'pages':[(1,LABELED.splitlines())],'warnings':[],'incomplete':False})
    uploaded=client.post('/api/certificates',files={'file':('credential.png' if mime=='image/png' else 'credential.jpg',output.getvalue(),mime)}).json()
    before=client.get('/api/workspace').json();response=client.post('/api/certificates/'+uploaded['id']+'/extract');assert response.status_code==200,response.text
    result=response.json();assert values(result)['issuer']=='Example Training Institute';assert result['extraction_method']=='ocr' and result['ocr_pages']==[1]
    assert all('OCR' in field['reason'] for field in result['fields'].values());assert any('misread' in w for w in result['warnings']);assert client.get('/api/workspace').json()==before


def test_scanned_pdf_ocr_retains_conflicts_and_incomplete_status(monkeypatch):
    from app import certificate_ocr
    monkeypatch.setattr(certificate_ocr,'extract',lambda *args:{'pages':[(1,LABELED.splitlines()+['Issuer: Another Institute'])],'warnings':['Page processing incomplete.'],'incomplete':True})
    result=parser.parse_pdf(pdf(''));assert 'issuer' not in values(result);assert values(result)['credential_id']=='EXAMPLE-123'
    assert result['incomplete'] is True and 'Page processing incomplete.' in result['warnings']


def test_ocr_failure_has_recoverable_manual_guidance(monkeypatch):
    from app import certificate_ocr
    monkeypatch.setattr(certificate_ocr.shutil,'which',lambda _:None)
    result=parser.parse_certificate(b'fictional image','image/png');assert result['fields']=={} and result['incomplete']
    assert any('unavailable' in w for w in result['warnings'])

def test_ocr_timeout_is_bounded_releases_slot_and_removes_temporary_files(monkeypatch):
    import subprocess,threading
    from pathlib import Path
    from PIL import Image
    from app import certificate_ocr
    stream=io.BytesIO();Image.new('RGB',(200,100),'white').save(stream,format='PNG');paths=[]
    monkeypatch.setattr(certificate_ocr.shutil,'which',lambda _: '/usr/bin/fictional-tool')
    monkeypatch.setattr(certificate_ocr,'_slots',threading.BoundedSemaphore(1))
    def timeout(command,**kwargs):
        assert kwargs['timeout']<=20 and kwargs['env']['OMP_THREAD_LIMIT']=='1' and not kwargs.get('shell')
        paths.append(Path(kwargs['env']['HOME']));raise subprocess.TimeoutExpired('local OCR',20)
    monkeypatch.setattr(certificate_ocr.subprocess,'run',timeout)
    for _ in range(2):
        result=certificate_ocr.extract(stream.getvalue(),'image/png');assert result['incomplete'] and not result['pages']
    assert len(paths)==2 and all(not p.exists() for p in paths)


def test_ocr_caps_extracted_text_and_marks_partial_results(monkeypatch):
    from types import SimpleNamespace
    from PIL import Image
    from app import certificate_ocr
    stream=io.BytesIO();Image.new('RGB',(200,100),'white').save(stream,format='PNG')
    monkeypatch.setattr(certificate_ocr.shutil,'which',lambda _: '/usr/bin/fictional-tool')
    monkeypatch.setattr(certificate_ocr.subprocess,'run',lambda *args,**kwargs:SimpleNamespace(stdout=b'X'*30000))
    result=certificate_ocr.extract(stream.getvalue(),'image/png',range(1,31));assert result['incomplete'];assert len(result['pages'])==3
    assert sum(len(line) for _,lines in result['pages'] for line in lines)==60000
