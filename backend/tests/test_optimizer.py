from conftest import onboard_test_account
import copy
import io
import json
import time
import pytest
from docx import Document
from pypdf import PdfReader
from fastapi.testclient import TestClient
from app import ai, config, db, comparison, job_parser, optimization, resume_builder, resume_data, documents
from app.main import app
from app.network import ServiceError
from test_applications_workflow import wait_task

POSTING='''Analyst internship
Requirements
Excellent written and verbal communication.
Relevant project or internship experience.
Currently enrolled as a rising senior in a Bachelor’s or Master’s degree program.
Preferred Qualifications
SQL or Python proficiency.
Core Competencies
Curiosity and critical thinking.
Proactivity and innovation.
Work authorization
Must be authorized to work in the United States without sponsorship.
'''

def setup(client,account):
    client.put('/api/settings',json={'name':'Fictional Student','headline':'Generic technical headline','authorized_us':'yes','sponsorship_now':'no'})
    job=client.post('/api/jobs',json={'title':'Analyst Intern','description':POSTING}).json()
    rows=[]
    for data in [
        {'category':'education','title':'MS Data Science','degree':'Master of Science','major':'Data Science','organization':'Example University','expected_graduation':'May 2027','gpa':'4.0','description':'Worked unrelated shifts while studying.','relevant_courses':'Database Systems; Statistics'},
        {'category':'project','title':'Demand analysis','description':'Analyzed demand data using Python and presented findings to classmates.','contribution':'Prepared clear charts and documented the analysis.'},
        {'category':'skills','title':'Programming','skill_items':[{'name':'Python','level':'intermediate'},{'name':'SQL','level':'unknown'}]},
        {'category':'skills','title':'Certifications','tools':'AWS Certified Cloud Practitioner'},
    ]:
        rows.append(client.post('/api/experience',json={**data,'confirmed':True}).json())
    body={'job_id':job['id'],'experience_ids':[r['id'] for r in rows]}
    return job,rows,body


def fake_draft(payload):
    entries=[]
    for r in payload['catalog']:
        items=[i for i in r['items'] if i['field']!='education_note' and i['text']]
        entries.append({'record_id':r['id'],'reason':'Relevant evidence for the analyst role.','items':[{'item_id':i['item_id'],'text':i['text'],'priority':90 if i['field'] in ('skill','certification') else 75,'reason':'Supports the job requirements.'} for i in items]})
    project=next(r for r in payload['catalog'] if r['category']=='project')
    return {'headline':'Data Science | Python & SQL','headline_evidence':[{'record_id':project['id'],'quote':project['bullets'][0]}], 'entries':entries,'keywords':[{'term':'Python','job_quote':'SQL or Python proficiency.','evidence':[{'record_id':project['id'],'quote':project['bullets'][0]}]},{'term':'SQL','job_quote':'SQL or Python proficiency.','evidence':[]}]}


def mock_model(monkeypatch,mutate=None,audit=True):
    monkeypatch.setattr(config,'OPENAI_KEY','fictional-no-network')
    calls=[]
    async def fake(body):
        payload=json.loads(body['input']);calls.append((body,payload))
        if body['text']['format']['name']=='DraftAudit':result=audit(payload) if callable(audit) else {'approved':audit,'issues':[] if audit else ['Unsupported accomplishment.']}
        else:
            result=fake_draft(payload)
            if mutate:mutate(result)
        return {'model':body['model'],'status':'completed','usage':{'input_tokens':1000,'output_tokens':200,'total_tokens':1200},'output':[{'content':[{'type':'output_text','text':json.dumps(result)}]}]}
    monkeypatch.setattr(ai,'call_api',fake)
    return calls


def test_shared_classification_excludes_competencies_and_enrollment():
    catalog=job_parser.criteria({'description':POSTING})
    assert len([c for c in catalog if c['kind']=='qualification' and c['importance']=='required'])==2
    assert len([c for c in catalog if c['kind']=='eligibility'])==2
    assert not any('Curiosity' in c['text'] for c in catalog)
    profile={'authorized_us':'yes'};records=[{'id':'project','kind':'experience','data':{'description':'Prepared reports using Python.'}}]
    output={'requirements':[],'job_details':[],'recommendations':[],'suggestions':[]}
    for i,c in enumerate(catalog):
        output['requirements'].append({'criterion_id':c['id'],'keyword':'Wrong heading','job_quote':c['source'],'kind':'qualification','importance':'required','status':'partial' if i==0 else 'supported','evidence':[{'record_id':'project','quote':'Prepared reports using Python.'}],'explanation':'Some evidence.','question':''})
    output['requirements'].append({'keyword':'Curiosity','job_quote':'Curiosity and critical thinking.','kind':'qualification','importance':'required','status':'supported','evidence':[],'explanation':'','question':''})
    result=comparison.validate(output,{'description':POSTING},records,profile)
    assert result['schema_version']==3 and result['score']['groups']['required']['total']==2
    assert result['score']['groups']['preferred']['total']==1 and result['score']['value']==83
    assert len(result['score']['contributions'])==3
    assert all(r['keyword']!='Wrong heading' for r in result['requirements'])


def test_conflict_score_and_missing_assessment():
    r={'keyword':'SQL','kind':'qualification','importance':'required','status':'not_met'}
    result=comparison.score([r]);assert result['value']==0 and result['groups']['required']['not_met']==1
    result=comparison.validate({'requirements':[],'job_details':[],'recommendations':[],'suggestions':[]},{'description':POSTING},[],{})
    assert result['score']['groups']['required']['total']==2 and result['score']['value']==0
    assert all(r['status']=='unknown' for r in result['requirements'])


def test_ai_draft_roundtrip_keywords_privacy_both_layouts(client,account,monkeypatch):
    job,rows,body=setup(client,account);calls=mock_model(monkeypatch)
    estimate=client.post('/api/resumes/optimize-estimate',json=body)
    assert estimate.status_code==200 and estimate.json()['usd']>0 and not calls
    task=wait_task(client,client.post('/api/resumes/optimize',json={**body,'mode':'custom'}))
    assert task['status']=='completed',task
    draft=task['result'];assert len(calls)==2 and draft['data']['source_checked']
    assert 'authorized_us' not in json.dumps(calls) and 'sponsorship_now' not in json.dumps(calls)
    assert all('Worked unrelated' not in b for r in draft['data']['catalog'] for i,b in enumerate(r['bullets']) if i in draft['data']['content'].get(r['id'],[]))
    req={**body,'draft_id':draft['id'],'headline':draft['data']['headline'],'content':draft['data']['content'],'experience_ids':draft['data']['experience_ids']}
    groups=client.post('/api/resumes/keywords',json=req).json()
    assert [k['term'] for k in groups['included']]==['Python'] and [k['term'] for k in groups['unknown']]==['SQL']
    no_project={**req,'headline':'','experience_ids':[r['id'] for r in rows if r['data']['category']=='education']}
    assert client.post('/api/resumes/keywords',json=no_project).json()['supported'][0]['term']=='Python'
    for template in ('education','experience'):
        saved=client.post('/api/resumes',json={**req,'template':template});assert saved.status_code==200,saved.text
        rid=saved.json()['id'];pdf=client.get('/api/resumes/'+rid+'/preview').content
        assert len(PdfReader(io.BytesIO(pdf)).pages)==1
        text='\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
        assert 'Python' in text and 'AWS Certified Cloud Practitioner' in text and 'Analyzed demand' in text
        assert 'Worked unrelated' not in text and 'Generic technical headline' not in text and 'authorized_us' not in text
        word=client.get('/api/resumes/'+rid+'/export/docx').content
        doc=Document(io.BytesIO(word));assert doc.styles['Normal'].font.size.pt==10.5
        assert documents.docx_pages(word)==1
        assert 'Data Science | Python & SQL' in client.get('/api/resumes/'+rid+'/export/txt').text
    assert len(calls)==2 # saving, selecting, rendering and downloading make no API requests
    backup=client.get('/api/account/export').json()
    assert any(r['kind']=='resume_draft' for r in backup['records'])
    assert client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')}).status_code==200
    drafts=db.list_entities(account['id'],'resume_draft');assert len(drafts)==2
    restored=next(d for d in drafts if d['id']!=draft['id']);d=restored['data']
    restored_req={**req,'draft_id':restored['id'],'job_id':d['job_id'],'experience_ids':d['experience_ids'],'content':d['content']}
    assert client.post('/api/resumes',json=restored_req).status_code==200
    assert client.get('/api/resume-drafts/'+restored['id']).status_code==200
    assert all(db.get(account['id'],rid,'experience') for rid in d['experience_ids'])


@pytest.mark.parametrize('kind',['number','credential','foreign','empty','audit'])
def test_invalid_draft_preserves_inputs_no_save(client,account,monkeypatch,kind):
    job,rows,body=setup(client,account)
    def mutate(d):
        if kind=='number':d['entries'][1]['items'][0]['text']='Increased revenue by 75% using Python.'
        elif kind=='credential':d['entries'][3]['items'][0]['text']='AWS Certified Solutions Architect'
        elif kind=='foreign':d['entries'][0]['record_id']='another-users-record'
        elif kind=='empty':d['entries'][1]['items']=[]
    calls=mock_model(monkeypatch,mutate,audit=kind!='audit')
    result=wait_task(client,client.post('/api/resumes/optimize',json=body))
    assert result['status']=='failed' and result['result']['inputs']['job_id']==job['id'],result
    assert db.list_entities(account['id'],'resume_draft')==[] and db.list_entities(account['id'],'resume')==[]
    assert len(db.list_entities(account['id'],'experience'))==4


def test_draft_ownership_and_project_description(client,account,monkeypatch):
    job,rows,body=setup(client,account);calls=mock_model(monkeypatch)
    result=wait_task(client,client.post('/api/resumes/optimize',json=body));draft=result['result']
    other=TestClient(app,base_url='http://localhost');me=other.post('/api/auth/register',json={'username':'another','password':'another-fictional-password'}).json();other.headers['X-CSRF-Token']=me['csrf']
    onboard_test_account(me)
    assert other.get('/api/resume-drafts/'+draft['id']).status_code==404
    assert other.post('/api/resumes',json={**body,'draft_id':draft['id']}).status_code==400
    project=rows[1]
    raw=client.post('/api/resume-content',json=body).json()['catalog'];p=next(r for r in raw if r['id']==project['id'])
    assert p['items'][0]['item_id']==resume_data.entry_snapshot(project['data'],project['id'],True)['content_items'][0]['item_id']
    assert client.post('/api/resumes',json={**body,'experience_ids':[project['id']],'content':{project['id']:[]}}).status_code==400


def test_fit_never_leaves_empty_project_or_skills(monkeypatch):
    entries=[resume_data.entry_snapshot({'category':'project','title':'Project','description':'Meaningful analysis.\nMore relevant analysis.'},'p',True),resume_data.entry_snapshot({'category':'skills','title':'Tools','tools':'Python, SQL'},'s',True)]
    snapshot={'schema_version':3,'sections':[{'title':'Projects','entries':entries}],'posting_snapshot':{'description':'Python analysis'}}
    seen=[]
    def render(value):
        seen.append(copy.deepcopy(value));count=sum(len(e['bullets']) for s in value['sections'] for e in s['entries'])
        return (1 if count<=2 else 2),{}
    monkeypatch.setattr(resume_builder,'render',render)
    fit=resume_builder.fit(snapshot,resume_builder.catalog(snapshot));result=resume_builder.select(snapshot,fit['content'],fit['experience_ids'])
    assert all(e['bullets'] for s in result['sections'] for e in s['entries'])
    assert sum(len(e['bullets']) for s in result['sections'] for e in s['entries'])==2


def test_user_edits_and_stale_source_preservation(client,account,monkeypatch):
    job,rows,body=setup(client,account);calls=mock_model(monkeypatch)
    task=wait_task(client,client.post('/api/resumes/optimize',json=body));draft=task['result']
    project=next(r for r in draft['data']['catalog'] if r['category']=='project');item=project['items'][0]
    req={**body,'draft_id':draft['id'],'headline':'Business Analytics | Python','experience_ids':draft['data']['experience_ids'],'content':draft['data']['content'],'overrides':{item['item_id']:'Used Python to analyze demand data and present findings to classmates.'}}
    saved=client.post('/api/resumes',json=req);assert saved.status_code==200,saved.text
    text=client.get('/api/resumes/'+saved.json()['id']+'/export/txt').text
    assert 'Business Analytics | Python' in text and 'Used Python to analyze demand' in text
    assert len(calls)==2
    source=next(r for r in rows if r['id']==project['id'])
    client.put('/api/experience/'+source['id'],json={**source['data'],'description':'Changed source content after the AI draft.'})
    assert client.post('/api/resumes',json=req).status_code==409
    assert db.get(account['id'],draft['id'],'resume_draft')['data']['headline']=='Data Science | Python & SQL'
    assert client.get('/api/resumes/'+saved.json()['id']+'/preview').status_code==200


def test_accepted_edits_survive_optimization(client,account,monkeypatch):
    job,rows,body=setup(client,account);calls=mock_model(monkeypatch)
    project=rows[1];original=project['data']['description'];replacement='Used Python to analyze demand data and presented the findings to classmates.'
    analysis=db.save(account['id'],'analysis',{'schema_version':3,'job_id':job['id'],'requirements':[],'suggestions':[{'record_id':project['id'],'original':original,'proposed':replacement}]})
    req={**body,'analysis_id':analysis['id'],'decisions':[{'index':0,'action':'accept'}]}
    task=wait_task(client,client.post('/api/resumes/optimize',json=req));assert task['status']=='completed',task
    payload=calls[0][1];assert replacement in payload['accepted_edits'].values()
    draft=task['result']
    saved=client.post('/api/resumes',json={**req,'draft_id':draft['id'],'content':draft['data']['content'],'experience_ids':draft['data']['experience_ids']})
    assert saved.status_code==200,saved.text
    assert replacement in client.get('/api/resumes/'+saved.json()['id']+'/export/txt').text


def test_multiline_accepted_edit_keeps_source_selection_stable(client,account,monkeypatch):
    job,rows,body=setup(client,account);mock_model(monkeypatch)
    project=rows[1];original='Analyzed demand using Python.\nPresented findings to classmates.'
    project=client.put('/api/experience/'+project['id'],json={**project['data'],'description':original}).json()
    replacement='Analyzed demand using Python and presented findings to classmates.'
    analysis=db.save(account['id'],'analysis',{'schema_version':3,'job_id':job['id'],'requirements':[],'suggestions':[{'record_id':project['id'],'original':original,'proposed':replacement}]})
    req={**body,'analysis_id':analysis['id'],'decisions':[{'index':0,'action':'accept'}]}
    task=wait_task(client,client.post('/api/resumes/optimize',json=req));assert task['status']=='completed',task
    draft=task['result']
    saved=client.post('/api/resumes',json={**req,'draft_id':draft['id'],'experience_ids':draft['data']['experience_ids'],'content':draft['data']['content']})
    assert saved.status_code==200,saved.text
    text=client.get('/api/resumes/'+saved.json()['id']+'/export/txt').text
    assert replacement in text and 'Prepared clear charts and documented the analysis.' in text


def test_posting_change_rejects_stale_comparison_draft(client,account,monkeypatch):
    job,rows,body=setup(client,account);mock_model(monkeypatch)
    task=wait_task(client,client.post('/api/resumes/optimize',json=body));draft=task['result']
    client.put('/api/jobs/'+job['id'],json={**job['data'],'description':POSTING+'\nPreferred Qualifications\nTableau experience.\n'})
    req={**body,'draft_id':draft['id'],'content':draft['data']['content'],'experience_ids':draft['data']['experience_ids']}
    assert client.post('/api/resumes',json=req).status_code==409
    assert client.get('/api/resume-drafts/'+draft['id']).status_code==200


def test_citations_keep_original_and_checked_wording_separate_and_record_bound():
    original='Built Python reports for operations teams.'
    rewrite='Prepared operations reports using Python.'
    item={'item_id':'one','field':'description','original':original,'text':rewrite}
    entry={'source_id':'project','title':'Operations analysis','details':'Class project','category':'project','bullets':[rewrite],'source_original_bullets':[original],'content_items':[item]}
    snapshot={'sections':[{'entries':[entry]}],'posting_snapshot':{'description':'Python reporting'}}
    records=optimization.evidence_sources(snapshot)
    output={'headline':'Python reporting','headline_evidence':[{'record_id':'project','quote':original}], 'entries':[{'record_id':'project','items':[{'item_id':'one','text':rewrite}]}],'keywords':[{'term':'Python','job_quote':'Python reporting','evidence':[{'record_id':'project','quote':rewrite}]}]}
    optimization.validate(copy.deepcopy(output),snapshot,records)
    for evidence in ({'record_id':'foreign','quote':original},{'record_id':'project','quote':'Built Azure billing systems.'},{'record_id':'project','quote':original+' Operations analysis'}):
        bad=copy.deepcopy(output);bad['headline_evidence']=[evidence]
        with pytest.raises(ServiceError,match='source could not be verified'):optimization.validate(bad,snapshot,records)
    other={**entry,'source_id':'other','bullets':['Managed suppliers.'],'source_original_bullets':['Managed suppliers.'],'content_items':[{**item,'original':'Managed suppliers.','text':'Managed suppliers.'}]}
    snapshot['sections'][0]['entries'].append(other)
    bad=copy.deepcopy(output);bad['headline_evidence']=[{'record_id':'other','quote':original}]
    with pytest.raises(ServiceError,match='source could not be verified'):optimization.validate(bad,snapshot,optimization.evidence_sources(snapshot))


@pytest.mark.parametrize('expected', [False, True])
def test_date_citations_reach_independent_audit_from_confirmed_headers(client,account,monkeypatch,expected):
    job,rows,body=setup(client,account)
    education=rows[0]
    dates={'start_date':'September 2019','end_date':'' if expected else 'June 2023','expected_graduation':'June 2028' if expected else ''}
    result=client.put('/api/experience/'+education['id'],json={**education['data'],**dates})
    assert result.status_code==200,result.text
    quote='Expected graduation June 2028' if expected else 'September 2019 – June 2023'
    def mutate(draft):
        draft['entries'][0]['reason']='Relevant education: '+quote
        draft['keywords'][0]['evidence']=[{'record_id':education['id'],'quote':quote}]
    def audit(payload):
        # Model boundary: a shortened catalog must fail this check, even though
        # the deterministic citation check can already see the snapshot header.
        source=next(r for r in payload['confirmed_sources'] if r['id']==education['id'])
        assert all(quote not in i['text'] for i in source['items'])
        assert source['start_date']==dates['start_date']
        assert source['end_date']==dates['end_date']
        assert source['expected_graduation']==dates['expected_graduation']
        supported=quote in source.get('dates','') and quote in source.get('details','')
        variants=payload.get('evidence_sources',{}).get(education['id'],[])
        assert any(quote in text for text in variants)
        assert all('authorized_us' not in r and 'sponsorship_now' not in r for r in payload['confirmed_sources'])
        return {'approved':supported,'issues':[] if supported else ['Degree dates are missing from the confirmed sources.']}
    calls=mock_model(monkeypatch,mutate,audit=audit)
    task=wait_task(client,client.post('/api/resumes/optimize',json=body))
    assert task['status']=='completed',task
    assert task['result']['data']['source_checked'] and len(calls)==2


@pytest.mark.parametrize('foreign_record',[False,True])
def test_header_date_citations_reject_invented_dates_and_other_records(foreign_record):
    education=resume_data.entry_snapshot({'category':'education','title':'BS Computing','organization':'Example University','start_date':'September 2019','end_date':'June 2023'},'degree',True)
    project=resume_data.entry_snapshot({'category':'project','title':'Reporting','description':'Analyzed reports using Python.'},'project',True)
    snapshot={'sections':[{'entries':[education,project]}],'posting_snapshot':{'description':'Python reporting'}}
    output={'headline':'Computing','headline_evidence':[{'record_id':'degree','quote':'BS Computing'}],'entries':[{'record_id':'degree','items':[]}],'keywords':[{'term':'Python','job_quote':'Python reporting','evidence':[{'record_id':'project' if foreign_record else 'degree','quote':'September 2019 – June 2023' if foreign_record else 'September 2019 – June 2024'}]}]}
    with pytest.raises(ServiceError,match='source could not be verified'):
        optimization.validate(output,snapshot,optimization.evidence_sources(snapshot))
