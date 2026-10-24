import io
from reportlab.pdfgen import canvas
from app import documents, db


def job_pdf():
    stream=io.BytesIO();pdf=canvas.Canvas(stream)
    for i,line in enumerate(['Junior Data Analyst','Example Company','Requirements: SQL and Python.','Responsibilities: Build reports and check data quality.']):
        pdf.drawString(40,750-i*20,line)
    pdf.save();return stream.getvalue()


def test_job_pdf_parses_for_review_without_saving(client,account):
    before=client.get('/api/workspace').json()
    response=client.post('/api/jobs/import-document',files={'file':('Job Application for Junior Data Analyst at Example Company.pdf',job_pdf(),'application/pdf')})
    assert response.status_code==200,response.text
    result=response.json()
    assert result['title']=='Junior Data Analyst' and result['company']=='Example Company'
    assert 'SQL and Python' in result['description'] and result['pages']==1
    assert client.get('/api/workspace').json()==before
    assert not list((db.config.DATA_DIR/'uploads').glob('**/*'))
    saved=client.post('/api/jobs',json={k:result[k] for k in ('title','company','description','url')})
    assert saved.status_code==200
    assert saved.json()['data']['description']==result['description']


def test_job_import_limits_are_pdf_specific(client,account,monkeypatch):
    calls=[]
    def extract(name,raw,**kwargs):
        calls.append(kwargs['max_upload']);return {'text':'Requirements: SQL and Python.','pages':1}
    monkeypatch.setattr(documents,'extract',extract)
    assert client.post('/api/jobs/import-document',files={'file':('job.pdf',b'fixture')}).status_code==200
    assert client.post('/api/jobs/import-document',files={'file':('job.txt',b'fixture')}).status_code==200
    assert calls==[50*1024*1024,10*1024*1024]
    assert client.post('/api/jobs/import-document',headers={'Content-Length':str(52*1024*1024)}).status_code==413


def test_job_document_errors_and_auth(client,account):
    assert client.post('/api/jobs/import-document',files={'file':('job.exe',b'unsupported')}).status_code==400
    assert client.post('/api/jobs/import-document',files={'file':('job.pdf',b'broken pdf')}).status_code==400
    client.post('/api/auth/logout')
    assert client.post('/api/jobs/import-document',files={'file':('job.pdf',job_pdf())}).status_code==401


def test_careers_page_filename_splits_role_and_company_and_preserves_hyphen(client,account,monkeypatch):
    text='10/8/26, 2:14 PMJunior Machine Learning Engineering - Rolls-Royce Careers\nRolls-Royce\nRequirements\nPython experience.'
    monkeypatch.setattr(documents,'extract',lambda *a,**k:{'text':text,'pages':8})
    before=client.get('/api/workspace').json()
    result=client.post('/api/jobs/import-document',files={'file':('Junior Machine Learning Engineering - Rolls-Royce Careers.pdf',b'fixture')}).json()
    assert result['title']=='Junior Machine Learning Engineering' and result['company']=='Rolls-Royce'
    assert result['overview']['company']=='Rolls-Royce' and result['description']==text
    assert result['overview']['identity_sources']['company']['kind']=='filename hint'
    assert client.get('/api/workspace').json()==before


def test_generic_filename_uses_printed_careers_title_and_labeled_employer(client,account,monkeypatch):
    text='10/8/26, 2:14 PMData Analyst | Example Labs Careers\nCompany: Example Labs\nRequirements\nSQL.'
    monkeypatch.setattr(documents,'extract',lambda *a,**k:{'text':text,'pages':1})
    result=client.post('/api/jobs/import-document',files={'file':('job.pdf',b'fixture')}).json()
    assert result['title']=='Data Analyst' and result['company']=='Example Labs'
    for origin in result['overview']['identity_sources'].values():assert origin['quote'] in text


def test_printed_careers_pdf_import_separates_unmarked_list_without_saving(client,account):
    from test_job_overview import UNMARKED_POSTING
    stream=io.BytesIO();pdf=canvas.Canvas(stream)
    # Deliberately omit bullet glyphs, matching browser PDFs that draw bullets
    # as vector shapes instead of selectable text.
    for page in UNMARKED_POSTING.split('\n\n'):
        for i,line in enumerate(page.splitlines()):pdf.drawString(25,800-i*22,line.replace('ﬁ','fi'))
        pdf.showPage()
    pdf.save()
    before=client.get('/api/workspace').json()
    response=client.post('/api/jobs/import-document',files={'file':('Integration Solutions Engineer - Careers.pdf',stream.getvalue(),'application/pdf')})
    assert response.status_code==200,response.text
    result=response.json()
    assert (result['title'],result['company'])==('Integration Solutions Engineer','Epic')
    assert result['overview']['company']=='Epic'
    assert len(result['overview']['sections']['required'])==3
    assert len(result['overview']['sections']['eligibility'])==2
    assert result['overview']['facts']['location']['value']=='Madison, WI'
    assert 'careers@epic.com' in result['description']
    assert client.get('/api/workspace').json()==before
    assert not list((db.config.DATA_DIR/'uploads').glob('**/*'))
