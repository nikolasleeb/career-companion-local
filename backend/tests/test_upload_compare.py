import copy
import io
import json
from pathlib import Path
import base64
import httpx
import pytest
from reportlab.pdfgen import canvas
from app import ai, config, db, documents, job_parser, posting_extraction, comparison, role_alignment
from app.network import ServiceError
from test_app import wait

HTTP_CLIENT=httpx.AsyncClient


TEXT = '''Junior Data Analyst
Example Company
Requirements
SQL and Python.
Responsibilities
Build reports.
Location: Seattle, WA
Hours: Full time, 40 hours per week
Benefits include health insurance.
'''


def pdf_document():
    stream=io.BytesIO();pdf=canvas.Canvas(stream)
    for i,line in enumerate(TEXT.splitlines()):pdf.drawString(40,750-i*20,line)
    pdf.save();return stream.getvalue()


def extracted_fixture(payload):
    sources=payload['source_catalog']
    def sourced(text,needle):
        return {'text':text,'source_ids':[next(r['id'] for r in sources if needle in r['text'])]}
    empty={'text':'','source_ids':[]}
    return {'title':sourced('Junior Data Analyst','Junior Data Analyst'),
            'company':sourced('Example Company','Example Company'),
            'facts':{k:sourced('Seattle, WA','Location:') if k=='location' else sourced('Full time, 40 hours per week','Hours:') if k=='schedule' else copy.deepcopy(empty) for k in posting_extraction.FACTS},
            'summary':[], 'criteria':[
                {**sourced('SQL and Python.','SQL and Python.'),'group':'required'},
                {**sourced('Build reports.','Build reports.'),'group':'responsibilities'}]}


@pytest.fixture
def profile(client,account,monkeypatch):
    monkeypatch.setattr(config,'OPENAI_KEY','fictional-key-never-sent')
    return client.post('/api/experience',json={'title':'Profile-only project','description':'My confirmed SQL project.','confirmed':True}).json()


def provider(monkeypatch,extract=extracted_fixture,fail_stage='',tamper=None):
    original=HTTP_CLIENT;calls=[]
    def handler(request):
        body=json.loads(request.content);calls.append(body)
        name=body['text']['format']['name']
        raw=body['input']
        payload=json.loads(raw[0]['content'][0]['text'] if isinstance(raw,list) else raw)
        if name==fail_stage:
            return httpx.Response(503,json={'error':{'code':'server_is_overloaded'}},headers={'Retry-After':'45'})
        if name=='PostingExtractionOutput':
            assert 'Profile-only project' not in json.dumps(payload)
            value=extract(payload)
            if tamper:tamper(value)
        else:
            assert name=='CatalogComparisonOutput'
            value={'summary':'Compared the saved posting.','requirements':[], 'duty_assessments':[],
                   'job_details':[], 'recommendations':[], 'suggestions':[], 'keywords':[], 'questions':[]}
            for field,key in [('requirements','criterion_catalog'),('duty_assessments','duty_catalog')]:
                value[field]=[{'criterion_id':r['id'],'status':'unknown','evidence':[],
                               'explanation':'Needs more information.','question':'','project_context_ids':[]} for r in payload[key]]
        return httpx.Response(200,json={'status':'completed','model':body['model'],
            'usage':{'input_tokens':100,'output_tokens':50,'total_tokens':150},
            'output':[{'content':[{'type':'output_text','text':json.dumps(value)}]}]})
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    return calls


def start(client,raw=None,token='upload-comparison-fixture',filename='posting.pdf',mode='economy'):
    return client.post('/api/analyses/from-document',data={'request_token':token,'mode':mode},
                       files={'file':(filename,raw if raw is not None else pdf_document())})


def finished(client,response):
    assert response.status_code==200,response.text
    return wait(client,response.json()['task_id'])


def test_original_pdf_extracts_then_compares_with_shared_catalog_and_two_usage_events(client,account,profile,monkeypatch):
    calls=provider(monkeypatch);raw=pdf_document()
    response=start(client,raw);result=finished(client,response)
    assert result['status']=='completed',result
    assert [c['text']['format']['name'] for c in calls]==['PostingExtractionOutput','CatalogComparisonOutput']
    file=calls[0]['input'][0]['content'][1]
    assert file['detail']=='high' and base64.b64decode(file['file_data'].split(',',1)[1])==raw
    assert all(c['store'] is False for c in calls)
    analysis=result['result'];job=db.get(account['id'],analysis['data']['job_id'],'job')
    overview=client.get('/api/jobs/'+job['id']+'/overview').json()
    assert overview['company']=='Example Company' and overview['facts']['location']['value']=='Seattle, WA'
    assert analysis['data']['posting_snapshot']['structured_posting']==job['data']['structured_posting']
    assert {r['criterion_id'] for r in analysis['data']['requirements']}=={r['id'] for r in job_parser.criteria(job['data'])}
    assert {r['criterion_id'] for r in analysis['data']['duty_assessments']}=={r['id'] for r in role_alignment.catalog(job['data'])}
    assert analysis['data']['score']['groups']['required']['total']==1
    assert analysis['data']['posting_hash']==overview['catalog_hash']
    assert overview['catalog_hash']!=overview['text_hash']
    assert result['job_id']==job['id']
    labels=[r['label'] for r in result['progress']['history']]+[result['progress']['label']]
    assert labels[-3:]==['Reading job posting','Comparing with your Profile','Saving results']
    events=db.list_entities(account['id'],'usage_event');assert len(events)==2
    assert all(e['data']['status']=='completed' and e['data']['input_tokens']==100 for e in events)
    assert 'file_data' not in json.dumps(events) and 'My confirmed SQL project' not in json.dumps(events)
    assert not list((config.DATA_DIR/'uploads').glob('**/*'))
    recovered=client.get('/api/analyses/from-document/status?request_token=upload-comparison-fixture').json()
    assert recovered['task_id']==response.json()['task_id']
    repeated=start(client,raw);assert repeated.json()['task_id']==response.json()['task_id'] and len(calls)==2
    assert start(client,raw,mode='deep').status_code==409
    assert start(client,pdf_document()+b'changed').status_code==409
    # Cached extraction survives reruns, including a different comparison mode.
    again=finished(client,client.post('/api/analyses',json={'job_id':job['id'],'mode':'deep'}))
    assert again['status']=='completed' and len(calls)==3
    assert calls[-1]['text']['format']['name']=='CatalogComparisonOutput'


def test_extraction_failure_preserves_previous_results_and_never_compares(client,account,profile,monkeypatch):
    previous=db.save(account['id'],'analysis',{'summary':'Previous reviewed result'})
    calls=provider(monkeypatch,fail_stage='PostingExtractionOutput')
    result=finished(client,start(client))
    assert result['status']=='failed' and len(calls)==1
    assert db.list_entities(account['id'],'job')==[]
    assert db.get(account['id'],previous['id'],'analysis')==previous


def test_comparison_failure_keeps_extraction_and_retry_does_not_parse_again(client,account,profile,monkeypatch):
    calls=provider(monkeypatch,fail_stage='CatalogComparisonOutput')
    raw=pdf_document();response=start(client,raw);result=finished(client,response)
    assert result['status']=='failed' and len(calls)==2
    job=db.list_entities(account['id'],'job')[0]
    assert result['job_id']==job['id'] and posting_extraction.cached(job['data'])
    assert start(client,raw).json()['task_id']==response.json()['task_id']
    retry_calls=provider(monkeypatch)
    result=finished(client,client.post('/api/analyses',json={'job_id':job['id'],'request_token':'retry-only-comparison'}))
    assert result['status']=='completed' and len(retry_calls)==1
    assert retry_calls[0]['text']['format']['name']=='CatalogComparisonOutput'


def test_invalid_extraction_references_fail_before_saving_or_comparing(client,account,profile,monkeypatch):
    calls=provider(monkeypatch,tamper=lambda v:v['criteria'][0].update(source_ids=['foreign-line']))
    result=finished(client,start(client))
    assert result['status']=='failed' and 'traced' in result['error'] and len(calls)==1
    assert db.list_entities(account['id'],'job')==[] and db.list_entities(account['id'],'analysis')==[]


def test_source_changes_invalidate_extraction_but_identity_edits_preserve_it(client,account,profile,monkeypatch):
    provider(monkeypatch);result=finished(client,start(client));job=db.get(account['id'],result['job_id'],'job')
    data={k:job['data'][k] for k in ('title','company','description','url')}
    renamed=client.put('/api/jobs/'+job['id'],json={**data,'title':'Corrected title'}).json()
    assert posting_extraction.cached(renamed['data'])['title']=='Corrected title'
    changed=client.put('/api/jobs/'+job['id'],json={**data,'description':TEXT+'New required qualification: R.'}).json()
    assert posting_extraction.cached(changed['data']) is None and 'structured_posting' not in changed['data']
    calls=provider(monkeypatch)
    result=finished(client,client.post('/api/analyses',json={'job_id':job['id']}))
    assert result['status']=='completed' and len(calls)==2


def test_text_upload_and_legacy_postings_are_extracted_without_file_images(client,account,profile,monkeypatch):
    calls=provider(monkeypatch)
    result=finished(client,start(client,TEXT.encode(),filename='posting.txt'))
    assert result['status']=='completed' and isinstance(calls[0]['input'],str)
    legacy=client.post('/api/jobs',json={'title':'Old title','description':TEXT}).json()
    result=finished(client,client.post('/api/analyses',json={'job_id':legacy['id']}))
    assert result['status']=='completed' and len(calls)==4


def test_upload_limits_authentication_and_account_isolation(client,account,profile,monkeypatch):
    assert start(client,b'broken').status_code==400
    assert start(client,b'unsupported',filename='job.exe').status_code==400
    assert start(client,token='short').status_code==422
    assert client.post('/api/analyses/from-document',headers={'Content-Length':str(52*1024*1024)}).status_code==413
    provider(monkeypatch);response=start(client);task=finished(client,response)
    client.post('/api/auth/logout')
    assert start(client).status_code==401
    other=client.post('/api/auth/register',json={'username':'other-upload','password':'fictional-password'}).json()
    client.headers['X-CSRF-Token']=other['csrf']
    from conftest import onboard_test_account
    onboard_test_account(other)
    assert client.get('/api/tasks/'+response.json()['task_id']).status_code==404
    assert client.get('/api/jobs/'+task['job_id']+'/overview').status_code==404
    assert client.get('/api/analyses/from-document/status?request_token=upload-comparison-fixture').status_code==404


def test_nonadjacent_source_fragments_are_preserved_and_cannot_be_forged():
    text=TEXT.replace('SQL and Python.','Experience with big data:\nHiring team navigation\nprocessing, filtering, and\npresenting millions of rows.')
    payload={'source_catalog':posting_extraction.source_catalog(text)}
    empty={'text':'','source_ids':[]}
    ids=[r['id'] for r in payload['source_catalog'] if any(v in r['text'] for v in ('Experience with big data','processing, filtering','presenting millions'))]
    output={'title':{'text':'Junior Data Analyst','source_ids':['line:1']},'company':{'text':'Example Company','source_ids':['line:2']},'facts':{k:empty for k in posting_extraction.FACTS},'summary':[],
            'criteria':[{'text':'Experience processing, filtering, and presenting millions of rows.','source_ids':ids,'group':'required'}]}
    overview=posting_extraction.assemble(output,text,{})
    job={'description':text,'structured_posting':overview}
    catalog=comparison.posting_catalogs(job)['requirements']
    assert len(catalog)==1 and 'Hiring team' not in catalog[0]['source']
    assert posting_extraction.source_quote_valid(catalog[0]['source'],job)
    assert not posting_extraction.source_quote_valid(catalog[0]['source']+' invented',job)
    assert job_parser.organize(job)['sections']['responsibilities']==[]
    assert role_alignment.catalog(job)==[]


def test_changed_extraction_invalidates_an_old_comparison_even_when_source_text_is_unchanged():
    payload={'source_catalog':posting_extraction.source_catalog(TEXT)}
    output=extracted_fixture(payload)
    first=posting_extraction.assemble(output,TEXT,{})
    output['criteria'][0]['group']='preferred'
    second=posting_extraction.assemble(output,TEXT,{})
    assert first['text_hash']==second['text_hash']
    assert job_parser.posting_hash({'description':TEXT,'structured_posting':first})!=job_parser.posting_hash({'description':TEXT,'structured_posting':second})
    assert job_parser.posting_hash({'description':TEXT,'structured_posting':first})!=job_parser.posting_hash({'description':TEXT})


AMAZON=Path(__import__('os').environ.get('CAREER_POSTING_FIXTURE','/nonexistent/optional-posting.pdf'))


@pytest.mark.skipif(not AMAZON.exists(),reason='User-provided PDF is available only on the task host')
def test_amazon_original_pdf_regression(client,account,profile,monkeypatch):
    def amazon(payload):
        rows=payload['source_catalog']
        def value(text,*needles):
            return {'text':text,'source_ids':list(dict.fromkeys(next(r['id'] for r in rows if needle in r['text']) for needle in needles))}
        empty={'text':'','source_ids':[]}
        return {'title':value('2027 Data Science Internship - United States, PhD or Masters Student','2027 Data Science','Internship -','PhD or Masters'),
                'company':value('Amazon','Student, Amazon'),
                'facts':{k:value('Seattle, WA, USA','WA, USA') if k=='location' else value('Full time, 40 hours per week','(40 hours per week)') if k=='schedule' else empty for k in posting_extraction.FACTS},
                'summary':[], 'criteria':[
                    {**value('Experience processing, filtering, and presenting large quantities (100K to millions of rows) of data.','Experience with big data:','processing,','presenting large quantities'),'group':'required'},
                    {**value('Experience with clustered data processing (Hadoop, Spark, Map-reduce, and Hive).','Experience with clustered data','Map-reduce, and Hive)'),'group':'preferred'}]}
    calls=provider(monkeypatch,extract=amazon)
    result=finished(client,start(client,AMAZON.read_bytes(),filename=AMAZON.name))
    assert result['status']=='completed',result
    data=result['result']['data'];overview=data['posting_snapshot']['structured_posting']
    assert overview['company']=='Amazon' and overview['facts']['location']['value']=='Seattle, WA, USA'
    assert len(overview['sections']['required'])==len(overview['sections']['preferred'])==1
    assert 'Sao Paulo' not in json.dumps(overview['facts'])
    assert 'Hiring team' not in json.dumps(data['requirements'])
    assert len(calls)==2 and data['score']['groups']['required']['total']==1
