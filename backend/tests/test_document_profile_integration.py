"""Combined Profile/document approval regression; all model responses are fictional."""
import asyncio,copy
import pytest
from fastapi import HTTPException
from app import db,resume_conversation as guided
from app.models import ConversationMessage,FactApproval
from test_guided_resume import env,proposal,response,chat_mock


def test_supporting_detail_approval_preserves_explicit_course_status_and_is_once_only(env,client,monkeypatch):
 uid,job,rows,session,calls=env;school=next(r for r in rows if r['data']['category']=='education')
 added=client.post('/api/profile-courses/'+school['id']+'/add',json={'expected_updated_at':school['updated_at'],'titles':['SQL Methods']});assert added.status_code==200,added.text
 course=next(c for c in added.json()['courses'] if c['title']=='SQL Methods')
 updated=client.put('/api/profile-courses/'+school['id']+'/'+course['id'],json={'expected_updated_at':course['parent_updated_at'],'title':course['title'],'status':'planned'});assert updated.status_code==200,updated.text
 before=copy.deepcopy(db.get(uid,school['id'])['data']['course_items'])
 p=proposal(env,rid=school['id'],category='education',text='Presented SQL findings in class.')
 chat_mock(monkeypatch,response([p]));state=guided.state(uid,session['id'])
 state=asyncio.run(guided.send(uid,state['id'],ConversationMessage(text=p['fields'][0]['value'],expected_version=state['data']['version'])))
 pending=next(p for p in state['data']['proposals'] if p['status']=='pending')
 body=FactApproval(proposal_id=pending['id'],expected_version=state['data']['version'],action='approve',update_draft=False)
 confirmed=guided.approve(uid,state['id'],body)
 normalize=lambda items:[{**item,'status_override':item.get('status_override')} for item in items]
 assert normalize(db.get(uid,school['id'])['data']['course_items'])==normalize(before)
 current=next(c for c in client.get('/api/profile-courses').json() if c['id']==course['id']);assert current['status']=='planned' and current['status_override'] is True
 answers=db.list_entities(uid,'profile_answer');assert len(answers)==1 and school['id'] in answers[0]['data']['experience_ids']
 with pytest.raises(HTTPException):guided.approve(uid,state['id'],body.model_copy(update={'expected_version':confirmed['data']['version']}))
 assert len(db.list_entities(uid,'profile_answer'))==1 and not calls
