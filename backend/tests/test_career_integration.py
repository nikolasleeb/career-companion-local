"""Career handoffs use fictional accounts and mocked providers only."""
import copy
import json
import pytest
from app import ai, career_goals, config, credentials, db, explicit_context
from test_broader_career import wait
from test_career_coach import reply

CODE = '15-1252.00'

def goal(code=CODE, id='exploring-software'):
    return {'id':id,'category':'career_change','text':'Explore a transition into software development.',
            'target':'Next year','priority':'medium','progress':'planned','occupation':explicit_context.occupation_link(code)}

def test_linked_goals_review_revision_duplicates_and_bookmarks(client, account):
    user = account['id']
    detail = client.get('/api/career-explorer/occupations/'+CODE).json()
    assert detail['context_ref'] == explicit_context.occupation_reference(CODE)
    assert not db.list_entities(user,'career_goals')
    initial = client.put('/api/profile/career-goals',json={'expected_revision':0,'items':[goal()]})
    assert initial.status_code == 200, initial.text
    assert initial.json()['items'][0]['occupation']==detail['occupation_link']
    assert not initial.json()['use_for_ai']
    assert client.put('/api/profile/career-goals',json={'expected_revision':1,'items':[goal(),goal(id='duplicate')]}).status_code==422
    assert client.put('/api/profile/career-goals',json={'expected_revision':0,'items':[goal()]}).status_code==409
    edited=goal();edited['text']='My own carefully edited ambition.'
    assert client.put('/api/profile/career-goals',json={'expected_revision':1,'items':[edited]}).status_code==200
    career=client.post('/api/career-explorer/saved',json={'code':CODE}).json()['careers'][0]
    assert client.delete('/api/career-explorer/saved/'+career['id']).status_code==200
    assert career_goals.read(user)['items'][0]['text']==edited['text']
    backup=client.get('/api/account/export').json()
    assert client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')}).status_code==200
    assert not db.list_entities(user,'usage_event')

def test_forged_and_stale_goal_metadata_rejected_losslessly(client,account):
    bad=goal();bad['occupation']['title']='Invented title'
    assert client.put('/api/profile/career-goals',json={'expected_revision':0,'items':[bad]}).status_code==409
    bad=goal();bad['occupation']['revision']='0'*64
    assert client.put('/api/profile/career-goals',json={'expected_revision':0,'items':[bad]}).status_code==409
    assert career_goals.read(account['id'])['revision']==0
    legacy={'id':'legacy','category':'custom','text':'Preserve this existing goal.'}
    result=client.put('/api/profile/career-goals',json={'expected_revision':0,'items':[legacy]})
    assert result.status_code==200
    assert 'occupation' not in result.json()['items'][0]

@pytest.mark.parametrize('path',['knowledge-coach/chats/new/messages','career-coach/chats/new/actions'])
def test_bad_context_stops_before_dispatch(client,account,monkeypatch,path):
    credentials.save(account['id'],'sk-fictional-never-sent')
    async def forbidden(*args,**kwargs):raise AssertionError('Must not dispatch paid work')
    monkeypatch.setattr(ai,'structured',forbidden)
    ref=explicit_context.occupation_reference(CODE);ref['revision']='0'*64
    result=client.post('/api/'+path,json={'text':'Explore this occupation','request_token':'stale-context-test','shared_context':[ref]})
    assert result.status_code==409,result.text
    assert not db.list_entities(account['id'],'assistant_chat')
    assert not db.list_entities(account['id'],'coach_chat')

def test_explicit_coach_context_with_global_goals_off(client,account,monkeypatch):
    user=account['id'];credentials.save(user,'sk-fictional-never-sent')
    career_goals.save(user,career_goals.Change(expected_revision=0,items=[career_goals.Goal(id='private-goal',text='UNSELECTED_GOAL')]))
    before=copy.deepcopy(db.list_entities(user,'experience'));calls=[]
    async def model(schema,payload,*args,**kwargs):
        calls.append(payload)
        source=next(s for s in payload['source_catalog'] if s['kind']=='explicit_occupation')
        assert 'UNSELECTED_GOAL' not in json.dumps(payload)
        return {'answer':'Explore this occupation as an interest, not a qualification.','references':[{'source_id':source['source_id'],'quote':source['text'][:80]}],'needs_research':False,'research_topics':[],'visuals':[]},{'model':'fictional'}
    monkeypatch.setattr(ai,'structured',model)
    body={'text':'Help me explore this occupation','request_token':'explicit-coach-test','shared_context':[explicit_context.occupation_reference(CODE)]}
    started=client.post('/api/knowledge-coach/chats/new/messages',json=body);result=wait(client,started)
    assert result['status']=='completed',result
    assert len(calls)==1
    again=client.post('/api/knowledge-coach/chats/new/messages',json=body)
    assert again.json()['task_id']==started.json()['task_id']
    assert len(calls)==1
    saved=next(r for r in result['result']['messages'] if r['data']['role']=='assistant')
    assert saved['data']['explicit_context_snapshot'][0]['revision']==body['shared_context'][0]['revision']
    assert saved['data']['explicit_context_snapshot'][0]['snapshot']['code']==CODE
    assert db.list_entities(user,'experience')==before
    assert not career_goals.read(user)['use_for_ai']

def test_explicit_plans_context_citations_and_backup(client,account,monkeypatch):
    user=account['id'];credentials.save(user,'sk-fictional-never-sent');monkeypatch.setattr(config,'ENABLE_WEB_SEARCH',False)
    calls=[]
    async def model(schema,payload,*args,**kwargs):
        calls.append(payload)
        assert payload['explicitly_selected_context'][0]['snapshot']['code']==CODE
        source=next(s for s in payload['retrieved_chunks'] if s['kind']=='occupation')
        refs=[{'chunk_id':source['chunk_id'],'quote':source['text'][:100]}]
        return reply(payload,recommendations=[],citations=refs),{'model':'fictional'}
    monkeypatch.setattr(ai,'structured',model)
    started=client.post('/api/career-coach/chats/new/actions',json={'operation':'message','text':'Explore this occupation with me','request_token':'explicit-plans-test','shared_context':[explicit_context.occupation_reference(CODE)]})
    result=wait(client,started);assert result['status']=='completed',result
    assert len(calls)==1 and not db.list_entities(user,'coach_plan')
    message=result['result']['data'];assert message['explicit_context_snapshot'][0]['snapshot']['code']==CODE
    assert message['reply']['citations'][0]['kind']=='occupation'
    backup=client.get('/api/account/export').json()
    imported=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')})
    assert imported.status_code==200,imported.text
