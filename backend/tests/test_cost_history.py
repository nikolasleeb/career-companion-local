"""Provider requests are mocked; these tests never spend API credit."""
import asyncio
import csv
import io
import json
from datetime import datetime,timedelta,timezone
import httpx
import pytest
from pydantic import BaseModel
from app import ai,ai_settings,cost_history as costs,credentials,db
from app.network import ServiceError

HTTP_CLIENT=httpx.AsyncClient
KEY='sk-fictional-cost-tests-only'
BODY={'model':'gpt-6.1-sol','input':'PRIVATE SOURCE','text':{'format':{'name':'ProjectAnalysisOutput'}}}


def response(identity='r1',**patch):
    return {'id':identity,'status':'completed','model':'gpt-6.1-sol','usage':{'input_tokens':1000,'input_tokens_details':{'cached_tokens':200},'output_tokens':300,'output_tokens_details':{'reasoning_tokens':100}},'output':[],**patch}


def mocked(monkeypatch,handler):
    original=HTTP_CLIENT
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))


async def request(user,body=None,process='project_analysis',task_id=''):
    token=ai.set_user_context(user,task_id=task_id,process=process)
    try:return await ai.call_api(body or BODY)
    finally:ai.reset_user_context(token)


def saved(user,**patch):
    return costs.write(user,{'event_key':'test:'+db.uid(),'occurred_at':db.now(),'model':'gpt-6.1-sol','process':'project_analysis','status':'completed','input_tokens':1000,'output_tokens':300,'usage_reported':True,'token_cost_usd':.00462,'tool_cost_usd':0,'estimated_cost_usd':.00462,**patch})


def test_metered_request_cache_reasoning_tools_and_historical_rate_snapshot(client,account,monkeypatch):
    user=account['id'];credentials.save(user,KEY)
    mocked(monkeypatch,lambda _:httpx.Response(200,json=response(output=[{'type':'web_search_call'},{'type':'web_search_call'}])))
    result=asyncio.run(request(user,{**BODY,'tools':[{'type':'web_search'}]}))
    event=costs.events(user)[0]
    assert event['input_tokens']==1000 and event['cached_input_tokens']==200
    assert event['output_tokens']==300 and event['reasoning_tokens']==100
    assert event['token_cost_usd']==pytest.approx(.00462)  # Reasoning already in the 300 output tokens.
    assert event['tool_cost_usd']==.02 and event['estimated_cost_usd']==pytest.approx(.02462)
    assert event['process']=='project_analysis' and event['step']=='Project Analysis'
    assert result['_next_step_usage_event_id']==event['id']
    serialized=json.dumps(event)
    assert KEY not in serialized and 'PRIVATE SOURCE' not in serialized
    monkeypatch.setitem(ai_settings.CATALOG,'gpt-6.1-sol',{**ai_settings.CATALOG['gpt-6.1-sol'],'input':999})
    assert costs.events(user)[0]['estimated_cost_usd']==.02462
    assert costs.events(user)[0]['rates']['input']==2


@pytest.mark.parametrize('patch,note',[
    ({'model':'unknown-model'},'Model rate'),
    ({'service_tier':'future-tier'},'service-tier'),
    ({'usage':{'input_tokens':1000,'output_tokens':300,'input_tokens_details':{'cache_write_tokens':1100}}},'Inconsistent'),
    ({'usage':None},'No token usage'),
])
def test_unpriced_components_stay_explicit(client,account,patch,note):
    user=account['id'];event=costs.begin({'user_id':user},BODY)
    costs.finish(user,event,BODY,response(**patch))
    event=costs.events(user)[0]
    assert event['partial'] and event['token_cost_usd'] is None
    assert event['estimated_cost_usd'] is None  # A known zero tool component must not imply a free response.
    assert any(note in n for n in event['notes'])
    assert costs.report(user)['totals']['unpriced_requests']==1
    assert costs.report(user)['totals']['estimated_cost_usd'] is None


@pytest.mark.parametrize('details,ttl,expected,short,long',[
    ({'cached_tokens':200,'cache_write_tokens':500},'30m',.00487,500,0),
    ({'cached_tokens':200,'cache_write_tokens':500},'12h',.00612,0,500),
    ({'cached_tokens':200,'cache_write_tokens':500,'cache_write_tokens_details':{'ttl_30m_tokens':300,'ttl_12h_tokens':200}},'30m',.00537,300,200),
    ({'cached_tokens':200,'cache_write_tokens':0},'30m',.00462,0,0),
])
def test_cache_writes_replace_input_cost_and_preserve_lifetimes(client,account,details,ttl,expected,short,long):
    user=account['id'];body={**BODY,'prompt_cache_options':{'ttl':ttl}}
    raw={'input_tokens':1000,'output_tokens':300,'input_tokens_details':details}
    event=costs.begin({'user_id':user},body)
    costs.finish(user,event,body,response(usage=raw))
    value=costs.events(user)[0]
    assert not value['partial'] and value['cache_counts_reported']
    assert value['cache_write_30m_tokens']==short and value['cache_write_12h_tokens']==long
    assert value['estimated_cost_usd']==pytest.approx(expected)
    assert ai_settings.usage_cost('gpt-6.1-sol',raw,ttl)==pytest.approx(expected)
    assert ai_settings.usage_cost('gpt-6.1-sol',value)==pytest.approx(expected)


def test_historical_cache_write_gap_recovers_a_range_once_with_frozen_rates(client,account,monkeypatch):
    user=account['id']
    saved(user,input_tokens=1000,cached_input_tokens=200,token_cost_usd=None,estimated_cost_usd=None,partial=True,rates={'input':2.,'cached_input':.1,'output':10.},notes=['Cache-write pricing is unavailable; token cost is unpriced.'])
    monkeypatch.setitem(ai_settings.CATALOG,'gpt-6.1-sol',{**ai_settings.CATALOG['gpt-6.1-sol'],'input':999})
    value=costs.events(user)[0]
    assert value['estimated_cost_usd']==.00462 and value['estimated_cost_upper_usd']==.00502
    assert value['partial'] and not value['cache_counts_reported'] and 'not retained' in value['notes'][0]
    first=db.list_entities(user,'usage_event')[0]['updated_at']
    report=costs.report(user);assert report['totals']['estimated_cost_upper_usd']==.00502
    assert len(report['events'])==1 and db.list_entities(user,'usage_event')[0]['updated_at']==first
    assert report['by_model'][0]['estimated_cost_usd']==.00462
    saved(user,estimated_cost_usd=None,token_cost_usd=None,partial=True,notes=['Unknown model'])
    assert costs.report(user)['totals']['estimated_cost_upper_usd'] is None


@pytest.mark.parametrize('status', ['incomplete','failed'])
def test_failed_or_incomplete_response_still_records_billed_tokens(client,account,monkeypatch,status):
    user=account['id'];credentials.save(user,KEY)
    mocked(monkeypatch,lambda _:httpx.Response(200,json=response(status=status)))
    with pytest.raises(ServiceError):asyncio.run(request(user))
    event=costs.events(user)[0]
    assert event['status']==status and event['estimated_cost_usd']==.00462


def test_contract_failure_is_recorded_before_validation(client,account,monkeypatch):
    user=account['id'];credentials.save(user,KEY)
    mocked(monkeypatch,lambda _:httpx.Response(200,json=response(output=[{'type':'message','content':[{'type':'output_text','text':'{"wrong": true}'}]}])))
    class Expected(BaseModel):answer:str
    async def run():
        token=ai.set_user_context(user,process='cover_letter')
        try:
            with pytest.raises(ServiceError,match='output contract'):await ai.structured(Expected,{'private':'content'})
        finally:ai.reset_user_context(token)
    asyncio.run(run())
    event=costs.events(user)[0]
    assert event['estimated_cost_usd']==.00462 and event['process']=='cover_letter'


def test_retry_attempts_each_logged_and_timeout_is_unknown_without_retry(client,account,monkeypatch):
    user=account['id'];credentials.save(user,KEY);calls=[]
    def handler(req):
        calls.append(req)
        return httpx.Response(500,json={'error':{'code':'server_error'}},headers={'retry-after':'0'}) if len(calls)==1 else httpx.Response(200,json=response())
    mocked(monkeypatch,handler)
    asyncio.run(request(user))
    events=costs.events(user)
    assert len(calls)==len(events)==2
    assert {e['status'] for e in events}=={'failed','completed'}
    assert costs.report(user)['totals']['unpriced_requests']==1
    def timeout(req):calls.append(req);raise httpx.ReadTimeout('fixture timeout',request=req)
    mocked(monkeypatch,timeout)
    with pytest.raises(ServiceError,match='timed out'):asyncio.run(request(user))
    assert len(calls)==3 and costs.events(user)[0]['status']=='unknown'


def test_no_key_no_charge_ledger_and_concurrent_account_requests_are_scoped(client,account,monkeypatch):
    user=account['id']
    with pytest.raises(ServiceError):asyncio.run(request(user))
    assert not costs.events(user)
    other=client.post('/api/auth/register',json={'username':'other-cost','password':'fictional-password'}).json()
    client.headers['X-CSRF-Token']=other['csrf']
    for u in (user,other['id']):credentials.save(u,KEY)
    async def handler(req):
        await asyncio.sleep(0)
        body=json.loads(req.content)
        return httpx.Response(200,json=response(identity=body['input']))
    mocked(monkeypatch,handler)
    async def both():return await asyncio.gather(request(user,{**BODY,'input':'first'},'analysis'),request(other['id'],{**BODY,'input':'second'},'story_prompts'))
    asyncio.run(both())
    assert [e['process'] for e in costs.events(user)]==['analysis']
    assert [e['process'] for e in costs.events(other['id'])]==['story_prompts']
    assert client.get('/api/usage').json()['totals']['requests']==1
    client.post('/api/auth/logout')
    assert client.get('/api/usage').status_code==401
    assert client.get('/api/usage/export').status_code==401


def legacy(stamp=None):
    return {'model':'gpt-6.1-sol','generated_at':stamp or db.now(),'usage':{'input_tokens':120,'cached_input_tokens':10,'output_tokens':30,'reasoning_tokens':10},'estimated_token_cost_usd':.123456,'pricing_date':'2026-10-20'}


def test_recover_deduplicates_saved_copies_preserves_original_cost_and_process(client,account):
    user=account['id'];meta=legacy();now=datetime.now(timezone.utc)
    task=db.uid()
    with db.connect() as c:
        c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',(task,user,'project_analysis','completed',json.dumps({'data':{'ai':meta}}),None,(now-timedelta(minutes=1)).isoformat(),(now+timedelta(minutes=1)).isoformat()))
        # A later document revision carries a copy of the old metadata; it is not a new call.
        c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',(db.uid(),user,'resume_guided','completed',json.dumps({'copied':meta}),None,(now+timedelta(days=1)).isoformat(),(now+timedelta(days=1,minutes=1)).isoformat()))
    db.save(user,'project_analysis',{'ai':meta,'actual_cost_usd':999})
    db.save(user,'resume',{'ai':meta,'illustrative_estimate':{'usd':900},'profile':{'ai':legacy('2020-01-01T00:00:00Z')}})
    for _ in range(2):
        report=costs.report(user)
        assert report['totals']['requests']==1 and report['totals']['estimated_cost_usd']==.123456
        assert report['events'][0]['task_id']==task and report['events'][0]['process']=='project_analysis'
        assert report['events'][0]['partial'] and report['events'][0]['origin']=='recovered'


def test_new_metadata_link_prevents_backfill_duplicate(client,account,monkeypatch):
    user=account['id'];credentials.save(user,KEY)
    mocked(monkeypatch,lambda _:httpx.Response(200,json=response()))
    result=asyncio.run(request(user))
    token=ai.set_user_context(user)
    try:meta=ai.metadata(result,'economy')
    finally:ai.reset_user_context(token)
    db.save(user,'project_analysis',{'ai':meta})
    assert len(costs.events(user))==1
    assert costs.events(user)[0]['metadata_key']==costs.metadata_key(meta)


def test_pending_request_after_restart_is_unknown_and_filters_use_local_calendar(client,account):
    user=account['id']
    pending=saved(user,status='pending',occurred_at='2026-10-20T06:59:00Z',estimated_cost_usd=None,token_cost_usd=None,tool_cost_usd=None)
    saved(user,occurred_at='2026-10-20T07:01:00Z',process='analysis',model='gpt-6-luna')
    report=costs.report(user,start='2026-10-19',end='2026-10-19',tz='America/Phoenix')
    assert report['totals']['requests']==1 and report['events'][0]['id']==pending['id']
    assert report['events'][0]['status']=='unknown' and report['series'][0]['key']=='2026-10-19'
    assert costs.report(user,tz='UTC',bucket='month')['series'][0]['key']=='2026-10'
    filtered=costs.report(user,model='gpt-6-luna',process='analysis',limit=1,offset=0)
    assert filtered['totals']['requests']==1 and filtered['events'][0]['model']=='gpt-6-luna'
    for query in ('?start=2026-12-01&end=2026-01-01','?tz=bad/zone','?offset=-1','?limit=1000'):
        assert client.get('/api/usage'+query).status_code==422


def test_csv_escapes_formula_strings_and_pagination_does_not_change_totals(client,account,monkeypatch):
    user=account['id']
    for i in range(35):saved(user,step='=HYPERLINK("evil")' if i==0 else 'Review',process='analysis')
    async def forbidden(*_):raise AssertionError('History must never call AI')
    monkeypatch.setattr(ai,'call_api',forbidden)
    page=client.get('/api/usage?offset=30&limit=30').json()
    assert len(page['events'])==5 and page['totals']['requests']==35
    export=client.get('/api/usage/export?process=analysis')
    rows=list(csv.DictReader(io.StringIO(export.text)))
    assert len(rows)==35 and any(r['step'].startswith("'=HYPERLINK") for r in rows)
    assert all('input' not in r or r['input']!='PRIVATE SOURCE' for r in rows)


def test_usage_backup_remaps_metadata_references_and_additive_restore_is_idempotent(client,account):
    user=account['id'];event=saved(user,event_key='response:backup')
    # Use a simple supported record with a nested per-call AI reference.
    db.save(user,'analysis',{'ai':{**legacy(),'usage_event_id':event['id']}})
    payload=client.get('/api/account/export').json()
    assert len([r for r in payload['records'] if r['kind']=='usage_event'])==1
    second=client.post('/api/auth/register',json={'username':'restore-cost','password':'fictional-password'}).json()
    client.headers['X-CSRF-Token']=second['csrf']
    for _ in range(2):
        result=client.post('/api/account/import',files={'file':('backup.json',json.dumps(payload),'application/json')})
        assert result.status_code==200,result.text
        assert client.get('/api/usage').json()['totals']['requests']==1
    restored=db.list_entities(second['id'],'usage_event')[0]
    assert restored['id']!=event['id']
    assert all(r['data']['ai']['usage_event_id']==restored['id'] for r in db.list_entities(second['id'],'analysis'))
    assert client.delete('/api/records/'+restored['id']).status_code==409
    assert client.request('DELETE','/api/account',json={'username':'restore-cost','password':'fictional-password'}).status_code==200
    assert not db.list_entities(second['id'],'usage_event') and len(costs.events(user))==1


def test_history_available_before_onboarding_without_api_key(client):
    user=client.post('/api/auth/register',json={'username':'fresh-cost','password':'fictional-password'}).json()
    client.headers['X-CSRF-Token']=user['csrf']
    assert not client.get('/api/me').json()['onboarding']['completed']
    assert client.get('/api/usage').json()['totals']['requests']==0
    assert client.get('/api/usage/export').status_code==200


def test_task_context_records_multiple_calls_and_survives_later_failure(client,account,monkeypatch):
    from app.main import run_task
    user=account['id'];credentials.save(user,KEY);task=db.uid();calls=[]
    def handler(req):
        calls.append(req);return httpx.Response(200,json=response(identity='task-'+str(len(calls))))
    mocked(monkeypatch,handler)
    with db.connect() as c:
        c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',(task,user,'resume_guided','queued',json.dumps({'inputs':{'operation':'review'}}),None,db.now(),db.now()))
    async def work():
        for _ in range(2):await ai.call_api(BODY)
        raise ServiceError('Later document validation failed')
    asyncio.run(run_task(task,user,work))
    events=costs.events(user)
    assert len(events)==2 and all(e['task_id']==task and e['process']=='resume_guided' and e['task_status']=='failed' for e in events)
    assert costs.report(user)['totals']['estimated_cost_usd']==.00924
    assert all(e['step'].startswith('review') for e in events)


def test_cancelled_request_is_retained_as_unknown(client,account,monkeypatch):
    user=account['id'];credentials.save(user,KEY)
    async def cancelled(_):raise asyncio.CancelledError()
    mocked(monkeypatch,cancelled)
    with pytest.raises(asyncio.CancelledError):asyncio.run(request(user))
    assert costs.events(user)[0]['status']=='unknown'


def test_bad_usage_and_additional_tools_do_not_create_false_free_totals(client,account):
    user=account['id']
    body={**BODY,'tools':[{'type':'web_search'}]}
    event=costs.begin({'user_id':user},body)
    costs.finish(user,event,body,response(output=None))
    row=costs.events(user)[0]
    assert row['tool_cost_usd'] is None and row['partial'] and row['estimated_cost_usd']==.00462
    event=costs.begin({'user_id':user},BODY)
    costs.finish(user,event,BODY,response(identity='extra',output=[{'type':'code_interpreter_call'}]))
    assert costs.events(user)[0]['tool_cost_usd'] is None
    event=costs.begin({'user_id':user},BODY)
    costs.finish(user,event,BODY,response(identity='malformed',usage={'input_tokens':'bad','output_tokens':None}))
    assert costs.events(user)[0]['estimated_cost_usd'] is None
