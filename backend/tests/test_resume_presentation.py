import copy
import io
import pytest
from docx import Document
from pypdf import PdfReader
from app import ai,documents,resume_data,resume_presentation,db
from app.main import build_resume
from app.models import ResumeRequest,WorkingRender
from test_guided_resume import env,build,request
from app import resume_conversation as guided


def fixture_data():
    groups=[
        {'category':'skills','title':'Programming','skill_items':[{'name':'Python (pandas, NumPy)','level':'intermediate'},{'name':'SQL','level':'beginner'},{'name':'Git','level':'unknown'}]},
        {'category':'skills','title':'Certifications','organization':'Issuer group metadata','certification_items':[{'name':'Example Cloud Practitioner','issuer':'Example Training','earned_date':'2025-01-29','valid_from':'2025-02-01','expiration_date':'2028-01-29','credential_id':'PRIVATE-CREDENTIAL-ID','credential_url':'https://example.org/verify'},{'name':'Example Analytics Certificate','does_not_expire':True},{'name':'Example Security Credential'}]},
    ]
    return {'name':'Fictional Student','schema_version':4,'compact_skills':True,'sections':[{'title':'Skills','entries':[resume_data.entry_snapshot(v,str(n),granular=True) for n,v in enumerate(groups)]}]}


def test_compact_display_removes_ratings_and_credential_metadata_without_changing_sources():
    data=fixture_data();old=copy.deepcopy(data);display=resume_presentation.display(data)
    skills,certs=display['sections'][0]['entries']
    assert skills['bullets']==['Python (pandas, NumPy)','SQL','Git']
    assert certs['bullets']==['Example Cloud Practitioner · Expires 2028-01-29','Example Analytics Certificate · No expiration','Example Security Credential']
    assert certs['organization']==''
    assert data==old and 'intermediate, self-rated' in data['sections'][0]['entries'][0]['bullets'][0]
    assert display['sections'][0]['entries'][1]['content_items']==old['sections'][0]['entries'][1]['content_items']
    assert resume_presentation.display(display)==display


@pytest.mark.parametrize('format',['txt','docx','pdf'])
def test_all_resume_exports_use_names_and_expiry_only(format):
    data=fixture_data();raw,mime=documents.export_resume(data,format)
    if format=='txt':text=raw.decode()
    elif format=='docx':text='\n'.join(p.text for p in Document(io.BytesIO(raw)).paragraphs)
    else:text='\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(raw)).pages)
    for expected in ['Python (pandas, NumPy)','SQL','Example Cloud Practitioner','Expires 2028-01-29','No expiration','Example Security Credential']:assert expected in text
    for removed in ['self-rated','intermediate','beginner','Earned','Valid from','Example Training','Issuer group metadata','PRIVATE-CREDENTIAL-ID','https://example.org/verify']:assert removed not in text


def test_legacy_snapshots_and_explicit_custom_wording_remain_unchanged():
    data=fixture_data();data.pop('compact_skills');text=documents.resume_plain(data)
    assert 'self-rated' in text and 'PRIVATE-CREDENTIAL-ID' in text
    new=fixture_data();entry=new['sections'][0]['entries'][1]
    entry['bullets'][0]='My explicitly edited credential wording'
    assert resume_presentation.display(new)['sections'][0]['entries'][1]['bullets'][0]=='My explicitly edited credential wording'
    old={'category':'skills','title':'Certifications','tools':'Legacy Certificate'}
    new['sections'][0]['entries']=[resume_data.entry_snapshot(old,'legacy')]
    assert resume_presentation.display(new)['sections'][0]['entries'][0]['bullets']==['Legacy Certificate']


def test_non_skill_claims_and_skill_context_are_not_stripped():
    data=fixture_data();entry=data['sections'][0]['entries'][0]
    entry['bullets'].append('The study includes intermediate and advanced course work.')
    entry['content_items'].append({'field':'skill_context','text':entry['bullets'][-1],'original':entry['bullets'][-1],'item_id':'context'})
    entry['category']='project'
    assert resume_presentation.display(data)['sections'][0]['entries'][0]['bullets']==entry['bullets']
    entry['category']='skills'
    assert resume_presentation.display(data)['sections'][0]['entries'][0]['bullets'][-1]==entry['bullets'][-1]


def test_future_builds_default_to_compact_while_profile_evidence_and_backup_stay_full(env,client):
    user,job,rows,session,calls=env
    body={'category':'skills','title':'Certifications','confirmed':True,'certification_items':[{'name':'Example Cloud Practitioner','issuer':'Example Training','expiration_date':'2028-01-29','credential_id':'PRIVATE-CREDENTIAL-ID'}]}
    cert=client.post('/api/experience',json=body).json()
    snapshot=build_resume(user,ResumeRequest(job_id=job['id'],experience_ids=[cert['id']]))
    assert snapshot['compact_skills']
    assert 'PRIVATE-CREDENTIAL-ID' not in documents.resume_plain(snapshot)
    assert 'PRIVATE-CREDENTIAL-ID' in ai.experience_text(cert['data'])
    assert 'PRIVATE-CREDENTIAL-ID' in client.get('/api/account/export').text
    assert db.get(user,cert['id'],'experience')['data']==cert['data']


def test_existing_draft_can_update_presentation_locally_without_altering_old_revision(env):
    user,job,rows,session,calls=env;state=build(env);head=state['current']['id'];old=db.get(user,head,'resume_revision')['data']
    # Simulate an older saved draft. Re-rendering creates a new revision only.
    old['snapshot'].pop('compact_skills',None);old['source_snapshot'].pop('compact_skills',None)
    db.save(user,'resume_revision',old,head)
    state=guided.state(user,state['id']);body=request(state);body.compact_skills=True
    changed=guided.render(user,state['id'],WorkingRender(expected_version=state['data']['version'],request_token='clean-skills',resume=body))
    assert changed['current']['id']!=head and changed['current']['data']['snapshot']['compact_skills']
    assert len(calls)==2 # Only the original mocked build and audit.
    assert db.get(user,head,'resume_revision')['data']==old
    assert changed['current']['data']['snapshot']['experience_ids']==state['current']['data']['snapshot']['experience_ids']
