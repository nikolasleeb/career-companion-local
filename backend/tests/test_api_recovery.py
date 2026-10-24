from conftest import onboard_test_account
import asyncio
import httpx
import pytest
from app import ai, config, db, provider_errors
from app.network import ServiceError
from test_app import wait

@pytest.mark.parametrize('status,code,expected',[(401,None,'API key'),(403,None,'permissions'),(404,'model_not_found','model'),(429,'insufficient_quota','credits'),(429,'rate_limit_exceeded','rate limiting'),(503,'server_is_overloaded','temporarily unavailable'),(400,None,'reasoning level')])
def test_provider_failures_are_actionable_and_redacted(monkeypatch,status,code,expected):
    monkeypatch.setattr(config,'OPENAI_KEY','sk-fixture-secret')
    original=httpx.AsyncClient
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(status,json={'error':{'code':code,'message':'sk-fixture-secret private applicant text'}},headers={'Retry-After':'45','x-request-id':'req_fixture123'})
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    with pytest.raises(ServiceError) as e:asyncio.run(ai.call_api({'model':'fixture'}))
    assert expected in str(e.value) and 'req_fixture123' in str(e.value)
    assert 'sk-fixture-secret' not in str(e.value) and 'private applicant' not in str(e.value)
    assert len(calls)==1

@pytest.mark.parametrize('kind,phrase',[(httpx.ReadTimeout,'timed out'),(httpx.ConnectError,'connection')])
def test_transport_failure_does_not_repeat_paid_post(monkeypatch,kind,phrase):
    monkeypatch.setattr(config,'OPENAI_KEY','fixture')
    original=httpx.AsyncClient;calls=[]
    def handler(request):calls.append(request);raise kind('PRIVATE SECRET',request=request)
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    with pytest.raises(ServiceError) as e:asyncio.run(ai.call_api({}))
    assert phrase in str(e.value) and 'not automatically' in str(e.value) and 'PRIVATE' not in str(e.value)
    assert len(calls)==1


def test_transient_backoff_is_bounded_and_honors_server_delay(monkeypatch):
    monkeypatch.setattr(config,'OPENAI_KEY','fixture')
    original=httpx.AsyncClient;calls=[];delays=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(503,json={'error':{'code':'server_is_overloaded'}},headers={'Retry-After':'3'}) if len(calls)==1 else httpx.Response(200,json={'status':'completed','output':[]})
    async def pause(delay):delays.append(delay)
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    monkeypatch.setattr(ai.asyncio,'sleep',pause)
    assert asyncio.run(ai.call_api({}))['status']=='completed'
    assert len(calls)==2 and delays==[3]

@pytest.mark.parametrize('result,phrase',[(None,'unreadable'),([], 'unreadable'),({'status':'incomplete','incomplete_details':{'reason':'max_output_tokens'}},'output limit'),({'status':'failed','error':{'code':'server_error','message':'PRIVATE'}},'could not complete')])
def test_malformed_and_incomplete_responses_are_not_saved(monkeypatch,result,phrase):
    monkeypatch.setattr(config,'OPENAI_KEY','fixture');original=httpx.AsyncClient
    def handler(request):return httpx.Response(200,json=result) if result is not None else httpx.Response(200,text='<html>broken</html>')
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    with pytest.raises(ServiceError) as e:asyncio.run(ai.call_api({}))
    assert phrase in str(e.value) and 'PRIVATE' not in str(e.value)


def test_malformed_output_and_retry_metadata_are_safe():
    for value in [None,[None],[{'content':None}],[{'content':[{'type':'output_text','text':123}]}]]:
        with pytest.raises(ServiceError):ai.output_text({'output':value})
    assert provider_errors.error_code({'error':{'code':{'unsafe':True}}}) is None
    assert provider_errors.retry_delay({'retry-after':'nan'})>=2
    assert provider_errors.retry_delay({'retry-after':'Thu, 01 Jan 2099 00:00:00 GMT'})>30


def test_comparison_start_token_recovers_completed_result_without_duplicate(client,sample,account,monkeypatch):
    monkeypatch.setattr(config,'OPENAI_KEY','fixture');calls=[]
    async def analyze(*args):calls.append(args);return {'summary':'fictional completed result'}
    monkeypatch.setattr(ai,'analyze',analyze)
    body={'job_id':sample['id'],'mode':'economy','request_token':'lost-response-token'}
    started=client.post('/api/analyses',json=body).json()
    finished=wait(client,started['task_id']);assert finished['status']=='completed'
    duplicate=client.post('/api/analyses',json=body).json()
    assert duplicate['task_id']==started['task_id'] and len(calls)==1
    assert client.get('/api/tasks/'+duplicate['task_id']).json()['result']==finished['result']
    assert '_task_inputs' not in client.get('/api/tasks/'+duplicate['task_id']).text
    assert client.post('/api/analyses',json={**body,'mode':'deep'}).status_code==409
    other=client.post('/api/auth/register',json={'username':'other-recovery','password':'fictional-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
    onboard_test_account(other)
    assert client.get('/api/tasks/'+started['task_id']).status_code==404


def test_failed_comparison_keeps_previous_result_and_recovery_token(client,sample,account,monkeypatch):
    monkeypatch.setattr(config,'OPENAI_KEY','fixture')
    previous=db.save(account['id'],'analysis',{'job_id':sample['id'],'summary':'existing reviewed comparison'})
    async def fail(*args):raise ServiceError('OpenAI is temporarily unavailable. Your saved inputs remain available.')
    monkeypatch.setattr(ai,'analyze',fail)
    body={'job_id':sample['id'],'request_token':'failed-token'}
    start=client.post('/api/analyses',json=body).json();failed=wait(client,start['task_id'])
    assert failed['status']=='failed' and 'unavailable' in failed['error']
    assert client.post('/api/analyses',json=body).json()['task_id']==start['task_id']
    assert db.get(account['id'],previous['id'],'analysis')['data']['summary']=='existing reviewed comparison'
    assert len(db.list_entities(account['id'],'analysis'))==1
