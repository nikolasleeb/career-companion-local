import json
import pytest
from app import db,work_preferences,assistant_context,work_style_neo

@pytest.fixture
def shared_report(client,account):
 u=account['id'];cat=work_style_neo.catalog();report=work_style_neo.score({x['id']:3 for x in cat['items']},{'p1':'left'})
 report['raw_answers']='SECRET_RAW_REPORT';report['preferences'][0]['raw']='SECRET_CHOICE_EXTRA'
 record=db.save(u,'work_style',{'status':'completed','completed_at':db.now(),'report':report,'answers':{'private':'SECRET_QUESTIONNAIRE'},'comparison_answers':{'private':'SECRET_RAW_COMPARISONS'}})
 return u,record

def save(client,record,revision=0,**changes):
 return client.put('/api/profile/work-preferences',json={'summary':'I like focused preparation and planned collaboration.','reviewed':True,'use_for_ai':True,'expected_revision':revision,'assessment_id':record['id'],**changes})

def test_legacy_summary_consent_does_not_grant_report_access(client,shared_report):
 u,record=shared_report
 assert save(client,record).status_code==200
 assert not work_preferences.read(u)['coach_report_access']
 assert work_preferences.coach_context(u) is None
 assert not work_preferences.resume_context(u)['preferences']
 assert not any(s['kind']=='work_style_report' for s in assistant_context.sources(u))

def test_explicit_scope_exposes_report_scores_and_choices_but_never_raw_answers(client,shared_report):
 u,record=shared_report;r=save(client,record,coach_report_access=True);assert r.status_code==200,r.text
 report=work_preferences.coach_context(u)
 assert len(report['report']['domains'])==5 and len(report['report']['facets'])==30
 assert report['report']['domains'][0]['mean']==3 and report['report']['work_choices'][0]['selected']
 assert 'SECRET' not in json.dumps(report)
 sources=[s for s in assistant_context.sources(u) if s['kind']=='work_style_report']
 assert sources and all(s['record_id']==record['id'] for s in sources)
 assert 'SECRET' not in json.dumps(sources)
 assert any(s['kind']=='work_style_report' for s in assistant_context.retrieve(u,'Explain my Conscientiousness report scores'))
 summary=work_preferences.context(u)
 assert summary['preferences']==['I like focused preparation and planned collaboration.']
 assert 'domains' not in json.dumps(summary) and 'facets' not in json.dumps(summary)


def test_revocation_and_report_deletion_remove_new_retrieval(client,shared_report):
 u,record=shared_report;assert save(client,record,coach_report_access=True).status_code==200
 assert save(client,record,1,use_for_ai=False).status_code==200
 assert not work_preferences.read(u)['coach_report_access'] and work_preferences.coach_context(u) is None
 assert not any(s['kind']=='work_style_report' for s in assistant_context.sources(u))
 assert save(client,record,2,coach_report_access=True).status_code==200
 db.delete(u,record['id']);assert work_preferences.coach_context(u) is None


def test_other_account_cannot_share_or_retrieve_a_report(client,shared_report):
 u,record=shared_report;save(client,record,coach_report_access=True)
 other=client.post('/api/auth/register',json={'username':'another-work-style-user','password':'fictional-password'}).json()
 from conftest import onboard_test_account
 onboard_test_account(other);client.headers['X-CSRF-Token']=other['csrf']
 assert save(client,record,coach_report_access=True).status_code==404
 assert work_preferences.coach_context(other['id']) is None
 assert not any(s['record_id']==record['id'] for s in assistant_context.sources(other['id']))
 with pytest.raises(Exception):assistant_context.retrieve(other['id'],'work styles',pinned=[record['id']])


def test_backup_restore_requires_fresh_sharing_consent(client,account):
 u=account['id'];record=client.post('/api/work-style').json();ratings={x['id']:3 for x in work_style_neo.catalog()['items']}
 completed=client.post('/api/work-style/'+record['id']+'/score',json={'expected_version':record['data']['version'],'answers':ratings,'comparison_answers':{'p1':'left'},'page':0})
 assert completed.status_code==200,completed.text
 assert save(client,record,coach_report_access=True).status_code==200
 backup=client.get('/api/account/export').json()
 restored=client.post('/api/account/import',files={'file':('work-styles.json',json.dumps(backup).encode(),'application/json')})
 assert restored.status_code==200,restored.text
 assert not work_preferences.read(u)['use_for_ai'] and not work_preferences.read(u)['coach_report_access']
 assert work_preferences.coach_context(u) is None
