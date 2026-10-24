import copy
import json
import pytest
from pydantic import ValidationError
from app import ai, comparison, config, db
from app.models import CatalogComparisonOutput
from app.network import ServiceError
from test_applications_workflow import wait_task
from test_comparison_catalog_contract import POSTING, wire


def test_catalog_preserves_exact_fields_subject_commas_negation_and_structured_skills():
    records=[{'id':'project','kind':'experience','data':{'category':'project','title':'Data project','description':'Prepared data.\nPresented results, with limitations.','contribution':'I have not trained a model.','majors':['Economics, Politics and Law','Data Science'],'minors':['Statistics','Business'],'skill_items':[{'name':'Python','level':'intermediate','context':'Used pandas for ETL.'}],'answer_sources':[{'text':'Metadata is not approved record wording.'}]}},
             {'id':'credential','kind':'experience','data':{'category':'skills','title':'Certifications','tools':'not a skill claim','certification_items':[{'name':'Example credential','issuer':'Example Institute','earned_date':'2025-01-01','expiration_date':'2027-01-01'}]}},
             {'id':'guide','kind':'guidance','data':{'text':'Guidance is not applicant experience.'}}]
    catalog=comparison.evidence_catalog(records,{'us_citizen':'yes','email':'private@example.test'})
    source_text={r['id']:ai.experience_text(r['data']) for r in records if r['kind']=='experience'}
    assert all(ai.valid_quote(s['quote'],source_text[s['record_id']]) for s in catalog['professional'])
    assert len({s['source_id'] for s in catalog['professional']})==len(catalog['professional'])
    assert any(s['quote']=='I have not trained a model.' for s in catalog['professional'])
    assert any('Economics, Politics and Law' in s['quote'] and 'Data Science' in s['quote'] for s in catalog['professional'])
    assert any('Used pandas for ETL.' in s['quote'] for s in catalog['professional'])
    assert any('Expires 2027-01-01' in s['quote'] for s in catalog['professional'])
    assert not any(word in json.dumps(catalog) for word in ('Metadata is not','Guidance is not','not a skill claim','private@example.test'))
    assert catalog['eligibility'][0]['record_id']=='profile:us_citizen'


def test_source_ids_change_with_content_and_record_ownership():
    record={'id':'mine','kind':'experience','data':{'description':'Prepared a report.'}}
    original=comparison.evidence_catalog([record],{})['professional'][0]['source_id']
    assert comparison.evidence_catalog([copy.deepcopy(record)],{})['professional'][0]['source_id']==original
    changed=copy.deepcopy(record);changed['data']['description']='Prepared a different report.'
    foreign={**record,'id':'other-account-record'}
    for current in (changed,foreign):
        catalog=comparison.evidence_catalog([current],{})
        with pytest.raises(ServiceError,match='unavailable Profile passage'):
            comparison.attach_evidence_sources({'duty_assessments':[{'evidence':[{'source_id':original}]}]},catalog)


@pytest.mark.parametrize('section',['qualification','duty_assessments','recommendations','keywords'])
def test_private_source_ids_rejected_outside_eligibility(section):
    catalog=comparison.evidence_catalog([],{'authorized_us':'yes'})
    row={'kind':'qualification','record_id':'profile:authorized_us','evidence':[{'source_id':catalog['eligibility'][0]['source_id']}]}
    field='requirements' if section=='qualification' else section
    with pytest.raises(ServiceError,match='private eligibility evidence outside'):
        comparison.attach_evidence_sources({field:[row]},catalog)
    result=comparison.attach_evidence_sources({'requirements':[{**row,'kind':'eligibility'}]},catalog)
    assert result['requirements'][0]['evidence']==[{'record_id':'profile:authorized_us','quote':'authorized_us = yes'}]


def test_recommendation_cannot_borrow_another_records_passage():
    catalog=comparison.evidence_catalog([{'id':'one','kind':'experience','data':{'title':'One'}}],{})
    with pytest.raises(ServiceError,match='another record'):
        comparison.attach_evidence_sources({'recommendations':[{'record_id':'two','evidence':[{'source_id':catalog['professional'][0]['source_id']}]}]},catalog)


def test_provider_evidence_schema_rejects_copied_or_invented_quotes():
    record={'id':'one','kind':'experience','data':{'gpa':'4.0'}}
    catalogs=comparison.posting_catalogs({'description':POSTING})
    value=wire({'criterion_catalog':catalogs['requirements'],'duty_catalog':catalogs['duty_assessments']},record)
    value['requirements'][0]['evidence'][0]['quote']='Invented result'
    with pytest.raises(ValidationError):CatalogComparisonOutput.model_validate(value)
    schema=CatalogComparisonOutput.model_json_schema()
    assert set(schema['$defs']['CatalogEvidence']['properties'])=={'source_id'}
    assert schema['$defs']['CatalogEvidence']['additionalProperties'] is False
    for name in ('CriterionAssessment','CatalogRecommendation','CatalogKeyword'):
        assert schema['$defs'][name]['properties']['evidence']['items']['$ref'].endswith('/CatalogEvidence')


def test_first_comparison_binds_multiple_professional_passages_once_without_private_leak(client,account,monkeypatch):
    monkeypatch.setattr(config,'OPENAI_KEY','fictional-fixture-no-network')
    client.put('/api/settings',json={'us_citizen':'yes'})
    job=client.post('/api/jobs',json={'title':'ML Engineer','description':POSTING}).json()
    record=client.post('/api/experience',json={'category':'project','title':'Fictional project','gpa':'4.0','description':'Prepared the data.\nDocumented the workflow.','contribution':'Presented findings to classmates.\nI have not trained a model.','confirmed':True}).json()
    calls=[]
    async def fake(body):
        calls.append(body);payload=json.loads(body['input']);value=wire(payload,record)
        def source(text):return {'source_id':next(s['source_id'] for s in payload['professional_evidence_catalog'] if s['quote']==text)}
        for duty in value['duty_assessments']:
            if 'Document' in next(c['text'] for c in payload['duty_catalog'] if c['id']==duty['criterion_id']):
                duty.update(status='supported',evidence=[source('Documented the workflow.'),source('Presented findings to classmates.')])
            else:duty.update(status='not_met',evidence=[source('I have not trained a model.')])
        eligibility=next(r for r in value['requirements'] if r['status']=='unknown')
        eligibility.update(status='supported',evidence=[{'source_id':payload['private_eligibility_catalog'][0]['source_id']}])
        value['recommendations']=[{'record_id':record['id'],'reason':'Relevant documentation work.','evidence':[source('Documented the workflow.')]}]
        value['keywords']=[{'term':'Document','job_quote':'Document your work clearly and present findings to technical audiences.','evidence':[source('Documented the workflow.')]}]
        return {'status':'completed','model':body['model'],'usage':{'input_tokens':100,'output_tokens':100,'total_tokens':200},'output':[{'content':[{'type':'output_text','text':json.dumps(value)}]}]}
    monkeypatch.setattr(ai,'call_api',fake)
    token='single-evidence-dispatch'
    start=client.post('/api/analyses',json={'job_id':job['id'],'request_token':token})
    task=wait_task(client,start);assert task['status']=='completed',task
    repeated=wait_task(client,client.post('/api/analyses',json={'job_id':job['id'],'request_token':token}))
    assert repeated['id']==task['id'] and len(calls)==1
    result=task['result']['data'];assert result['score']['value']==100
    assert {r['status'] for r in result['duty_assessments']}=={'supported','not_met'}
    for field in ('duty_assessments','recommendations','keywords'):
        assert all(e['record_id']==record['id'] and ai.valid_quote(e['quote'],ai.experience_text(record['data'])) for row in result[field] for e in row['evidence'])
    assert all('source_id' not in e for row in result['requirements'] for e in row['evidence'])
    assert client.get('/api/workspace').json()['experience']==[record]


@pytest.mark.parametrize('identity',['foreign-passage','evidence:stale-content'])
def test_invalid_passage_fails_once_keeps_previous_result(client,account,monkeypatch,identity):
    monkeypatch.setattr(config,'OPENAI_KEY','fictional-fixture-no-network')
    job=client.post('/api/jobs',json={'title':'ML Engineer','description':POSTING}).json()
    record=client.post('/api/experience',json={'category':'project','title':'Fictional','gpa':'4.0','confirmed':True}).json()
    old=db.save(account['id'],'analysis',{'job_id':job['id'],'summary':'Previous result'})
    calls=[]
    async def fake(body):
        calls.append(body);value=wire(json.loads(body['input']),record)
        value['duty_assessments'][0].update(status='supported',evidence=[{'source_id':identity}])
        return {'output':[{'content':[{'type':'output_text','text':json.dumps(value)}]}]}
    monkeypatch.setattr(ai,'call_api',fake)
    task=wait_task(client,client.post('/api/analyses',json={'job_id':job['id']}))
    assert task['status']=='failed' and 'unavailable Profile passage' in task['error'] and len(calls)==1
    assert db.list_entities(account['id'],'analysis')==[old]


@pytest.mark.parametrize('evidence,message',[
    ({'record_id':'profile:us_citizen','quote':'us_citizen = yes'},'private eligibility answer'),
    ({'record_id':'missing','quote':'anything'},'unavailable confirmed experience'),
    ({'record_id':'project','quote':'Invented work'},'did not match its confirmed experience source'),
])
def test_legacy_duty_errors_distinguish_private_unknown_and_mismatched(evidence,message):
    from app import role_alignment
    job={'description':POSTING};criterion=role_alignment.catalog(job)[0]
    row={'criterion_id':criterion['id'],'job_quote':criterion['source'],'evidence':[evidence]}
    with pytest.raises(ServiceError,match=message):
        role_alignment.validate({'duty_assessments':[row]},job,{'project':'Prepared data.','profile:us_citizen':'us_citizen = yes'})
