import copy,json
import pytest
from app import ai,career_goals,career_coach,db,assistant_ai,credentials,config,career_plan_inputs
from test_career_coach import reply,wait

def direction(**changes):
 return {'id':'overall','category':'general_statement','text':'Explore reliable cloud systems.', 'guided_editor':{'version':1,'mode':'direct','education':'yes','fields':{'graduation':'May 2027','degree':'Data Science','skills':'[blank]','completed_degree':'HIDDEN_EDITING_AID'}},**changes}

def put(client,items,revision=0,**kw):
 return client.put('/api/profile/career-goals',json={'items':items,'expected_revision':revision,**kw})

def test_editor_roundtrip_singleton_conflict_and_no_evidence_mutation(client,account):
 original=copy.deepcopy(db.list_entities(account['id'],'experience'))
 specific={'id':'cert','category':'certification','text':'Earn an AWS certification.','target':'2028','priority':'high','progress':'planned'}
 r=put(client,[direction(),specific],use_for_ai=True);assert r.status_code==200,r.text
 saved=r.json();assert saved['items'][0]['guided_editor']['fields']['skills']==''
 assert saved['items'][1]['text']==specific['text'] and saved['use_for_ai']
 assert client.get('/api/profile/career-goals').json()==saved
 assert put(client,[direction(id='duplicate'),direction()],1).status_code==422
 assert put(client,[direction(text='Stale update')],0).status_code==409
 assert career_goals.read(account['id'])==saved
 assert db.list_entities(account['id'],'experience')==original
 assert not db.list_entities(account['id'],'usage_event')
 # Omitting metadata from an old client discards editing aids without changing the ID.
 replacement={'id':'overall','category':'general_statement','text':'Explore research instead.'}
 assert put(client,[replacement,specific],1).status_code==200
 assert 'guided_editor' not in career_goals.read(account['id'])['items'][0]
 # Explicit legacy/chat save likewise cannot keep stale guided fields.
 assert put(client,[direction(),specific],2).status_code==200
 r=client.put('/api/profile/career-goals',json={'text':'Explore a new direction.','expected_revision':3})
 assert r.status_code==200 and 'guided_editor' not in r.json()['items'][0]
 assert r.json()['items'][0]['id']=='overall' and r.json()['items'][1]['id']=='cert'

@pytest.mark.parametrize('text',['[blank]',' [blank] ','___','...'])
def test_placeholder_only_rejected_without_changes(client,account,text):
 assert put(client,[direction(text=text)]).status_code==422
 assert career_goals.read(account['id'])['revision']==0

def test_normalization_and_strict_metadata_validation(client,account):
 r=put(client,[direction(text='Explore [blank] cloud.')]);assert r.status_code==200
 assert r.json()['note']=='Explore cloud.'
 for edit in [{'version':2},{'education':'inferred'},{'fields':{'unknown':'value'}},{'fields':{'skills':'x'*1001}}]:
  d=direction();d['guided_editor'].update(edit)
  assert put(client,[d],1).status_code==422
 assert put(client,[direction(category='skill')],1).status_code==422

def test_optional_metadata_backup_restore_and_isolation(client,account):
 assert put(client,[direction()]).status_code==200
 backup=client.get('/api/account/export').json()
 other=client.post('/api/auth/register',json={'username':'guided-other','password':'fictional-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
 assert client.get('/api/profile/career-goals').json()['items']==[]
 r=client.post('/api/account/import',files={'file':('goals.json',json.dumps(backup).encode(),'application/json')});assert r.status_code==200,r.text
 restored=career_goals.read(other['id']);assert restored['items'][0]['guided_editor']['education']=='yes'
 assert restored['items'][0]['text']==direction()['text'] and not restored['use_for_ai']
 assert 'Explore reliable' not in json.dumps(career_coach.profile(other['id']))

def test_guidance_groups_text_once_and_never_sends_fields(client,account):
 assert put(client,[direction(),{'id':'learn','category':'skill','text':'Learn distributed processing.'}],use_for_ai=True).status_code==200
 value=career_goals.guidance_context(account['id']);wire=json.dumps(value)
 assert wire.count(direction()['text'])==1 and 'HIDDEN_EDITING_AID' not in wire and 'guided_editor' not in wire
 assert 'Overall career direction' in value['text'] and 'Specific goals' in value['text']
 assert 'conflicting dates' in value['guidance']
 plan=career_plan_inputs.context(account['id'],career_plan_inputs.PlanInput(objective='Explore',goal_ids=['overall'],goals_revision=1))
 assert 'guided_editor' not in json.dumps(plan)
 q={'id':'q','label':'Why do you want this job?','description':'','context':'','options':[],'control':'textarea','private':False}
 body=assistant_ai.Assistance(request_token='g'*32,question_id='q',action='draft_short_answer',use_career_goals=True,approved_cost_usd=.01,consent=True)
 payload=assistant_ai.build_payload(account['id'],{'unresolved':[q]},body)
 wire=assistant_ai.provider_body(payload)['input'];assert wire.count(direction()['text'])==1 and 'HIDDEN_EDITING_AID' not in wire
 client.put('/api/profile/career-goals',json={'expected_revision':1,'use_for_ai':False})
 assert career_goals.guidance_context(account['id'])['text']==''

def test_mocked_planning_preserves_snapshots_and_receives_no_editor_fields(client,account,monkeypatch):
 put(client,[direction()],use_for_ai=True);credentials.save(account['id'],'sk-fictional-goals');monkeypatch.setattr(config,'ENABLE_WEB_SEARCH',False)
 chat=client.post('/api/career-coach/chats',json={}).json();snapshot=copy.deepcopy(chat['data']['profile_goals_snapshot']);calls=[]
 put(client,[direction(text='A newer direction.')],1)
 async def model(schema,payload,*a,**k):
  calls.append(payload);return reply(payload,recommendations=[]),{'model':'fictional'}
 monkeypatch.setattr(ai,'structured',model)
 task=client.post('/api/career-coach/chats/'+chat['id']+'/actions',json={'operation':'message','text':'Help me explore','request_token':'guided-direction-mock'}).json()
 result=wait(client,task);assert result['status']=='completed',result
 goals=calls[0]['career_goals_as_aspirations'];assert goals['text'].count(direction()['text'])==1
 assert 'A newer direction.' not in goals['text'] and 'guided_editor' not in json.dumps(calls[0])
 assert client.get('/api/career-coach/chats/'+chat['id']).json()['chat']['data']['profile_goals_snapshot']==snapshot
