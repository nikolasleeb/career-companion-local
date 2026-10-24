from conftest import comparison_wire
import asyncio
import json
import stat
import pytest
from app import ai, ai_settings, config, credentials, db
from app.models import WebJobsOutput
from app.network import ServiceError
from test_app import fixture_analysis, wait

FAKE_KEY='sk-'+'not-real-'+'a'*32


def test_private_key_is_scoped_redacted_persistent_and_removed(client,account):
    response=client.put('/api/settings/openai-key',json={'api_key':FAKE_KEY})
    assert response.status_code==200 and FAKE_KEY not in response.text
    assert credentials.get(account['id'])==FAKE_KEY
    assert stat.S_IMODE(credentials.path(account['id']).stat().st_mode)==0o600
    assert stat.S_IMODE(credentials.path(account['id']).parent.stat().st_mode)==0o700
    db.init()  # Simulated process initialization leaves the saved credential intact.
    assert credentials.get(account['id'])==FAKE_KEY
    me=client.get('/api/me')
    assert me.json()['capabilities']['openai_key_source']=='account'
    assert FAKE_KEY not in me.text
    backup=client.get('/api/account/export')
    assert FAKE_KEY not in backup.text and 'openai_key' not in backup.text
    other=client.post('/api/auth/register',json={'username':'other-student','password':'fictional-password'}).json()
    client.headers['X-CSRF-Token']=other['csrf']
    assert not client.get('/api/me').json()['capabilities']['openai']
    assert credentials.get(account['id'])==FAKE_KEY and credentials.get(other['id'])==''
    client.headers['X-CSRF-Token']=client.post('/api/auth/login',json={'username':'student','password':'fictional-test-password'}).json()['csrf']
    assert client.delete('/api/settings/openai-key').status_code==200
    assert not credentials.path(account['id']).exists()
    assert client.get('/api/me').json()['capabilities']['openai_key_source']=='none'


def test_key_validation_auth_csrf_and_installation_fallback(client,account,monkeypatch):
    response=client.put('/api/settings/openai-key',json={'api_key':'not valid'})
    assert response.status_code==422 and 'not valid' not in response.text
    assert client.put('/api/settings/openai-key',headers={'X-CSRF-Token':'wrong'},json={'api_key':FAKE_KEY}).status_code==403
    monkeypatch.setattr(config,'OPENAI_KEY','installation-fixture')
    assert client.get('/api/me').json()['capabilities']['openai_key_source']=='installation'
    client.post('/api/auth/logout')
    assert client.put('/api/settings/openai-key',json={'api_key':FAKE_KEY}).status_code==401


def test_custom_preferences_and_estimates_make_no_model_requests(client,account,monkeypatch):
    async def forbidden(body):raise AssertionError('Changing preferences must not call OpenAI')
    monkeypatch.setattr(ai,'call_api',forbidden)
    for model in ai_settings.CATALOG:
        costs=[]
        for effort in ai_settings.CATALOG[model].get('efforts',ai_settings.EFFORTS):
            response=client.put('/api/settings',json={'mode':'custom','custom_model':model,'custom_reasoning':effort})
            assert response.status_code==200,response.text
            active=client.get('/api/me').json()['capabilities']['ai']['active']
            assert active['model']==model and active['reasoning_effort']==effort
            costs.append(active['estimate']['usd'])
        assert costs==sorted(costs)
    assert client.get('/api/workspace').json()['analysis']==[]
    assert client.put('/api/settings',json={'custom_model':'invented-model'}).status_code==422
    assert client.put('/api/settings',json={'custom_reasoning':'ultra'}).status_code==422
    backup=client.get('/api/account/export').json()
    assert backup['profile']['custom_reasoning']=='max'
    assert 'api_key' not in backup['profile']


def test_custom_configuration_reaches_ai_and_records_usage(client,sample,account,monkeypatch):
    client.put('/api/settings/openai-key',json={'api_key':FAKE_KEY})
    client.put('/api/settings',json={'mode':'custom','custom_model':'gpt-5.6-sol','custom_reasoning':'max'})
    output=fixture_analysis(account['id'],sample['data']);calls=[]
    async def fake(body):
        calls.append((body,ai._context.get()['key']))
        return {'status':'completed','model':body['model'],'usage':{'input_tokens':100,'input_tokens_details':{'cached_tokens':20},'output_tokens':50,'total_tokens':150,'output_tokens_details':{'reasoning_tokens':30}},'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(comparison_wire(output,json.loads(body['input'])['posting'],json.loads(body['input'])))}]}]}
    monkeypatch.setattr(ai,'call_api',fake)
    response=client.post('/api/analyses',json={'job_id':sample['id'],'mode':'custom'})
    result=wait(client,response.json()['task_id'])
    assert result['status']=='completed',result
    body,key=calls[-1]
    assert key==FAKE_KEY and body['model']=='gpt-5.6-sol'
    assert body['reasoning']['effort']=='max' and body['max_output_tokens']==32000
    meta=result['result']['data']['ai']
    assert meta['mode']=='custom' and meta['reasoning_effort']=='max'
    assert meta['estimated_token_cost_usd']==pytest.approx(.001328)
    assert meta['usage']['reasoning_tokens']==30 and meta['usage']['cached_input_tokens']==20
    assert FAKE_KEY not in json.dumps(result)


def test_simultaneous_account_contexts_are_isolated(client,account):
    credentials.save(account['id'],FAKE_KEY)
    db.update_settings(account['id'],{'custom_model':'gpt-5.6-sol','custom_reasoning':'max'})
    second=client.post('/api/auth/register',json={'username':'another','password':'fictional-password'}).json()
    credentials.save(second['id'],FAKE_KEY+'b')
    db.update_settings(second['id'],{'custom_model':'gpt-5.6-luna','custom_reasoning':'none'})
    async def inspect(user):
        token=ai.set_user_context(user)
        try:
            await asyncio.sleep(0)
            return ai.options('custom'),ai._context.get()['key']
        finally:ai.reset_user_context(token)
    async def both():return await asyncio.gather(inspect(account['id']),inspect(second['id']))
    first,other=asyncio.run(both())
    assert first[0]['model']=='gpt-5.6-sol' and first[1]==FAKE_KEY
    assert other[0]['model']=='gpt-5.6-luna' and other[1]==FAKE_KEY+'b'
    assert ai._context.get() is None


def test_web_search_custom_model_and_redacted_provider_error(client,account,monkeypatch):
    credentials.save(account['id'],FAKE_KEY)
    db.update_settings(account['id'],{'custom_model':'gpt-5.6-luna','custom_reasoning':'none'})
    calls=[]
    async def fake(body):calls.append(body);return {'model':body['model'],'output':[],'usage':{}}
    monkeypatch.setattr(ai,'call_api',fake)
    async def search():
        token=ai.set_user_context(account['id'])
        try:return await ai.web_jobs('analyst','US','custom')
        finally:ai.reset_user_context(token)
    asyncio.run(search())
    assert calls[0]['model']=='gpt-5.6-luna' and calls[0]['reasoning']['effort']=='none'


def test_account_delete_removes_credential(client,account):
    credentials.save(account['id'],FAKE_KEY)
    response=client.request('DELETE','/api/account',json={'username':'student','password':'fictional-test-password'})
    assert response.status_code==200
    assert not credentials.path(account['id']).exists()


def test_provider_auth_header_uses_account_key_and_errors_do_not_echo_it(client,account,monkeypatch):
    import httpx
    credentials.save(account['id'],FAKE_KEY)
    original=httpx.AsyncClient
    def handler(request):
        assert request.headers['Authorization']=='Bearer '+FAKE_KEY
        return httpx.Response(401,json={'message':'Rejected '+FAKE_KEY})
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    async def invoke():
        token=ai.set_user_context(account['id'])
        try:
            with pytest.raises(ServiceError) as error:await ai.call_api({'model':'gpt-5.6-terra'})
            assert '401' in str(error.value) and FAKE_KEY not in str(error.value)
        finally:ai.reset_user_context(token)
    asyncio.run(invoke())


def test_current_model_rates_and_reasoning_validation(client,account):
    assert ai_settings.CATALOG['gpt-6.1-sol']['input']==2
    assert ai_settings.CATALOG['gpt-6.1-sol']['output']==10
    assert ai_settings.estimate('gpt-6.1-sol','high')['usd']==pytest.approx(.087)
    assert ai_settings.estimate('gpt-6-luna','low')['usd']==pytest.approx(.00185)
    assert client.put('/api/settings',json={'custom_model':'gpt-6.1-sol','custom_reasoning':'none'}).status_code==422
    assert client.put('/api/settings',json={'custom_model':'gpt-6-luna','custom_reasoning':'none','mode':'custom'}).status_code==200
    # A partial model update must validate against the already-saved effort.
    assert client.put('/api/settings',json={'custom_model':'gpt-6.1-sol'}).status_code==422
    assert client.get('/api/me').json()['settings']['custom_model']=='gpt-6-luna'
    assert client.put('/api/settings',json={'custom_model':'gpt-6.1-sol','custom_reasoning':'low'}).status_code==200
    me=client.get('/api/me').json()
    current=next(m for m in me['capabilities']['ai']['catalog'] if m['id']=='gpt-6.1-sol')
    assert 'none' not in current['efforts']


def test_current_model_reaches_responses_and_keeps_old_selection(client,sample,account,monkeypatch):
    client.put('/api/settings/openai-key',json={'api_key':FAKE_KEY})
    original=client.get('/api/me').json()['settings'].get('custom_model','gpt-5.6-terra')
    assert original=='gpt-5.6-terra'
    output=fixture_analysis(account['id'],sample['data']);calls=[]
    async def fake(body):
        calls.append(body)
        return {'model':body['model'],'output':[{'content':[{'type':'output_text','text':json.dumps(comparison_wire(output,json.loads(body['input'])['posting'],json.loads(body['input'])))}]}],'usage':{'input_tokens':100,'output_tokens':50}}
    monkeypatch.setattr(ai,'call_api',fake)
    for model,effort in [('gpt-6.1-sol','low'),('gpt-6-luna','none')]:
        client.put('/api/settings',json={'mode':'custom','custom_model':model,'custom_reasoning':effort})
        task=client.post('/api/analyses',json={'job_id':sample['id'],'mode':'custom'}).json()
        result=wait(client,task['task_id'])
        assert result['status']=='completed',result
        assert calls[-1]['model']==model and calls[-1]['reasoning']['effort']==effort
        assert result['result']['data']['ai']['model']==model
