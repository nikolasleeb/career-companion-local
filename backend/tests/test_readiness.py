"""Real SDK Runner with fictional accounts and intercepted provider responses."""
import asyncio, copy, json, time
import pytest
from app import db, credentials, ai, readiness, personalization
from app.readiness_models import Reply, Direction, Finding, NextAction, Reference
from app.readiness_runtime import Context, Budget
from app.network import ServiceError

CODE='15-2051.00'

def find(text,source):return Finding(text=text,references=[Reference(source_id=source['source_id'],quote=source['text'][:120])])

def response(wire,output):
    return {'id':'resp_'+db.uid(),'object':'response','created_at':int(time.time()),'model':wire['model'],
            'status':'completed','parallel_tool_calls':False,'tool_choice':'auto','tools':wire.get('tools',[]),
            'output':output,'usage':{'input_tokens':100,'output_tokens':150,'total_tokens':250,
            'input_tokens_details':{'cached_tokens':0,'cache_write_tokens':0},'output_tokens_details':{'reasoning_tokens':0}}}

def output_for(wire):
    initial=json.loads(wire['input'][0]['content'][0]['text']) if isinstance(wire['input'][0].get('content'),list) else json.loads(wire['input'][0]['content'])
    operation=initial['operation'];sources={s['source_id']:s for s in initial['source_catalog']}
    for item in wire['input']:
        if item.get('type')=='function_call_output':
            data=json.loads(item['output']);sources.update({s['source_id']:s for s in data.get('sources',[])})
    source=sources['occupation:'+CODE]
    direction=Direction(code=CODE,interest_connection=find('This direction is worth exploring.',source),work_and_preparation=find('Review the published occupation description.',source),exploration_activity='Try explaining a small fictional analysis.')
    kind={'discover':'shortlist','compare':'comparison','assess':'assessment','reassess':'assessment','follow_up':'answer'}[operation]
    actions=[NextAction(title=t,purpose='Explore the work through a small practice activity.',effort='Estimate: a short session',steps=['Choose a fictional example','Reflect on what interests you'],learning_topics=['Python'],references=direction.work_and_preparation.references) for t in ('Explore a task','Practice a method','Reflect on the direction')] if kind=='assessment' else []
    return Reply(outcome=kind,summary='Explore the direction and review the uncertainty.',summary_references=direction.work_and_preparation.references,
                 directions=[direction] if kind in ('shortlist','comparison') else [],next_actions=actions,
                 needs_clarification=['Your interests need further exploration.'],changes=['Current evidence reviewed.'] if operation=='reassess' else []).model_dump()

@pytest.fixture
def provider(monkeypatch):
    wires=[]
    original=readiness.run_agent
    async def diagnostic(*args,**kwargs):
        try:return await original(*args,**kwargs)
        except Exception:
            import traceback;traceback.print_exc();raise
    monkeypatch.setattr(readiness,'run_agent',diagnostic)
    async def call(wire,retry_allowed=True):
        assert retry_allowed is False and wire['store'] is False
        wires.append(copy.deepcopy(wire));policy=ai._request_policy.get();reservation=policy.reserve(wire) if policy else None
        names={i.get('name') for i in wire['input'] if i.get('type')=='function_call'}
        if 'inspect_occupation' not in names and wire.get('tool_choice')!='none':
            content=[{'type':'function_call','id':'fc_'+db.uid(),'call_id':'call_'+db.uid(),'name':'inspect_occupation','arguments':json.dumps({'occupation_code':CODE}),'status':'completed'}]
        else:
            value=output_for(wire)
            content=[{'type':'message','id':'msg_'+db.uid(),'role':'assistant','status':'completed','content':[{'type':'output_text','text':json.dumps({'reply':value}),'annotations':[]}]}]
        result=response(wire,content)
        if policy:policy.finish(reservation,result,200)
        return result
    monkeypatch.setattr(ai,'call_api',call);return wires

def new(client,account,**kwargs):
    credentials.save(account['id'],'sk-fictional-never-sent')
    r=client.post('/api/career-readiness/sessions',json={'objective':'Explore careers involving analysis',**kwargs})
    assert r.status_code==200,r.text;return r.json()

def wait(client,start):
    for _ in range(250):
        r=client.get('/api/tasks/'+start['task_id']).json()
        if r['status'] not in ('queued','running','cancelling'):return r
        time.sleep(.01)
    raise AssertionError('Readiness did not finish')

def act(client,session,operation='discover',token=None,**kwargs):
    body={'operation':operation,'expected_revision':session['data']['revision'],'request_token':token or db.uid(),**kwargs}
    r=client.post('/api/career-readiness/sessions/'+session['id']+'/actions',json=body)
    assert r.status_code==200,r.text
    return wait(client,r.json()),body

def test_browsing_and_saving_are_free(client,account,provider):
    s=new(client,account)
    assert client.get('/api/career-readiness/options').status_code==200
    assert client.get('/api/career-readiness/occupations?q=data%20scientist').json()
    assert client.get('/api/career-readiness/sessions/'+s['id']).status_code==200
    assert client.get('/api/career-readiness/sessions/'+s['id']+'/estimate').status_code==200
    assert not provider

def test_exploration_works_before_profile_setup(client,provider):
    r=client.post('/api/auth/register',json={'username':'undecided-student','password':'fictional-undecided-password'})
    u=r.json();client.headers['X-CSRF-Token']=u['csrf']
    assert client.get('/api/career-readiness/options').status_code==200
    s=new(client,u);result,_=act(client,s)
    assert result['status']=='completed',result

def test_readiness_is_explicit_coach_context_only(client,account,provider):
    s=new(client,account,occupation_codes=[CODE],selected_code=CODE);result,_=act(client,s,'assess');assert result['status']=='completed',result
    d=client.get('/api/career-readiness/sessions/'+s['id']).json();report=d['reports'][0]
    from app import explicit_context,coach_access
    assert not any(r['kind']=='readiness_report' for r in coach_access.records(account['id']))
    shared=client.get('/api/career-readiness/reports/'+report['id']+'/handoff').json()
    resolved=explicit_context.resolve(account['id'],[shared['context_ref']]);assert resolved[0]['kind']=='explicit_readiness'
    assert explicit_context.plan_chunks(resolved)[0]['kind']=='readiness'

def test_revoke_sharing_blocks_handoff_but_allows_fresh_reassessment(client,account,provider):
    s=new(client,account,occupation_codes=[CODE],selected_code=CODE);result,_=act(client,s,'assess');assert result['status']=='completed',result
    d=client.get('/api/career-readiness/sessions/'+s['id']).json();report=d['reports'][0]
    value=personalization.read(account['id'])
    assert client.put('/api/profile/personalization',json={'enabled':False,'expected_revision':value['revision']}).status_code==200
    assert client.get('/api/career-readiness/reports/'+report['id']+'/handoff').status_code==400
    result,_=act(client,d['session'],'reassess',report_id=report['id']);assert result['status']=='completed',result
    d=client.get('/api/career-readiness/sessions/'+s['id']).json()
    assert not any(source['kind']=='reviewed_profile' for source in d['reports'][-1]['data']['source_snapshot'])

def test_cancellation_does_not_publish_partial_output_or_retry(client,account,monkeypatch):
    calls=[]
    async def waiting(*args,**kwargs):calls.append(1);await asyncio.sleep(30)
    monkeypatch.setattr(ai,'call_api',waiting)
    s=new(client,account)
    r=client.post('/api/career-readiness/sessions/'+s['id']+'/actions',json={'operation':'discover','expected_revision':1,'request_token':'readiness-cancel-token'})
    assert r.status_code==200
    for _ in range(50):
        if calls:break
        time.sleep(.01)
    stop=client.post('/api/tasks/'+r.json()['task_id']+'/cancel',json={});assert stop.status_code==200
    result=wait(client,r.json());assert result['status']=='cancelled',result
    assert len(calls)==1
    d=client.get('/api/career-readiness/sessions/'+s['id']).json();assert not d['reports'] and not d['turns'] and d['session']['data']['revision']==1

def test_profile_edit_during_provider_wait_rejects_stale_assessment(client,account,provider,monkeypatch):
    original=ai.call_api;started=[]
    async def delayed(*args,**kwargs):
        started.append(True);await asyncio.sleep(.15);return await original(*args,**kwargs)
    monkeypatch.setattr(ai,'call_api',delayed)
    s=new(client,account,occupation_codes=[CODE],selected_code=CODE)
    r=client.post('/api/career-readiness/sessions/'+s['id']+'/actions',json={'operation':'assess','expected_revision':1,'request_token':db.uid()});assert r.status_code==200
    for _ in range(50):
        if started:break
        time.sleep(.01)
    db.save(account['id'],'experience',{'category':'project','title':'New reviewed project','description':'A new reviewed description.','confirmed':True})
    result=wait(client,r.json());assert result['status']=='failed' and 'changed during' in result['error']
    assert not db.list_entities(account['id'],'readiness_report')

def test_sdk_loop_assessment_history_handoff_and_reassessment(client,account,provider):
    s=new(client,account);r,_=act(client,s);assert r['status']=='completed',r
    details=client.get('/api/career-readiness/sessions/'+s['id']).json()
    assert details['turns'][0]['data']['activity'][0]['tool']=='inspect_occupation'
    assert len(provider)==2
    s=details['session'];updated=client.patch('/api/career-readiness/sessions/'+s['id'],json={**s['data']['inputs'],'occupation_codes':[CODE],'selected_code':CODE,'expected_revision':s['data']['revision']})
    assert updated.status_code==200,updated.text;s=updated.json()
    r,_=act(client,s,'assess');assert r['status']=='completed',r
    d=client.get('/api/career-readiness/sessions/'+s['id']).json();assert len(d['reports'])==1
    report=d['reports'][0];assert len(report['data']['reply']['next_actions'])==3
    h=client.get('/api/career-readiness/sessions/'+s['id']+'/handoff/'+report['id']);assert h.status_code==200,h.text
    assert h.json()['context_ref']['kind']=='readiness'
    assert client.get('/api/career-readiness/sessions/'+s['id']+'/changes').json()['unchanged']
    r,_=act(client,d['session'],'follow_up',message='Why this direction?',report_id=report['id']);assert r['status']=='completed',r
    d=client.get('/api/career-readiness/sessions/'+s['id']).json()
    r,_=act(client,d['session'],'reassess',report_id=report['id']);assert r['status']=='completed',r
    d=client.get('/api/career-readiness/sessions/'+s['id']).json();assert [v['data']['version'] for v in d['reports']]==[1,2]
    assert d['reports'][0]['data']['reply']==report['data']['reply']

def test_completed_request_token_recovers_without_redispatch(client,account,provider):
    s=new(client,account);r,body=act(client,s,token='readiness-recovery-0001');assert r['status']=='completed',r
    count=len(provider)
    again=client.post('/api/career-readiness/sessions/'+s['id']+'/actions',json=body)
    assert again.status_code==200 and again.json()['task_id']==r['id']
    assert len(provider)==count
    assert client.get('/api/career-readiness/actions/'+body['request_token']).json()['task_id']==r['id']
    wrong=client.post('/api/career-readiness/sessions/'+s['id']+'/actions',json={**body,'message':'different'})
    assert wrong.status_code==409

def test_invalid_selection_and_stale_update(client,account,provider):
    assert client.post('/api/career-readiness/sessions',json={'objective':'Explore','occupation_codes':['invented']}).status_code==404
    s=new(client,account)
    assert client.post('/api/career-readiness/sessions/'+s['id']+'/actions',json={'operation':'assess','expected_revision':1,'request_token':db.uid()}).status_code==422
    patch={**s['data']['inputs'],'expected_revision':1}
    assert client.patch('/api/career-readiness/sessions/'+s['id'],json=patch).status_code==200
    assert client.patch('/api/career-readiness/sessions/'+s['id'],json=patch).status_code==409
    assert not provider

def test_account_isolation_and_delete(client,account,provider):
    s=new(client,account);r,_=act(client,s);assert r['status']=='completed',r
    other=client.post('/api/auth/register',json={'username':'other-readiness','password':'fictional-other-password'}).json();from conftest import onboard_test_account;onboard_test_account(other);client.headers['X-CSRF-Token']=other['csrf']
    assert client.get('/api/career-readiness/sessions').json()==[]
    assert client.get('/api/career-readiness/sessions/'+s['id']).status_code==404
    assert client.delete('/api/career-readiness/sessions/'+s['id']).status_code==404
    assert client.get('/api/career-readiness/actions/'+r['result']['turn_id']).status_code==404

def test_quote_and_professional_evidence_validation(client,account):
    c=Context(account['id'],'fictional',{'occupation_codes':[CODE],'selected_code':CODE},'economy')
    source={'source_id':'occupation:'+CODE,'kind':'occupation','text':'This is occupational guidance.'};c.add([source])
    value=Reply(outcome='answer',summary='Discuss uncertainty.',demonstrated_strengths=[find('You have experience.',source)]).model_dump()
    checked=readiness.validate_reply(value,c,'follow_up')
    assert checked['demonstrated_strengths']==[] and any('omitted' in s for s in checked['limitations'])
    value['demonstrated_strengths']=[];value['summary_references']=[{'source_id':source['source_id'],'quote':'not present'}]
    with pytest.raises(ServiceError,match='citation'):readiness.validate_reply(value,c,'follow_up')

def test_quote_punctuation_can_be_trimmed_but_words_cannot_be_repaired(client,account):
    c=Context(account['id'],'fictional',{},'economy')
    c.add([{'source_id':'source','kind':'curated','text':'Analyze user needs and develop solutions, applying documented methods.'}])
    value=Reply(outcome='answer',summary='Consider the work.',summary_references=[Reference(source_id='source',quote='Analyze user needs and develop solutions.')]).model_dump()
    assert readiness.validate_reply(value,c,'follow_up')['summary_references'][0]['quote']=='Analyze user needs and develop solutions'
    value['summary_references'][0]['quote']='Analyze employer needs and develop solutions.'
    with pytest.raises(ServiceError):readiness.validate_reply(value,c,'follow_up')
    value['summary_references'][0]={'source_id':'mistyped-id','quote':'Analyze user needs and develop solutions'}
    assert readiness.validate_reply(value,c,'follow_up')['summary_references'][0]['source_id']=='source'
    c.add([{'source_id':'duplicate','kind':'curated','text':'Analyze user needs and develop solutions, with another context.'}])
    with pytest.raises(ServiceError):readiness.validate_reply(value,c,'follow_up')

def test_discovery_search_handles_interests_and_returns_inspected_candidate_sources(client,account):
    rows=readiness.search_occupations('investigating questions and explaining research',account['id'])
    assert rows and all(row['description'] for row in rows)
    s=new(client,account);c=Context(account['id'],s['id'],{**s['data']['inputs'],'operation':'discover'},'economy')
    async def run():
        from agents.tool_context import ToolContext
        tool=next(t for t in readiness.tools_for(c) if t.name=='find_occupations')
        output=json.loads(await tool.on_invoke_tool(ToolContext(context=c,tool_name=tool.name,tool_call_id='fictional',tool_arguments='{}'),json.dumps({'query':'data scientist'})))
        assert output['sources'] and all(v['kind']=='occupation' for v in output['sources'])
        assert 'occupation:'+CODE in c.sources
    asyncio.run(run())

def test_budget_unknown_reservation_and_turn_limits(client,account):
    s=new(client,account);task=db.uid()
    with db.connect() as conn:conn.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',(task,account['id'],'career_readiness','running','{}',None,db.now(),db.now()))
    token=ai.set_user_context(account['id'],task_id=task,process='career_readiness')
    try:
        b=Budget(Context(account['id'],s['id'],s['data']['inputs'],'economy'))
        wire={'model':ai.options('economy')['model'],'input':'fictional','max_output_tokens':1000}
        reserved=b.reserve(wire);b.finish(reserved,None);assert b.used>0
        with db.connect() as conn:assert conn.execute('SELECT state FROM cc_readiness_reservations WHERE id=?',(reserved[0],)).fetchone()[0]=='unknown'
        b.ceiling=b.used
        with pytest.raises(ServiceError,match='spending ceiling'):b.reserve(wire)
    finally:ai.reset_user_context(token)

def test_tool_limits_repeated_calls_and_research_disabled(client,account):
    s=new(client,account);c=Context(account['id'],s['id'],{**s['data']['inputs'],'operation':'discover'},'economy')
    async def run():
        assert await c.invoke('example',{},lambda:{'ok':True})=={'ok':True}
        assert (await c.invoke('example',{},lambda:pytest.fail('Repeated tool executed')))['unavailable']
        research=next(t for t in readiness.tools_for(c) if t.name=='research_career')
        from agents.tool_context import ToolContext
        value=await research.on_invoke_tool(ToolContext(context=c,tool_name='research_career',tool_call_id='fictional',tool_arguments='{}'),json.dumps({'occupation_code':CODE,'focus':'licensing'}))
        assert 'disabled' in value
    asyncio.run(run())

def test_lifecycle_backup_validation_and_cleanup(client,account,provider):
    s=new(client,account,occupation_codes=[CODE],selected_code=CODE);r,_=act(client,s,'assess');assert r['status']=='completed',r
    exported=client.get('/api/account/export');assert exported.status_code==200
    data=exported.json();kinds={r['id']:r['kind'] for r in data['records']};by_id={r['id']:r for r in data['records']}
    records=[r for r in data['records'] if r['kind'] in readiness.KINDS];assert {r['kind'] for r in records}=={'readiness_session','readiness_turn','readiness_report'}
    for r in records:readiness.validate_backup(r,kinds,by_id)
    assert client.delete('/api/career-readiness/sessions/'+s['id']).status_code==200
    assert not db.list_entities(account['id'],'readiness_report')
    with db.connect() as conn:assert not conn.execute('SELECT * FROM cc_readiness_reservations').fetchall()

def test_account_import_remaps_readiness_and_preserves_dates_costs_and_handoffs(client,account,provider):
    s=new(client,account,occupation_codes=[CODE],selected_code=CODE);r,_=act(client,s,'assess');assert r['status']=='completed',r
    original=client.get('/api/career-readiness/sessions/'+s['id']).json()
    exported=client.get('/api/account/export').json()
    restored=client.post('/api/account/import',files={'file':('fictional-backup.json',json.dumps(exported).encode(),'application/json')})
    assert restored.status_code==200,restored.text
    sessions=client.get('/api/career-readiness/sessions').json();imported=next(row for row in sessions if row['id']!=s['id'])
    detail=client.get('/api/career-readiness/sessions/'+imported['id']).json();assert len(detail['reports'])==1
    report=detail['reports'][0]
    assert report['id']!=original['reports'][0]['id'] and report['data']['session_id']==imported['id']
    assert report['created_at']==original['reports'][0]['created_at']
    assert detail['session']['data']['inputs']['selected_code']==CODE
    assert detail['session_cost']==original['session_cost']
    assert client.get('/api/career-readiness/reports/'+report['id']+'/handoff').status_code==200

def test_readiness_to_interview_carries_reviewed_guidance_link(client,account,provider):
    s=new(client,account,occupation_codes=[CODE],selected_code=CODE);r,_=act(client,s,'assess');assert r['status']=='completed',r
    d=client.get('/api/career-readiness/sessions/'+s['id']).json();report=d['reports'][0]
    created=client.post('/api/interview-practice/sessions',json={'kind':'behavioral','role':'Data Scientists','notes':'Generated readiness guidance, not qualification evidence.','readiness_report_id':report['id']})
    assert created.status_code==200,created.text
    from app import interview_practice
    _,catalog=interview_practice.context(account['id'],created.json())
    assert any(s['kind']=='generated_readiness' for s in catalog)
