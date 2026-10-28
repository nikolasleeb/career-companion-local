import json
from app import config,credentials,db,onboarding,work_style
from test_onboarding import fresh

def test_resources_are_available_without_education_or_key(client,fresh,monkeypatch):
    for url in ('/api/guidance','/api/resources','/api/skills/options','/api/work-style/catalog','/api/work-style','/api/career-coach/chats','/api/career-coach/plans','/api/knowledge-coach/chats','/api/knowledge-coach/context','/api/interview-practice/sessions','/api/interview-practice/documents','/api/settings/api-connections','/api/profile/work-preferences'):
        response=client.get(url);assert response.status_code==200,(url,response.text)
    assessment=client.post('/api/work-style');assert assessment.status_code==200,assessment.text
    setup={'kind':'star','title':'General practice'}
    session=client.post('/api/interview-practice/sessions',json=setup);assert session.status_code==200,session.text
    id=session.json()['session']['id'] if 'session' in session.json() else session.json()['id']
    detail=client.get('/api/interview-practice/sessions/'+id);assert detail.status_code==200
    question=client.post('/api/interview-practice/sessions/'+id+'/questions',json={'question':'Tell me about a time you learned something.','expected_updated_at':detail.json()['session']['updated_at']});assert question.status_code==200,question.text
    assert client.get('/api/interview-practice/sessions/'+id+'/voice').status_code==200
    assert client.get('/api/applications').status_code==403 and client.get('/api/jobs/foreign/overview').status_code==403
    assert not onboarding.status(fresh['id'])['completed']

def test_general_coach_with_empty_profile_and_key(client,fresh,monkeypatch):
    from app import ai
    from test_broader_career import wait
    calls=[]
    async def model(schema,payload,*args,**kwargs):
        calls.append(payload)
        return {'answer':'Try a small project to explore your interests.','references':[],'needs_research':False,'research_topics':[],'visuals':[]},{'model':'fictional'}
    monkeypatch.setattr(ai,'structured',model)
    body={'text':'How can I explore careers in general?','request_token':'general-resource-test'}
    missing=client.post('/api/knowledge-coach/chats/new/messages',json=body);assert missing.status_code==503 and not calls
    credentials.save(fresh['id'],'sk-fictional-never-sent')
    task=wait(client,client.post('/api/knowledge-coach/chats/new/messages',json=body));assert task['status']=='completed',task
    assert len(calls)==1 and not db.list_entities(fresh['id'],'experience')
    assert client.get('/api/ai-actions/general-resource-test').status_code==200

def test_connection_metadata_contains_no_secrets(client,fresh,monkeypatch):
    monkeypatch.setattr(config,'ONET_KEY','secret-onet-long-value')
    monkeypatch.setattr(config,'USAJOBS_KEY','secret-usajobs-long-value');monkeypatch.setattr(config,'USAJOBS_EMAIL','server-private@example.org')
    credentials.save(fresh['id'],'sk-fictional-never-sent')
    response=client.get('/api/settings/api-connections');assert response.status_code==200
    value=response.json();text=json.dumps(value)
    assert not any(secret in text for secret in ('secret-onet','secret-usajobs','server-private','sk-fictional'))
    assert next(r for r in value['providers'] if r['id']=='onet')['configured']
    assert next(r for r in value['providers'] if r['id']=='openai')['status']=='saved_not_tested'
    assert not value['provider_checks_performed']

def test_welcome_dismissal_is_account_owned_idempotent_and_backup_compatible(client,fresh):
    assert client.get('/api/onboarding').json()['welcome_pending']
    first=client.post('/api/onboarding/welcome/dismiss').json();second=client.post('/api/onboarding/welcome/dismiss').json()
    assert first==second and first['welcome_dismissed_at'] and not first['welcome_pending']
    assert not first['completed'] and not credentials.get(fresh['id'])
    exported=client.get('/api/account/export').json()
    for r in exported['records']:
        if r['kind']=='onboarding':r['data'].pop('welcome_dismissed_at',None)
    imported=client.post('/api/account/import',files={'file':('old-backup.json',json.dumps(exported).encode(),'application/json')})
    assert imported.status_code==200,imported.text
    assert client.get('/api/onboarding').json()['welcome_dismissed_at']==first['welcome_dismissed_at']
    user=client.post('/api/auth/register',json={'username':'other-resource-user','password':'fictional-resource-password'}).json();client.headers['X-CSRF-Token']=user['csrf']
    assert client.get('/api/onboarding').json()['welcome_pending']

def test_general_interview_categories_need_key_not_education(client,fresh,monkeypatch):
    from app import ai,interview_practice as practice
    from test_interview_practice import wait,body
    calls=[]
    async def model(schema,payload,*args,**kwargs):
        calls.append(payload)
        return {'question':'Explain how you would learn a new topic and check your understanding.','topic':'General learning exercise','evaluation_focus':['Reasoning'],'constraints':[],'examples':[],'hints':[],'references':[]},{'model':'fictional-interview'}
    monkeypatch.setattr(ai,'structured',model)
    for kind in ('behavioral','star','coding','case','domain','presentation','other'):
        response=client.post('/api/interview-practice/sessions',json={'kind':kind,'title':'General practice','language':'Python'});assert response.status_code==200,response.text
        session=response.json()
        path='/api/interview-practice/sessions/'+session['id']+'/actions'
        if not calls:
            missing=client.post(path,json=body(session));assert missing.status_code==503
            credentials.save(fresh['id'],'sk-fictional-never-sent')
        result=wait(client,client.post(path,json=body(session)));assert result['status']=='completed',(kind,result)
        assert client.get('/api/interview-practice/sessions/'+session['id']).status_code==200
    assert len(calls)==7 and not onboarding.status(fresh['id'])['completed']

def test_general_skills_and_plans_with_empty_profile(client,fresh,monkeypatch):
    from app import ai
    from test_broader_career import wait
    from test_career_coach import wait as coach_wait
    credentials.save(fresh['id'],'sk-fictional-never-sent');monkeypatch.setattr(config,'ENABLE_WEB_SEARCH',False);calls=[]
    async def model(schema,payload,*args,**kwargs):
        calls.append(schema.__name__);assert kwargs['retry_allowed'] is False
        if schema.__name__=='PrepOutput':
            assert payload['reviewed_professional_profile']['sources']==[]
            return {'priorities':['Try a small Python exercise.'],'resource_ids':[payload['resource_catalog'][0]['id']],'questions':[]},{'model':'fictional'}
        assert payload['profile']['sources']==[]
        source=payload['retrieved_chunks'][0];citation=[{'chunk_id':source['chunk_id'],'quote':source['text'][:100]}]
        action={'kind':'project','title':'Try a small learning project','why':'Explore your interests.','steps':['Choose a fictional exercise','Reflect on what you learned'],'horizon':'30','effort':'Two hours','prerequisites':'Interest in learning','cost':'Free exploration','uncertainty':'Adjust the scope as you learn.','evidence':[],'citations':citation}
        return {'answer':'Explore your interests through a small project.','direction':'General exploration','recommendations':[action],'questions':[],'needs_fresh_research':False,'citations':citation,'profile_evidence':[]},{'model':'fictional'}
    monkeypatch.setattr(ai,'structured',model)
    result=wait(client,client.post('/api/preparation',json={'confirmed_gaps':['Python']}));assert result['status']=='completed',result
    assert client.get('/api/workspace').json()['prep']
    chat=client.post('/api/career-coach/chats',json={'goal':'Explore a career direction'}).json()
    response=client.post('/api/career-coach/chats/'+chat['id']+'/actions',json={'operation':'plan','request_token':'general-plan-request'})
    assert response.status_code==200,response.text
    result=coach_wait(client,response.json());assert result['status']=='completed',result.get('error')
    assert len(calls)==2 and not onboarding.status(fresh['id'])['completed']
