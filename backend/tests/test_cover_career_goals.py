import asyncio
import copy
import json
from app import career_goals, cover_context, cover_letters as letters, db
from app.models import CoverContent, CoverContextReview, CoverGenerate
from test_cover_letters import env
from conftest import onboard_test_account

def select(client,state,revision=1,enabled=True,ids=None):
    return client.put('/api/cover-workspaces/'+state['id']+'/career-goals',json={
        'expected_version':state['data']['version'],'expected_goals_revision':revision,
        'enabled':enabled,'goal_ids':ids if ids is not None else ['change-field']})

def create_goal(user):
    return career_goals.save(user,career_goals.Change(expected_revision=0,items=[career_goals.Goal(
        id='change-field',category='career_change',text='I want to move into data engineering because I enjoy building reliable pipelines.')]))

def review(user,state,text=None):
    pending=next(p for p in state['data']['context_proposals'] if p['status']=='pending')
    body=CoverContextReview(expected_version=state['data']['version'],content=CoverContent.model_validate(state['data']['content']),
        decisions=[{'proposal_id':pending['id'],'action':'approve','text':text or pending['text'],'save_to_profile':False}],build=False)
    return asyncio.run(cover_context.review(user,state['id'],body))

def test_selected_goals_require_motivation_review_and_revoke_future_context(client,env):
    user,job,resume,state,calls=env;create_goal(user)
    before=copy.deepcopy(db.list_entities(user,'experience'));resume_before=copy.deepcopy(db.get(user,resume['id'],'resume'))
    options=client.get('/api/cover-workspaces/'+state['id']+'/career-goals').json()
    assert options['selection']=={'enabled':False,'goal_ids':[]}
    selected=select(client,state);assert selected.status_code==200,selected.text
    state=selected.json();proposal=state['data']['context_proposals'][0]
    assert proposal['kind']=='motivation' and proposal['status']=='pending'
    assert proposal['career_goal_source']['goals_revision']==1
    assert not any(r['id'].startswith('answer:') for r in state['sources'])
    state=review(user,state,'I am exploring data engineering because I enjoy building reliable pipelines.')
    assert any(r.get('kind')=='motivation' for r in state['sources'])
    assert not calls
    state=asyncio.run(letters.generate(user,state['id'],CoverGenerate(expected_version=state['data']['version'],content=CoverContent.model_validate(state['data']['content']))))
    assert any(r.get('kind')=='motivation' for r in calls[0][1]['saved_resume_sources'])
    old_revision=copy.deepcopy(db.get(user,state['current']['id'],'cover_revision'))
    assert old_revision['data']['career_goal_selection']['enabled']
    off=select(client,state,enabled=False);assert off.status_code==200,off.text
    assert not any(r.get('kind')=='motivation' for r in off.json()['sources'])
    assert db.get(user,state['current']['id'],'cover_revision')==old_revision
    assert db.list_entities(user,'experience')==before and db.get(user,resume['id'],'resume')==resume_before
    assert not career_goals.read(user)['use_for_ai']
    backup=client.get('/api/account/export').json()
    restored=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')})
    assert restored.status_code==200,restored.text

def test_changed_goals_need_new_review_and_stale_letter_cannot_overwrite(client,env):
    user,_,_,state,calls=env;create_goal(user)
    selected=select(client,state);assert selected.status_code==200
    latest=selected.json();assert select(client,state).status_code==409
    career_goals.save(user,career_goals.Change(expected_revision=1,items=[career_goals.Goal(id='change-field',category='career_change',text='I am now exploring research engineering.')]))
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:review(user,latest)
    assert error.value.status_code==409
    assert not calls
    refreshed=select(client,latest,revision=2);assert refreshed.status_code==200,refreshed.text
    pending=[p for p in refreshed.json()['data']['context_proposals'] if p['status']=='pending']
    assert len(pending)==1 and pending[0]['text']=='I am now exploring research engineering.'
    assert all(p['status']=='rejected' for p in refreshed.json()['data']['context_proposals'] if p['career_goal_source']['goals_revision']==1)

def test_goal_choices_and_letter_selection_are_account_scoped(client,env):
    user,_,_,state,calls=env;create_goal(user)
    assert select(client,state,ids=['another-users-goal']).status_code==404
    assert select(client,state,ids=[]).status_code==422
    other=client.post('/api/auth/register',json={'username':'other-letter-goal','password':'fictional-password'}).json();onboard_test_account(other);client.headers['X-CSRF-Token']=other['csrf']
    assert client.get('/api/cover-workspaces/'+state['id']+'/career-goals').status_code==404
    assert select(client,state).status_code==404
    assert not calls
