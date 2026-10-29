"""Project response limits use one explicit request and preserve failed-call evidence."""
import asyncio,io,json
import httpx,pytest
from pypdf import PdfWriter
from app import ai,db,credentials,project_documents,project_sources,project_uploads
from app.network import ServiceError


def project(user,monkeypatch,pages=42):
    monkeypatch.setattr(project_documents.certificate_ocr,'extract',lambda *a,**k:{'pages':[],'incomplete':True,'warnings':[]})
    pdf=PdfWriter()
    for _ in range(pages):pdf.add_blank_page(100,100)
    out=io.BytesIO();pdf.write(out)
    source=project_uploads.preview(user,[('fictional-slides.pdf',out.getvalue())])
    snapshot=asyncio.run(project_sources.select(user,source['id'],['fictional-slides.pdf']))
    db.update_settings(user,{'mode':'custom','custom_model':'gpt-6.1-sol','custom_reasoning':'high','custom_speed':'standard'})
    credentials.save(user,'sk-fictional-project-budget-not-sent')
    return snapshot


def run(user,snapshot):
    async def action():
        token=ai.set_user_context(user,process='project_analysis')
        try:return await project_sources.analyze(user,snapshot['id'],'custom')
        finally:ai.reset_user_context(token)
    return asyncio.run(action())


def test_large_project_sends_compact_schema_with_response_headroom_once(client,account,monkeypatch):
    user=account['id'];snapshot=project(user,monkeypatch);calls=[];client_class=httpx.AsyncClient
    def handler(request):
        body=json.loads(request.content);calls.append(body)
        assert body['model']=='gpt-6.1-sol' and body['reasoning']=={'effort':'high'}
        assert body['max_output_tokens']==64000 and body['store'] is False
        assert body['text']['format']['schema']['properties']['findings']['maxItems']==8
        content=body['input'][0]['content'];assert any(v['type']=='input_file' for v in content)
        payload=json.loads(content[0]['text']);assert 'shortest useful exact excerpt' in payload['task']
        result={'summary':'A fictional visual project.','findings':[{'file_path':'fictional-slides.pdf','quote':'','observation':'Fictional slide deck.','evidence_kind':'visual','page':1}]}
        return httpx.Response(200,json={'status':'completed','model':body['model'],'usage':{'input_tokens':64919,'output_tokens':3000,'output_tokens_details':{'reasoning_tokens':2070}},'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(result)}]}]})
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kwargs:client_class(transport=httpx.MockTransport(handler),**kwargs))
    estimate=client.get('/api/project-snapshots/'+snapshot['id']+'/estimate?mode=custom').json()
    assert estimate['max_output_tokens']==64000 and estimate['answer_tokens']==4000
    result=run(user,snapshot);assert result['analysis']['data']['findings'][0]['requires_review'] and len(calls)==1
    assert not db.list_entities(user,'answer_draft')


@pytest.mark.parametrize('response_status',[200,503])
def test_failed_project_request_never_retries_or_replaces_previous_analysis(client,account,monkeypatch,response_status):
    user=account['id'];snapshot=project(user,monkeypatch)
    previous=db.save(user,'project_analysis',{'snapshot_id':snapshot['id'],'summary':'Existing completed findings','findings':[]})
    calls=[];client_class=httpx.AsyncClient
    def handler(request):
        body=json.loads(request.content);calls.append(body)
        if response_status==503:return httpx.Response(503,json={'error':{'code':'server_error'}},headers={'Retry-After':'0'})
        return httpx.Response(200,json={'status':'incomplete','model':body['model'],'incomplete_details':{'reason':'max_output_tokens'},'usage':{'input_tokens':64919,'output_tokens':64000,'output_tokens_details':{'reasoning_tokens':2070}},'output':[]})
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kwargs:client_class(transport=httpx.MockTransport(handler),**kwargs))
    with pytest.raises(ServiceError) as caught:run(user,snapshot)
    if response_status==200:
        message=str(caught.value);assert '64,000-token response limit' in message and 'no automatic retry' in message and 'lower reasoning' not in message
        event=db.list_entities(user,'usage_event')[0]['data']
        assert event['status']=='incomplete' and event['max_output_tokens']==64000 and event['reasoning_tokens']==2070
    assert len(calls)==1 and len(db.list_entities(user,'project_analysis'))==1
    assert db.get(user,previous['id'],'project_analysis')['data']==previous['data']
    assert db.get(user,snapshot['id'],'project_snapshot')['data']==snapshot['data']


def test_small_project_response_allowance_and_unrelated_estimates(client,account):
    snap=client.post('/api/project-sources/paste',json={'title':'Fictional project','text':'print("fictional project")'}).json()
    estimate=client.get('/api/project-snapshots/'+snap['id']+'/estimate').json()
    assert estimate['max_output_tokens']==32000
    assert 'max_output_tokens' not in client.get('/api/work-style/prompt-estimate').json()


def test_account_response_limit_overrides_project_default_and_is_exported(client,account,monkeypatch):
    user=account['id'];snapshot=project(user,monkeypatch)
    async def forbidden(*a,**k):raise AssertionError('Saving preferences must not call AI')
    monkeypatch.setattr(ai,'structured',forbidden)
    assert client.put('/api/settings',json={'ai_max_output_tokens':48000}).status_code==200
    assert client.get('/api/me').json()['settings']['ai_max_output_tokens']==48000
    assert client.get('/api/project-snapshots/'+snapshot['id']+'/estimate?mode=custom').json()['max_output_tokens']==48000
    assert client.get('/api/account/export').json()['profile']['ai_max_output_tokens']==48000
    assert client.put('/api/settings',json={'ai_max_output_tokens':0}).status_code==200
    assert client.get('/api/project-snapshots/'+snapshot['id']+'/estimate?mode=custom').json()['max_output_tokens']==64000
    for value in [-1,128001,True,1.5,'64000']:
        assert client.put('/api/settings',json={'ai_max_output_tokens':value}).status_code==422
    assert not db.list_entities(user,'usage_event')


def test_account_limit_reaches_raw_response_calls_and_does_not_cross_accounts(client,account,monkeypatch):
    user=account['id'];project(user,monkeypatch);db.update_settings(user,{'ai_max_output_tokens':48000})
    calls=[];client_class=httpx.AsyncClient
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200,json={'status':'completed','output':[]})
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kwargs:client_class(transport=httpx.MockTransport(handler),**kwargs))
    async def action(process='other'):
        token=ai.set_user_context(user,process=process)
        try:await ai.call_api({'model':'gpt-6.1-sol','max_output_tokens':512,'input':'Fictional request','store':False},retry_allowed=False)
        finally:ai.reset_user_context(token)
    asyncio.run(action());assert calls[-1]['max_output_tokens']==48000
    asyncio.run(action('openai_connection_test'));assert calls[-1]['max_output_tokens']==512
    other=client.post('/api/auth/register',json={'username':'separate-budget','password':'fictional-test-password'}).json()
    assert other['settings'].get('ai_max_output_tokens',0)==0
    from app import ai_settings
    assert ai_settings.output_limit(db.settings(other['id']),16000)==16000
