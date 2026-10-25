import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import config, db, auth
from app.main import app

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA_DIR',tmp_path)
    monkeypatch.setattr(config,'DB_PATH',tmp_path/'test.sqlite3')
    monkeypatch.setattr(config,'VAULT_KEY_FILE',tmp_path/'secrets'/'vault.key')
    monkeypatch.setattr(config,'OPENAI_KEY','')
    monkeypatch.setattr(config,'ALLOW_SERVER_AI_KEY',True)
    monkeypatch.setattr(config,'ONET_KEY','')
    monkeypatch.setattr(config,'ADZUNA_ID','')
    monkeypatch.setattr(config,'ADZUNA_KEY','')
    monkeypatch.setattr(config,'ENABLE_JOBSPY',False)
    auth.attempts.clear()
    with TestClient(app,base_url='http://localhost') as client:
        yield client

def onboard_test_account(user):
    # Ownership/document regression tests exercise an already-onboarded account.
    # First-time setup itself is tested using real fresh registrations separately.
    from app.models import ExperienceItem
    db.save(user['id'],'experience',ExperienceItem(category='education',title='Test setup education',degree='BS',organization='Fictional Setup University',confirmed=True,end_date='2020-05').model_dump())

@pytest.fixture
def account(client):
    response=client.post('/api/auth/register',json={'username':'student','password':'fictional-test-password'})
    assert response.status_code==200,response.text
    user=response.json()
    onboard_test_account(user)
    client.headers['X-CSRF-Token']=user['csrf']
    return user

@pytest.fixture
def sample(client,account):
    return cached_posting_fixture(account['id'],load_example(account['id'],'analyst'))


def cached_posting_fixture(user,job):
    """Comparison-contract tests start after extraction; extraction has its own tests."""
    from app import job_parser,posting_extraction
    overview=job_parser.organize(job['data'])
    overview['extraction_version']=posting_extraction.VERSION
    return db.save(user,'job',{**job['data'],'structured_posting':overview},job['id'])

def comparison_wire(value,job,payload):
    """Convert legacy fixture results to the ID-only provider contract."""
    from app import comparison,ai
    catalogs=comparison.posting_catalogs(job);result={**value}
    fields=('criterion_id','status','evidence','explanation','question')
    for field,rows in catalogs.items():
        seen=set();assessed=[]
        for row in value.get(field,[]):
            criterion=next((c for c in rows if c['id']==row.get('criterion_id')),None)
            if not criterion:criterion=next((c for c in rows if ai.valid_quote(row.get('job_quote',''),c['source'])),None)
            if not criterion or criterion['id'] in seen:continue
            seen.add(criterion['id']);assessed.append({key:criterion['id'] if key=='criterion_id' else row[key] for key in fields})
        result[field]=assessed
    sources=payload['professional_evidence_catalog']+payload['private_eligibility_catalog']
    for field in ('requirements','duty_assessments','recommendations','keywords'):
        result[field]=[{**row,'evidence':[{'source_id':next(source['source_id'] for source in sources if source['record_id']==ref['record_id'] and ai.valid_quote(ref['quote'],source['quote']))} for ref in row['evidence']]} for row in result.get(field,[])]
    result['suggestions']=[{'source_id':next(source['source_id'] for source in payload['rewrite_source_catalog'] if source['record_id']==row['record_id'] and ai.valid_quote(row['original'],source['quote'])),'guidance_source_id':next(source['source_id'] for source in payload['rewrite_guidance_catalog'] if source['guide_id']==row['guide_id'] and ai.valid_quote(row['guide_quote'],source['quote'])),'proposed':row['proposed'],'reason':row['reason']} for row in value.get('suggestions',[])]
    return result


def load_example(user,scenario):
    """Seed fictional reviewed data directly; demo UI cannot bypass education setup."""
    import json
    from app.models import ExperienceItem
    example=json.loads((config.CONTENT_DIR/'examples.json').read_text())[scenario]
    for row in db.list_entities(user,'experience'):db.delete(user,row['id'])
    db.update_settings(user,example.get('profile',{'name':example['name'],'contact':example['contact']}))
    for item in example['experience']:db.save(user,'experience',ExperienceItem.model_validate(item).model_dump())
    return db.save(user,'job',{'title':example['role'],'company':'Fictional classroom example','description':example['posting'],'url':''})


def without_setup(records):
    """Ignore only the explicit education scaffold in unrelated feature assertions.
    Production queries still receive it, and education tests inspect the full Profile.
    Imported copies retain their label, so backup assertions test their own records.
    """
    return [r for r in records if r.get('data',{}).get('title')!='Test setup education']
