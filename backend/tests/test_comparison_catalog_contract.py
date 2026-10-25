from conftest import without_setup
from conftest import cached_posting_fixture
import asyncio
import copy
import json
import pytest
from pydantic import ValidationError
from app import ai,comparison,config,db,job_parser,role_alignment
from app.models import CatalogComparisonOutput
from app.network import ServiceError
from test_applications_workflow import wait_task

POSTING='''Junior Machine Learning Engineer
Requirements
Minimum GPA: 3.0
Work authorization
To be considered, you must also be a U.S. Citizen.
What you will do
Build, train, and validate machine learning models for engineering teams.
Document your work clearly and present findings to technical audiences.
'''

@pytest.fixture
def comparison_case(client,account,monkeypatch):
    monkeypatch.setattr(config,'OPENAI_KEY','fictional-fixture-no-network')
    job=client.post('/api/jobs',json={'title':'ML Engineer','description':POSTING}).json()
    job=cached_posting_fixture(account['id'],job)
    record=client.post('/api/experience',json={'title':'Fictional project','category':'project','gpa':'4.0','description':'Documented a data-preparation workflow and presented findings.','confirmed':True}).json()
    return job,record


def wire(payload,record):
    sources=payload.get('professional_evidence_catalog',comparison.evidence_catalog([record],{})['professional'])
    def rows(catalog):
        return [{'criterion_id':c['id'],'status':'supported' if c['kind']=='qualification' else 'unknown','evidence':[{'source_id':next(s['source_id'] for s in sources if s['record_id']==record['id'] and s['quote']=='4.0')}] if c['kind']=='qualification' else [],'explanation':'Self-reported GPA.' if c['kind']=='qualification' else 'Needs more information.','question':''} for c in catalog]
    return {'summary':'Fictional comparison.','requirements':rows(payload['criterion_catalog']),'duty_assessments':rows(payload['duty_catalog']),'job_details':[],'recommendations':[],'suggestions':[],'keywords':[],'questions':[]}


def mock_provider(monkeypatch,record,change=None):
    calls=[]
    async def fake(body):
        calls.append(body);payload=json.loads(body['input']);value=wire(payload,record)
        if change:change(value,payload)
        return {'status':'completed','model':body['model'],'usage':{'input_tokens':100,'output_tokens':100,'total_tokens':200},'output':[{'content':[{'type':'output_text','text':json.dumps(value)}]}]}
    monkeypatch.setattr(ai,'call_api',fake)
    return calls


def test_first_comparison_succeeds_once_without_model_recopying_posting_sources(client,account,comparison_case,monkeypatch):
    job,record=comparison_case;calls=mock_provider(monkeypatch,record)
    result=wait_task(client,client.post('/api/analyses',json={'job_id':job['id'],'request_token':'first-catalog-comparison'}))
    assert result['status']=='completed',result
    assert len(calls)==1
    result=result['result']['data'];assert result['score']['value']==100
    expected=comparison.posting_catalogs(job['data'])
    for field,rows in expected.items():
        assert {r['criterion_id']:r['job_quote'] for r in result[field]}=={c['id']:c['source'] for c in rows}
        assert all(ai.valid_quote(r['job_quote'],POSTING) for r in result[field])
    schema=calls[0]['text']['format']['schema'];assessment=schema['$defs']['CriterionAssessment']
    assert set(assessment['properties'])=={'criterion_id','status','evidence','explanation','question','project_context_ids'}
    assert 'job_quote' not in assessment['required'] and assessment['additionalProperties'] is False
    assert calls[0]['text']['format']['name']=='CatalogComparisonOutput'
    assert without_setup(client.get('/api/workspace').json()['experience'])[0]==record


@pytest.mark.parametrize('tamper',['unknown','wrong_group','duplicate','profile_quote','profile_id','missing_evidence'])
def test_id_binding_never_repairs_untrusted_ids_or_profile_evidence(client,account,comparison_case,monkeypatch,tamper):
    job,record=comparison_case
    old=db.save(account['id'],'analysis',{'job_id':job['id'],'summary':'Previous saved result','requirements':[],'job_details':[],'suggestions':[]})
    def change(value,payload):
        row=value['requirements'][0]
        if tamper=='unknown':row['criterion_id']='nonexistent'
        elif tamper=='wrong_group':row['criterion_id']=payload['duty_catalog'][0]['id']
        elif tamper=='duplicate':value['requirements'].append(copy.deepcopy(row))
        elif tamper=='profile_quote':row['evidence'][0]['quote']='Invented GPA 4.8'
        elif tamper=='profile_id':row['evidence'][0]['record_id']='foreign-record'
        else:row['evidence']=[]
    calls=mock_provider(monkeypatch,record,change)
    result=wait_task(client,client.post('/api/analyses',json={'job_id':job['id']}))
    assert result['status']=='failed' and len(calls)==1
    assert db.list_entities(account['id'],'analysis')==[old]
    assert 'Invented GPA' not in result['error']


def test_invalid_server_catalog_fails_before_provider_dispatch(client,account,comparison_case,monkeypatch):
    job,record=comparison_case
    original=job_parser.criteria(job['data']);original[0]['source']='Not in the posting'
    monkeypatch.setattr(job_parser,'criteria',lambda job:original)
    async def forbidden(*args,**kwargs):raise AssertionError('Provider must not be called')
    monkeypatch.setattr(ai,'call_api',forbidden)
    with pytest.raises(ServiceError,match='no OpenAI request was started'):asyncio.run(ai.analyze(account['id'],job['data'],'economy'))


def test_new_provider_contract_forbids_invented_posting_quote_fields(comparison_case):
    job,record=comparison_case;catalogs=comparison.posting_catalogs(job['data'])
    payload={'criterion_catalog':catalogs['requirements'],'duty_catalog':catalogs['duty_assessments']}
    output=wire(payload,record);output['requirements'][0]['job_quote']='Invented requirement'
    with pytest.raises(ValidationError):CatalogComparisonOutput.model_validate(output)


def test_missing_rows_remain_unknown_and_catalog_wording_classification_is_authoritative(comparison_case):
    job,record=comparison_case;catalogs=comparison.posting_catalogs(job['data'])
    output=wire({'criterion_catalog':catalogs['requirements'],'duty_catalog':catalogs['duty_assessments']},record)
    output['requirements']=[];output['duty_assessments']=[]
    result=comparison.validate(comparison.attach_posting_sources(output,catalogs),job['data'],[record],{})
    assert result['score']['value']==0 and result['score']['coverage']['total']==1
    assert all(r['status']=='unknown' for r in result['requirements'])
    assert all(not r['assessment_complete'] for r in result['duty_assessments'])
