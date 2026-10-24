"""Speed choices, provider wiring and billing; no real provider requests."""
import asyncio
import json
import httpx
import pytest
from app import ai, ai_settings, assistant_ai, cost_history, credentials, db
from app.models import WebJobsOutput
from app.network import ServiceError


@pytest.mark.parametrize('model',list(ai_settings.CATALOG))
def test_speed_preferences_explicit_priced_and_account_private(client,account,monkeypatch,model):
    async def forbidden(*args,**kwargs):raise AssertionError('Saving must not call OpenAI')
    monkeypatch.setattr(ai,'call_api',forbidden)
    original=ai_settings.estimate(model,'high')['usd']
    for speed,multiplier in [('standard',1),('fast',2)]+([('ultrafast',6)] if model=='gpt-6.1-sol' else []):
        result=client.put('/api/settings',json={'mode':'custom','custom_model':model,'custom_reasoning':'high','custom_speed':speed})
        assert result.status_code==200,result.text
        active=client.get('/api/me').json()['capabilities']['ai']['active']
        assert active['speed']==speed and active['service_tier']==('default' if speed=='standard' else speed)
        assert active['reasoning_effort']=='high'
        assert active['estimate']['usd']==pytest.approx(original*multiplier)
    assert client.get('/api/account/export').json()['profile']['custom_speed']==speed
    db.init()
    assert db.settings(account['id'])['custom_speed']==speed
    second=client.post('/api/auth/register',json={'username':'speed-other','password':'fictional-password'}).json()
    client.headers['X-CSRF-Token']=second['csrf']
    assert client.get('/api/me').json()['capabilities']['ai']['custom_speed']=='standard'
    assert db.settings(account['id'])['custom_speed']==speed


def test_invalid_and_partial_changes_never_override_saved_speed(client,account):
    assert client.put('/api/settings',json={'custom_speed':'turbo'}).status_code==422
    assert client.put('/api/settings',json={'custom_model':'gpt-5.6-terra','custom_speed':'ultrafast'}).status_code==422
    assert client.put('/api/settings',json={'mode':'custom','custom_model':'gpt-6.1-sol','custom_reasoning':'high','custom_speed':'ultrafast'}).status_code==200
    assert client.put('/api/settings',json={'custom_model':'gpt-6-luna'}).status_code==422
    assert db.settings(account['id'])['custom_model']=='gpt-6.1-sol'
    assert ai_settings.resolve(db.settings(account['id']),'economy')['service_tier']=='default'
    assert ai_settings.resolve(db.settings(account['id']),'deep')['service_tier']=='default'
    assert client.put('/api/settings',headers={'X-CSRF-Token':'wrong'},json={'custom_speed':'standard'}).status_code==403
    assert db.settings(account['id'])['custom_speed']=='ultrafast'


@pytest.mark.parametrize('requested,returned,factor',[('fast','fast',2),('fast','priority',2),('ultrafast','ultrafast',6),('fast','default',1),('ultrafast','default',1),('fast',None,2)])
def test_provider_tier_wiring_and_returned_price_snapshot(client,account,monkeypatch,requested,returned,factor):
    credentials.save(account['id'],'sk-fictional-speed-tests')
    db.update_settings(account['id'],{'mode':'custom','custom_model':'gpt-6.1-sol','custom_reasoning':'high','custom_speed':requested})
    original=httpx.AsyncClient;calls=[]
    def handler(request):
        calls.append(json.loads(request.content))
        result={'id':'speed-fixture','model':'gpt-6.1-sol','status':'completed','usage':{'input_tokens':1000,'input_tokens_details':{'cached_tokens':200},'output_tokens':300},'output':[]}
        if returned is not None:result['service_tier']=returned
        return httpx.Response(200,json=result)
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    async def invoke():
        token=ai.set_user_context(account['id'])
        try:return await ai.web_jobs('analyst','US','custom')
        finally:ai.reset_user_context(token)
    _,meta=asyncio.run(invoke())
    assert len(calls)==1 and calls[0]['service_tier']==requested
    assert calls[0]['model']=='gpt-6.1-sol' and calls[0]['reasoning']['effort']=='high'
    event=cost_history.events(account['id'])[0]
    assert event['requested_service_tier']==requested and event['service_tier']==(returned or '')
    assert event['token_cost_usd']==pytest.approx(.00462*factor)
    assert event['rates']['input']==2*factor
    assert meta[0]['estimated_token_cost_usd']==pytest.approx(.00462*factor)
    assert event['rates']['output']==10*factor
    if returned=='default':assert any('different processing tier' in note for note in event['notes'])
    csv=client.get('/api/usage/export').text
    assert 'requested_service_tier' in csv and 'service_tier' in csv


def test_structured_call_uses_speed_and_standard_help_keeps_reserved_budget(client,account,monkeypatch):
    db.update_settings(account['id'],{'custom_model':'gpt-6.1-sol','custom_reasoning':'high','custom_speed':'ultrafast'})
    calls=[]
    async def fake(body):
        calls.append(body)
        return {'model':body['model'],'service_tier':'ultrafast','output':[{'content':[{'type':'output_text','text':'{"jobs":[]}'}]}]}
    monkeypatch.setattr(ai,'call_api',fake)
    async def invoke():
        token=ai.set_user_context(account['id'])
        try:return await ai.structured(WebJobsOutput,{'fictional':True},'custom')
        finally:ai.reset_user_context(token)
    asyncio.run(invoke())
    assert calls[0]['service_tier']=='ultrafast'
    assert assistant_ai.provider_body({'question':'fictional'})['service_tier']=='default'


@pytest.mark.parametrize('tier,factor',[('default',1),('fast',2),('priority',2),('ultrafast',6)])
def test_speed_cache_and_long_context_pricing(tier,factor):
    usage={'input_tokens':300000,'output_tokens':1000,'input_tokens_details':{'cached_tokens':10000,'cache_write_tokens':20000}}
    standard=ai_settings.usage_cost('gpt-6.1-sol',usage,cache_ttl='12h')
    assert ai_settings.usage_cost('gpt-6.1-sol-2026-10-01',usage,cache_ttl='12h',service_tier=tier)==pytest.approx(standard*factor)
    assert ai_settings.usage_cost('gpt-6-luna',usage,service_tier='ultrafast') is None


def test_speed_error_never_falls_back_or_retries_paid_request(client,account,monkeypatch):
    credentials.save(account['id'],'sk-fictional-speed-error')
    original=httpx.AsyncClient;calls=[]
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(400,json={'error':{'code':'invalid_service_tier','message':'SECRET provider details'}})
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    async def invoke():
        token=ai.set_user_context(account['id'])
        try:
            with pytest.raises(ServiceError,match='Try Standard speed') as error:
                await ai.call_api({'model':'gpt-6.1-sol','service_tier':'ultrafast'})
            assert 'SECRET' not in str(error.value)
        finally:ai.reset_user_context(token)
    asyncio.run(invoke())
    assert len(calls)==1
