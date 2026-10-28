import json
import pytest
from app import application_offers as offers, assistant_context, db, explicit_context, credentials, ai
from conftest import onboard_test_account
from test_broader_career import wait

def app(client,status='offer',title='Research engineer'):
    result=client.post('/api/applications',json={'title':title,'company':'Fictional Employer','status':status})
    assert result.status_code==200,result.text
    return result.json()

def save(client,application,revision=0,**details):
    return client.put('/api/applications/'+application['id']+'/offer',json={'expected_revision':revision,'details':details})

def test_optional_offer_unknowns_revision_and_history(client,account):
    a=app(client);path='/api/applications/'+a['id']+'/offer'
    initial=client.get(path).json();assert initial['revision']==0 and initial['details']['compensation']==''
    result=save(client,a,compensation='37.50',currency='usd',pay_period='hour',signing_bonus='One-time 1000 USD',equity='Not yet specified')
    assert result.status_code==200,result.text
    assert result.json()['details']['currency']=='USD'
    assert result.json()['details']['recurring_bonus']==''
    assert save(client,a,compensation='999').status_code==409
    assert client.get(path).json()['details']['compensation']=='37.50'
    changed=client.put('/api/applications/'+a['id'],json={**a['data'],'status':'declined'})
    assert changed.status_code==200,changed.text
    assert client.get(path).json()['details']['compensation']=='37.50'
    assert save(client,a,revision=1,compensation='38',currency='USD',pay_period='hour').status_code==200
    other=app(client,status='applied');assert save(client,other,notes='not an offer').status_code==409
    assert not db.list_entities(account['id'],'usage_event')

@pytest.mark.parametrize('details',[{'compensation':'-1'},{'compensation':'NaN'},{'compensation':'Infinity'},{'currency':'DOLLARS'},{'pay_period':'invented'},{'start_date':'2026-02-30'},{'response_deadline':'20261027'}])
def test_offer_validation(client,account,details):
    assert save(client,app(client),**details).status_code==422

def test_offer_isolation_no_automatic_context_and_backup_remapping(client,account):
    u=account['id'];a=app(client)
    assert save(client,a,notes='PRIVATE_OFFER_NOTE',compensation='123456.78',currency='USD',pay_period='year').status_code==200
    automatic=json.dumps(assistant_context.sources(u))
    assert 'PRIVATE_OFFER_NOTE' not in automatic and '123456.78' not in automatic
    with db.connect() as c:assert not c.execute("SELECT 1 FROM evidence_fts WHERE kind='application_offer'").fetchone()
    preview=client.get('/api/applications/'+a['id']+'/offer/preview').json()
    resolved=explicit_context.resolve(u,[preview['context_ref']]);assert 'PRIVATE_OFFER_NOTE' in resolved[0]['text']
    backup=client.get('/api/account/export').json()
    other=client.post('/api/auth/register',json={'username':'offer-other','password':'fictional-password'}).json();onboard_test_account(other);client.headers['X-CSRF-Token']=other['csrf']
    assert client.get('/api/applications/'+a['id']+'/offer').status_code==404
    assert client.get('/api/applications/'+a['id']+'/offer/preview').status_code==404
    with pytest.raises(Exception):explicit_context.resolve(other['id'],[preview['context_ref']])
    imported=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')})
    assert imported.status_code==200,imported.text
    restored=next(r for r in db.list_entities(other['id'],'application') if r['data']['title']==a['data']['title'])
    result=client.get('/api/applications/'+restored['id']+'/offer').json()
    assert result['revision']==1 and result['details']['notes']=='PRIVATE_OFFER_NOTE'
    assert 'PRIVATE_OFFER_NOTE' not in json.dumps(assistant_context.sources(other['id']))
    assert client.delete('/api/applications/'+restored['id']).status_code==200
    assert not db.list_entities(other['id'],'application_offer')
    assert db.get(u,offers.identity(u,a['id']),'application_offer')

def test_explicit_offer_discussion_and_stale_preview(client,account,monkeypatch):
    u=account['id'];credentials.save(u,'sk-fictional-key-never-sent');a=app(client)
    save(client,a,notes='A mentoring opportunity',currency='USD')
    ref=client.get('/api/applications/'+a['id']+'/offer/preview').json()['context_ref'];calls=[]
    async def model(schema,payload,*args,**kwargs):
        calls.append(payload);source=next(s for s in payload['source_catalog'] if s['kind']=='explicit_offer')
        return {'answer':'Consider the mentoring opportunity and clarify unknown terms.','references':[{'source_id':source['source_id'],'quote':'A mentoring opportunity'}],'needs_research':False,'research_topics':[],'visuals':[]},{'model':'fictional'}
    monkeypatch.setattr(ai,'structured',model)
    started=client.post('/api/knowledge-coach/chats/new/messages',json={'text':'Discuss this offer','request_token':'offer-discussion-one','shared_context':[ref]})
    result=wait(client,started);assert result['status']=='completed',result
    assert len(calls)==1
    assert save(client,a,revision=1,notes='Changed terms').status_code==200
    stale=client.post('/api/knowledge-coach/chats/new/messages',json={'text':'Discuss this offer','request_token':'offer-stale-one','shared_context':[ref]})
    assert stale.status_code==409 and len(calls)==1
