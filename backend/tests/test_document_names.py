import copy
from urllib.parse import unquote
import pytest
from app import ai,applications,db,documents,resume_data

AMAZON={'company':'Amazon','title':'2027 Data Science Internship - United States, PhD or Masters Student, Amazon Uni Tlt Acquisition-VAR'}
NAME='Nikolas Lee-Bishop'
EXPECTED='Nikolas-Lee-Bishop-Amazon-2027-Data-Science-Internship-Resume'


@pytest.mark.parametrize('title,expected',[
    (AMAZON['title'],'2027-Data-Science-Internship'),
    ('Software Engineer - Machine Learning','Software-Engineer-Machine-Learning'),
    ('Analyst | Risk & Compliance','Analyst-Risk-&-Compliance'),
    ('Research Engineer - Remote Sensing','Research-Engineer-Remote-Sensing'),
    ('Data Engineer — Remote','Data-Engineer'),
    ('Data Analyst | Job ID 12345','Data-Analyst'),
    ('2027 Internship — Masters Student','2027-Internship'),
    ('Amazon - Data Engineer','Data-Engineer'),
    ('2027 Internship---United States, PhD or Masters Student','2027-Internship'),
])
def test_core_role_cleanup_preserves_specializations(title,expected):
    assert resume_data.resume_title({'company':'Amazon','title':title})=='Amazon-'+expected+'-Resume'


def test_display_and_every_export_share_safe_short_stem_without_mutating_snapshot():
    snapshot={'name':NAME,'posting_snapshot':AMAZON,'title':'Old extremely verbose title','artifacts':{'pdf':'untouched'}}
    record={'kind':'resume','id':'immutable-version','data':snapshot}
    old=copy.deepcopy(record)
    assert applications.public(record)['data']['title']==EXPECTED
    for fmt in ('pdf','docx','txt'):
        assert resume_data.resume_filename(snapshot,fmt)==EXPECTED+'.'+fmt
    assert record==old


@pytest.mark.parametrize('posting,fallback,name',[
    ({},'Resume',''),({},'Existing custom label','Fictional Applicant'),
    ({'title':'Analyst'},'Resume',''),({'company':'Example'},'Resume',''),
    ({'company':'Équipe / 株式会社','title':'研究員 — Machine Learning'},'Resume','Zoë 李'),
    ({'company':'A<>:"/\\|?*','title':'Research---Engineer'},'Resume','\x00Fictional\x7f Applicant'),
    ({'company':'Long Company','title':'Specialist '+'非常に長い専門分野 '*50},'Resume','Example Applicant'),
    ({'company':'X'*250,'title':'Y'*250},'Resume','Z'*250),
])
def test_missing_metadata_unicode_and_long_names(posting,fallback,name):
    title=resume_data.resume_title(posting,fallback,name)
    assert title.endswith('Resume') and len(title.encode('utf-8'))<=180
    assert '---' not in title and '--' not in title
    assert not any(ch in title for ch in '<>:"/\\|?*\x00\x7f')
    assert resume_data.resume_title({},title,name)==title


def test_existing_version_export_names_change_without_rebuilding_artifacts(client,account,monkeypatch):
    async def forbidden(*a,**kw):raise AssertionError('Filename cleanup must not call a model')
    monkeypatch.setattr(ai,'structured',forbidden)
    raw=b'previously generated original artifact'
    monkeypatch.setattr(documents,'export_resume',lambda data,fmt:(raw,'application/octet-stream'))
    record=db.save(account['id'],'resume',{'name':NAME,'posting_snapshot':AMAZON,'title':'Old title','sections':[]})
    before=copy.deepcopy(db.get(account['id'],record['id'],'resume'))
    for fmt in ('pdf','docx','txt'):
        result=client.get('/api/resumes/'+record['id']+'/export/'+fmt)
        assert result.status_code==200 and result.content==raw
        assert EXPECTED+'.'+fmt in unquote(result.headers['content-disposition'])
    assert db.get(account['id'],record['id'],'resume')==before


def test_uploaded_title_and_original_filename_are_not_normalized(client,account):
    from test_application_documents import application,upload
    _,app=application(client)
    filename='Custom_Resume_Original_Long_Name.txt'
    raw=b'Fictional Applicant\nPreviously submitted custom resume. SQL and Python experience.'
    result=upload(client,app,raw=raw,name=filename).json()
    resume=result['resume']
    assert applications.public(resume)['data']['title']==filename
    response=client.get('/api/resumes/'+resume['id']+'/export/original')
    assert response.status_code==200 and response.content==raw
    assert filename in unquote(response.headers['content-disposition'])
