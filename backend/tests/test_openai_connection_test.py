import asyncio,json,time
import pytest
from app import ai,db,credentials,openai_connection_test as key_test

def wait(client,identity):
 for _ in range(150):
  r=client.get('/api/tasks/'+identity).json()
  if r['status'] not in ('queued','running','cancelling'):return r
  time.sleep(.01)
 raise AssertionError('task did not finish')
def start(client,token='fictional_test_token'):
 estimate=client.get('/api/settings/openai-key/test/estimate').json()
 r=client.post('/api/settings/openai-key/test',json={'request_token':token,'expected_model':estimate['model']});assert r.status_code==200,r.text;return r.json()['task_id']
def metadata(client):return next(r for r in client.get('/api/settings/api-connections').json()['providers'] if r['id']=='openai')

def test_one_bounded_paid_request_costs_dedupe_and_no_profile(client,account,monkeypatch):
 import httpx
 u=account['id'];credentials.save(u,'sk-fictional-test-only');db.update_settings(u,{'name':'PRIVATE_PROFILE_SENTINEL','custom_reasoning':'high'})
 calls=[]
 async def post(self,url,**kw):
  calls.append((url,kw));return httpx.Response(200,json={'id':'resp_fictional','model':kw['json']['model'],'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'OK'}]}],'usage':{'input_tokens':20,'output_tokens':2,'total_tokens':22}},request=httpx.Request('POST',url))
 monkeypatch.setattr(httpx.AsyncClient,'post',post)
 before=db.settings(u);assert metadata(client)['status']=='saved_not_tested';assert not calls
 task=start(client);assert wait(client,task)['status']=='completed';assert start(client)==task;assert len(calls)==1
 body=calls[0][1]['json'];assert body['input']=='Reply with exactly OK.' and body['max_output_tokens']==512 and body['service_tier']=='default' and body['store'] is False
 assert body['reasoning']['effort']==key_test.options(u)['reasoning_effort'];assert 'tools' not in body and 'PRIVATE_PROFILE_SENTINEL' not in json.dumps(body)
 assert db.settings(u)==before
 events=db.list_entities(u,'usage_event');assert len(events)==1 and events[0]['data']['process']=='openai_connection_test' and events[0]['data']['input_tokens']==20
 m=metadata(client);assert m['status']=='tested_successfully' and m['tested_at'] and m['tested_model']==body['model'];assert 'sk-fictional' not in json.dumps(m)
 credentials.save(u,'sk-fictional-replacement');assert metadata(client)['status']=='saved_not_tested'
 assert client.post('/api/settings/openai-key/test',json={'request_token':'fictional_test_token','expected_model':body['model']}).status_code==409
 credentials.remove(u);assert metadata(client)['status']=='not_configured'

@pytest.mark.parametrize('status,code,category',[(401,'invalid_api_key','invalid_credentials'),(403,'permission_denied','model_or_permissions'),(404,'model_not_found','model_or_permissions'),(429,'insufficient_quota','billing_or_quota'),(429,'rate_limit_exceeded','rate_limited'),(503,'server_error','temporary_or_unconfirmed'),(400,'invalid_request_error','request_settings')])
def test_provider_failures_are_sanitized_and_never_retried(client,account,monkeypatch,status,code,category):
 import httpx
 credentials.save(account['id'],'sk-fictional');calls=[]
 async def post(self,url,**kw):
  calls.append(url);return httpx.Response(status,json={'error':{'code':code,'message':'SECRET_PROVIDER_MESSAGE'}},request=httpx.Request('POST',url))
 monkeypatch.setattr(httpx.AsyncClient,'post',post)
 result=wait(client,start(client));assert result['status']=='failed' and len(calls)==1
 assert 'SECRET_PROVIDER_MESSAGE' not in json.dumps(result);assert metadata(client)['failure_category']==category
 assert len(db.list_entities(account['id'],'usage_event'))==1

def test_replacement_during_test_and_cancellation_cannot_verify_new_key(client,account,monkeypatch):
 credentials.save(account['id'],'sk-old');calls=[]
 async def provider(body,**kw):
  calls.append(body);await asyncio.sleep(.2);return {'output':[{'content':[{'type':'output_text','text':'OK'}]}]}
 monkeypatch.setattr(ai,'call_api',provider);task=start(client)
 time.sleep(.03);credentials.save(account['id'],'sk-new');assert wait(client,task)['status']=='completed';assert metadata(client)['status']=='saved_not_tested'
 task=start(client,'second_test_token');assert client.post('/api/tasks/'+task+'/cancel',json={}).status_code==200
 assert wait(client,task)['status']=='cancelled';assert metadata(client)['status']!='tested_successfully'
 assert len(calls)<=2

def test_requires_saved_key_matching_model_and_is_account_scoped(client,account):
 assert client.post('/api/settings/openai-key/test',json={'request_token':'fictional_token','expected_model':'gpt-6.1-sol'}).status_code==422
 credentials.save(account['id'],'sk-fictional');assert client.post('/api/settings/openai-key/test',json={'request_token':'fictional_token','expected_model':'unavailable'}).status_code==409
 other=client.post('/api/auth/register',json={'username':'other-key-test','password':'fictional-password'}).json();client.headers['X-CSRF-Token']=other['csrf'];assert metadata(client)['status']=='not_configured'
