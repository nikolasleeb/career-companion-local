"""Offline checks for research budgets, accurate failure reporting and billed usage."""
import asyncio
import json
import pytest
from app import ai,career_coach as coach,cost_history,db,config,credentials
from app.network import ServiceError

@pytest.mark.parametrize('reasoning,minimum',[('low',8000),('medium',16000),('high',16000),('max',32000)])
def test_research_keeps_selected_reasoning_with_enough_output_headroom(client,account,monkeypatch,reasoning,minimum):
 db.update_settings(account['id'],{'custom_model':'gpt-6.1-sol','custom_reasoning':reasoning})
 monkeypatch.setattr(config,'ENABLE_WEB_SEARCH',True);calls=[]
 async def provider(body,**kwargs):
  calls.append(body);assert kwargs['retry_allowed'] is False
  return {'model':'mock','status':'completed','usage':{},'output':[]}
 monkeypatch.setattr(ai,'call_api',provider)
 async def run():
  token=ai.set_user_context(account['id'])
  try:return await coach.research(account['id'],{'id':'mock-chat','data':{'goal':''}},coach.profile(account['id']),'budget-token','custom',public_topics=['research methods'])
  finally:ai.reset_user_context(token)
 asyncio.run(run());assert len(calls)==1
 assert calls[0]['reasoning']['effort']==reasoning and calls[0]['max_output_tokens']>=minimum and calls[0]['max_tool_calls']==4
 assert db.settings(account['id'])['custom_reasoning']==reasoning

def test_incomplete_stop_reason_and_budget_are_retained_without_prompts(client,account):
 body={'model':'gpt-6.1-sol','max_output_tokens':16000,'input':'PRIVATE PROMPT MUST NOT BE STORED','tools':[{'type':'web_search'}]}
 event=cost_history.begin({'user_id':account['id'],'process':'career_coach','operation':'message'},body)
 result=cost_history.finish(account['id'],event,body,{'status':'incomplete','incomplete_details':{'reason':'max_output_tokens'},'usage':{'input_tokens':100,'output_tokens':3000,'output_tokens_details':{'reasoning_tokens':3000}},'output':[]})
 d=result['data'];assert d['incomplete_reason']=='max_output_tokens' and d['max_output_tokens']==16000 and d['step']=='message · Current web research'
 assert d['status']=='incomplete' and d['reasoning_tokens']==3000 and d['estimated_cost_usd'] is not None
 assert 'PRIVATE PROMPT' not in json.dumps(d)
 historical=cost_history.UsageEvent.model_validate({k:v for k,v in d.items() if k not in ('max_output_tokens','incomplete_reason')})
 assert historical.max_output_tokens==0 and historical.incomplete_reason==''

def test_research_failure_keeps_root_cause_and_does_not_retry(client,account,monkeypatch):
 monkeypatch.setattr(config,'ENABLE_WEB_SEARCH',True);calls=[]
 async def provider(*a,**k):calls.append(True);raise ServiceError('The AI reached its output limit before finishing. No partial result was saved.')
 monkeypatch.setattr(ai,'call_api',provider)
 result=asyncio.run(coach.research(account['id'],{'id':'mock-chat','data':{'goal':''}},coach.profile(account['id']),'failed-research','economy',public_topics=['research methods']))
 assert result['data']['status']=='unavailable' and len(calls)==1
 error=coach.research_failure(result['data']);assert 'output limit' in str(error) and 'previous results' in str(error)
