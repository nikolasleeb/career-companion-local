import copy
import json
import pytest
from pydantic import ValidationError
from app import ai,comparison,config,db,guidance
from app.models import CatalogComparisonOutput
from app.network import ServiceError
from test_applications_workflow import wait_task
from test_comparison_catalog_contract import POSTING,wire


@pytest.fixture
def case(client,account,monkeypatch):
    monkeypatch.setattr(config,'OPENAI_KEY','fictional-no-network')
    job=client.post('/api/jobs',json={'title':'ML Engineer','description':POSTING}).json()
    record=client.post('/api/experience',json={'category':'project','title':'Fictional project','gpa':'4.0','description':'Documented a workflow for classmates.','contribution':'I have not trained a model.','confirmed':True}).json()
    return job,record


def rewrite(payload,field='description'):
    return {'source_id':next(s['source_id'] for s in payload['rewrite_source_catalog'] if s['field']==field),'guidance_source_id':payload['rewrite_guidance_catalog'][0]['source_id'],'proposed':'Documented the workflow for classmates.','reason':'Keep the supported action clear.'}


def test_rewrite_catalog_excludes_structured_private_and_metadata_fields(case,account):
    _,record=case
    retrieved=[record]+[{'id':g['id'],'kind':'guidance','data':g} for g in guidance.selected('resume')['items']]
    evidence=comparison.evidence_catalog(retrieved,{'us_citizen':'yes'})
    catalog=comparison.rewrite_catalog(retrieved,evidence)
    assert {s['field'] for s in catalog['sources']}=={'description','contribution'}
    assert all(s['record_id']==record['id'] for s in catalog['sources'])
    assert all(g['guide_id'] in {r['id'] for r in retrieved if r['kind']=='guidance'} for g in catalog['guidance'])
    assert all(ai.valid_quote(g['quote'],next(r['data']['text'] for r in retrieved if r['id']==g['guide_id'])) for g in catalog['guidance'])
    assert not any(g['source_id'] in {s['source_id'] for s in evidence['professional']} for g in catalog['guidance'])


def test_new_rewrite_schema_requires_only_ids_proposed_and_reason(case):
    job,record=case;catalog=comparison.posting_catalogs(job['data'])
    value=wire({'criterion_catalog':catalog['requirements'],'duty_catalog':catalog['duty_assessments']},record)
    value['suggestions']=[{'source_id':'example','guidance_source_id':'guide','proposed':'Wording.','reason':'Clarity.'}]
    assert CatalogComparisonOutput.model_validate(value).suggestions[0].source_id=='example'
    value['suggestions'][0]['original']='Invented source'
    with pytest.raises(ValidationError):CatalogComparisonOutput.model_validate(value)
    schema=CatalogComparisonOutput.model_json_schema()['$defs']['CatalogSuggestion']
    assert set(schema['properties'])=={'source_id','guidance_source_id','proposed','reason'}
    assert schema['additionalProperties'] is False


@pytest.mark.parametrize('bad',['source','guidance','structured','number','negation','employment'])
def test_invalid_optional_rewrite_never_discards_valid_comparison_or_other_edit(client,account,case,monkeypatch,bad):
    job,record=case;calls=[]
    old=db.save(account['id'],'analysis',{'job_id':job['id'],'summary':'Historical saved comparison','suggestions':[]})
    async def fake(body):
        calls.append(body);payload=json.loads(body['input']);output=wire(payload,record)
        valid=rewrite(payload);invalid=copy.deepcopy(valid)
        if bad=='source':invalid['source_id']='foreign-or-stale-source'
        elif bad=='guidance':invalid['guidance_source_id']='foreign-or-stale-guidance'
        elif bad=='structured':invalid['source_id']=next(s['source_id'] for s in payload['professional_evidence_catalog'] if s['field']=='gpa')
        elif bad=='number':invalid['proposed']='Improved accuracy by 92%.'
        elif bad=='negation':invalid.update(source_id=rewrite(payload,'contribution')['source_id'],proposed='Trained a model.')
        elif bad=='employment':invalid['proposed']='Employed as a professional analyst.'
        output['suggestions']=[invalid,valid]
        return {'status':'completed','model':body['model'],'usage':{'input_tokens':100,'output_tokens':100,'total_tokens':200},'output':[{'content':[{'type':'output_text','text':json.dumps(output)}]}]}
    monkeypatch.setattr(ai,'call_api',fake)
    token='one-rewrite-comparison-'+bad
    task=wait_task(client,client.post('/api/analyses',json={'job_id':job['id'],'request_token':token}))
    assert task['status']=='completed',task
    repeated=wait_task(client,client.post('/api/analyses',json={'job_id':job['id'],'request_token':token}))
    assert repeated['id']==task['id'] and len(calls)==1
    result=task['result']['data']
    assert result['omitted_suggestions']==1 and result['score']['value']==100
    assert len(result['suggestions'])==1
    suggestion=result['suggestions'][0]
    assert suggestion['record_id']==record['id'] and suggestion['original']==record['data']['description']
    assert suggestion['proposed']=='Documented the workflow for classmates.'
    guide=next(r for r in result['retrieved'] if r['id']==suggestion['guide_id'])
    assert suggestion['guide_quote']==guide['data']['text']
    ai.validate_analysis({'requirements':[],'suggestions':result['suggestions']},job['data'],result['retrieved'])
    assert client.get('/api/workspace').json()['experience']==[record]
    assert db.get(account['id'],old['id'],'analysis')==old


def test_all_invalid_optional_edits_still_save_verified_assessments(client,account,case,monkeypatch):
    job,record=case;calls=[]
    async def fake(body):
        calls.append(body);payload=json.loads(body['input']);output=wire(payload,record)
        output['suggestions']=[{**rewrite(payload),'guidance_source_id':'unknown'}]
        return {'output':[{'content':[{'type':'output_text','text':json.dumps(output)}]}]}
    monkeypatch.setattr(ai,'call_api',fake)
    task=wait_task(client,client.post('/api/analyses',json={'job_id':job['id']}))
    assert task['status']=='completed' and len(calls)==1
    result=task['result']['data']
    assert result['omitted_suggestions']==1 and result['suggestions']==[] and result['score']['value']==100
    assert result['requirements'] and result['duty_assessments']


def test_legacy_invalid_rewrite_filtered_but_core_evidence_still_fails(case):
    job,record=case
    catalogs=comparison.posting_catalogs(job['data'])
    output=comparison.attach_posting_sources(wire({'criterion_catalog':catalogs['requirements'],'duty_catalog':catalogs['duty_assessments']},record),catalogs)
    output=comparison.attach_evidence_sources(output,comparison.evidence_catalog([record],{}))
    output['suggestions']=[{'record_id':record['id'],'original':record['data']['description'],'proposed':'Invented','reason':'Clarity','guide_id':'unknown','guide_quote':'Made up'}]
    assert comparison.validate(copy.deepcopy(output),job['data'],[record],{})['omitted_suggestions']==1
    output['requirements'][0]['evidence'][0]['quote']='Invented GPA'
    with pytest.raises(ServiceError,match='reference'):comparison.validate(output,job['data'],[record],{})
