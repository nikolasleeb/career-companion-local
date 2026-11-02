"""Fictional provider tests for operation-specific generation and safe failures."""
import asyncio,copy,json
import pytest
from pydantic import ValidationError
from app import ai,career_coach as coach,career_plan_inputs as inputs,config,credentials,db
from app.network import ServiceError
from test_career_coach import reply,wait
from conftest import onboard_test_account

QUESTION='I want to learn PySpark, where do you recommend I begin and what are some resources?'

def test_plan_contract_dates_and_conversation():
    sample={'profile':{'sources':[{'id':'p','text':'Fictional Python project'}]},'retrieved_chunks':[{'chunk_id':'c','text':'Practice with small reproducible projects.'}]}
    value=reply(sample)
    for operation in ('plan','research'):
        schema,instructions=coach.generation_contract(operation)
        assert schema is coach.PlanReply and 'even if the message is phrased as a question' in instructions
        assert schema.model_json_schema()['properties']['recommendations']['minItems']==1
        with pytest.raises(ValidationError):schema.model_validate({**value,'recommendations':[]})
        with pytest.raises(ValidationError):schema.model_validate({**value,'recommendations':value['recommendations']*9})
    schema,instructions=coach.generation_contract('message')
    assert schema is coach.Reply and 'empty recommendations list is valid' in instructions
    assert schema.model_validate({**value,'recommendations':[]}).recommendations==[]
    for date in ('','2028-02-29'):
        coach.PlanReply.model_validate({**value,'recommendations':[{**value['recommendations'][0],'due_date':date}]})
    for date in ('Week 1','2026-02-29','2026-2-01','2026-13-01'):
        with pytest.raises(ValidationError):coach.PlanReply.model_validate({**value,'recommendations':[{**value['recommendations'][0],'due_date':date}]})
    for purpose in ('skills','explore','internships','graduation','career_change','certification','custom'):
        assert inputs.PlanInput(purpose=purpose,objective=QUESTION).purpose==purpose

@pytest.mark.parametrize('operation',['message','plan'])
def test_same_question_rebuilt_profile_followup_and_revisions(client,account,monkeypatch,operation):
    credentials.save(account['id'],'sk-fictional-never-sent');monkeypatch.setattr(config,'ENABLE_WEB_SEARCH',False)
    # Replace legacy setup with a newly built confirmed record.
    for item in db.list_entities(account['id'],'experience'):db.delete(account['id'],item['id'])
    onboard_test_account(account);calls=[]
    async def model(schema,payload,*args,**kw):
        calls.append((schema,copy.deepcopy(payload),kw));value=reply(payload)
        if schema is coach.Reply:value['recommendations']=[]
        return schema.model_validate(value).model_dump(),{'model':'simulated'}
    monkeypatch.setattr(ai,'structured',model)
    def action(chat,op,text,**extra):
        response=client.post('/api/career-coach/chats/'+chat+'/actions',json={'operation':op,'text':text,'request_token':db.uid(),**extra});assert response.status_code==200,response.text
        result=wait(client,response.json());assert result['status']=='completed',result;return result['result']
    first=action('new',operation,QUESTION,plan_input={'purpose':'skills','objective':QUESTION})
    assert bool(first['data']['reply']['recommendations'])==(operation=='plan')
    assert calls[0][0] is (coach.PlanReply if operation=='plan' else coach.Reply)
    assert calls[0][1]['profile']['sources'] and not calls[0][2]['retry_allowed']
    chat=first['data']['chat_id'];ref={}
    assert not db.list_entities(account['id'],'coach_plan')
    if operation=='plan':
        saved=client.post('/api/career-coach/chats/'+chat+'/roadmap',json={'message_id':first['id']});assert saved.status_code==200,saved.text;ref={'plan_ref':{'plan_id':saved.json()['id']}}
    follow=action(chat,'message','Could you explain the first exercise?',**ref)
    assert not follow['data']['reply']['recommendations'] and calls[-1][0] is coach.Reply
    revised=action(chat,'plan','Can this fit two hours a week?',**ref)
    assert revised['data']['reply']['recommendations'] and calls[-1][0] is coach.PlanReply
    assert len(db.list_entities(account['id'],'coach_plan'))==(1 if operation=='plan' else 0)


@pytest.mark.parametrize('operation', ['message','plan'])
def test_research_followup_keeps_operation_contract(client,account,monkeypatch,operation):
    credentials.save(account['id'],'sk-fictional-never-sent');monkeypatch.setattr(config,'ENABLE_WEB_SEARCH',False);calls=[]
    async def research(user,chat,p,token,mode,topics):
        return db.save(user,'coach_research',{'status':'checked','chunks':[],'warnings':[]})
    async def model(schema,payload,*args,**kw):
        calls.append((schema,kw['instructions']));value=reply(payload,needs_fresh_research=len(calls)==1)
        if operation=='message':value['recommendations']=[]
        return schema.model_validate(value).model_dump(),{'model':'simulated'}
    monkeypatch.setattr(coach,'research',research);monkeypatch.setattr(ai,'structured',model)
    response=client.post('/api/career-coach/chats/new/actions',json={'operation':operation,'text':QUESTION,'request_token':db.uid()})
    assert wait(client,response.json())['status']=='completed'
    schema, instructions=coach.generation_contract(operation)
    assert len(calls)==(1 if operation=='plan' else 2) and all(s is schema and i==instructions for s,i in calls)


def test_validation_diagnostics_never_include_values_or_unknown_keys(client,account,monkeypatch,caplog):
    calls=[]
    async def provider(body,**kw):
        calls.append(body)
        return {'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps({'answer':'PRIVATE ANSWER','private-secret-key':'PRIVATE VALUE'})}]}]}
    monkeypatch.setattr(ai,'call_api',provider)
    with pytest.raises(ServiceError) as err:asyncio.run(ai.structured(coach.PlanReply,{},retry_allowed=False))
    text=str(err.value)+' '+caplog.text
    assert 'recommendations (missing)' in text and '<field> (extra_forbidden)' in text
    assert not any(v in text for v in ('PRIVATE ANSWER','PRIVATE VALUE','private-secret-key'))
    assert len(calls)==1 and 'automatically retried' in str(err.value)
