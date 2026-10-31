import asyncio,copy,json
import pytest
from app import db,home,linked_project_evidence as linked,resume_conversation as guided,resume_builder,optimization,ai
from app.models import ExperienceItem,ConversationStart

def stored(user):
    with db.connect() as c:return [tuple(r) for r in c.execute('SELECT * FROM entities WHERE user_id=? ORDER BY id',(user,))]

def experience(user,**kw):return db.save(user,'experience',ExperienceItem(confirmed=True,**kw).model_dump())

def test_automatic_relationships_keep_original_sources_and_one_location(client,account,monkeypatch):
    u=account['id'];intern=experience(u,category='employment',title='Intern',description='Worked with sponsors.')
    contractor=experience(u,category='employment',title='Contractor',description='Continued later testing.')
    edu=experience(u,category='education',title='MS',degree='MS',organization='Example University',relevant_courses='Data Systems')
    project=experience(u,category='project',title='Prototype',description='Built a local retrieval prototype.',contribution='Initially tested approximately 10 documents.',linked_employment_ids=[intern['id'],contractor['id']],linked_education_ids=[edu['id']],linked_courses=[{'education_id':edu['id'],'course':'Data Systems'}])
    posting=db.save(u,'job',{'title':'Analyst','description':'Build and test data systems.'});session=guided.start(u,ConversationStart(job_id=posting['id']))
    before=db.get(u,project['id'],'experience');source=guided.source(u,session['data']);rows=linked.entries(source)
    original=rows[project['id']]['content_items'];assert len(original)==2
    for target in (intern,contractor,edu):
        borrowed=[i for i in rows[target['id']]['content_items'] if i.get('project_source')]
        assert len(borrowed)==2
        assert all(i['project_source']['destination_id']==target['id'] and i['project_source']['original'] in [v['original'] for v in original] for i in borrowed)
    assert db.get(u,project['id'],'experience')==before
    selected=resume_builder.select(source,{rid:list(range(len(e['content_items']))) for rid,e in rows.items()},list(rows))
    origins=[(i['project_source']['project_id'],i['project_source']['item_id']) if i.get('project_source') else (rid,i['item_id']) for rid,e in linked.entries(selected).items() for i in e['content_items']]
    assert len(origins)==len(set(origins))
    assert sum(i['original']=='Initially tested approximately 10 documents.' for e in linked.entries(selected).values() for i in e['content_items'])==1
    db.save(u,'experience',{**project['data'],'linked_employment_ids':[contractor['id']]},project['id'])
    updated=guided.source(u,session['data']);assert not any(i.get('project_source') for i in linked.entries(updated)[intern['id']]['content_items'])
    assert any(i.get('project_source') for i in rows[intern['id']]['content_items']) # frozen source unchanged


def test_automatic_payload_source_labels_privacy_and_model_choice(client,account,monkeypatch):
    u=account['id'];job=experience(u,category='employment',title='Intern',description='Demonstrated tools.')
    p=experience(u,category='project',title='Workbench',description='Built a reusable scenario tool.',linked_employment_ids=[job['id']])
    posting=db.save(u,'job',{'title':'Developer','description':'Develop scenario tools.'});s=guided.start(u,ConversationStart(job_id=posting['id']));snapshot=guided.source(u,s['data'])
    db.update_settings(u,{'authorized_us':'yes','career_goals':'PRIVATE_GOALS_SENTINEL'})
    calls=[]
    async def model(schema,payload,*a,**kw):
        calls.append(payload)
        if schema.__name__=='DraftAudit':return {'approved':True,'issues':[]},{'estimated_token_cost_usd':0}
        rows=payload['catalog'];r=next(r for r in rows if r['id']==job['id']);i=next(i for i in r['items'] if i.get('project_source'))
        return {'headline':'','headline_evidence':[],'keywords':[],'omissions':[],'entries':[{'record_id':job['id'],'reason':'Relevant project under its linked role','items':[{'item_id':i['item_id'],'text':i['original'],'priority':80,'reason':'Relevant tool'}]}]},{'estimated_token_cost_usd':0}
    monkeypatch.setattr(ai,'structured',model);monkeypatch.setattr(resume_builder,'render',lambda s:(1,{}))
    result=asyncio.run(optimization.create(u,snapshot,None,'economy'))['data']
    assert result['experience_ids']==[job['id']]
    wire=json.dumps(calls);assert 'PRIVATE_GOALS_SENTINEL' not in wire and 'authorized_us' not in wire
    assert 'Saved links permit reuse without another placement approval' in wire
    assert 'internship versus contractor' in wire
    assert calls[1]['proposal']['entries'][0]['record_id']==job['id']


def test_home_empty_read_only_account_scope_and_partial_failure(client,account,monkeypatch):
    u=account['id'];before=stored(u)
    def forbidden(*a,**kw):pytest.fail('Home must not call a provider or mutate storage')
    monkeypatch.setattr(db,'save',forbidden);monkeypatch.setattr(ai,'structured',forbidden)
    result=client.get('/api/home').json();assert result['applications']==[] and result['plans']==[] and result['suggestions']['jobs']==[] and result['read_only']
    assert stored(u)==before
    monkeypatch.setattr(home,'plans',lambda *a:(_ for _ in ()).throw(ValueError('bad legacy record')))
    partial=client.get('/api/home').json();assert partial['plans'] is None and partial['usage'] is not None and 'plans' in partial['errors']


def test_home_bounded_continuation_plans_reviews_and_suggestions(client,account,monkeypatch):
    u=account['id'];apps=[]
    for n in range(6):
        j=db.save(u,'job',{'title':f'Role {n}','company':'Example','description':'Fictional job'})
        apps.append(db.save(u,'application',{'job_id':j['id'],'title':j['data']['title'],'status':'preparing'}))
    chat=db.save(u,'coach_chat',{'title':'My plan','goal':'Build skills','progress':{}})
    action={'id':'milestone','title':'Build','kind':'project','steps':['Learn SQL','Build pipeline']}
    old=db.save(u,'coach_plan',{'chat_id':chat['id'],'actions':[action],'version':1})
    plan=db.save(u,'coach_plan',{'chat_id':chat['id'],'actions':[action],'version':2})
    db.save(u,'coach_chat',{**chat['data'],'plan_id':plan['id']},chat['id'])
    experience(u,category='project',title='Needs description')
    active=db.save(u,'job',{'title':'New suggestion','url':'https://example.com/new','description':'Saved suggestion'})
    closed=db.save(u,'job',{'title':'Closed suggestion','source_closed_at':'2026-01-01T00:00:00Z'})
    db.save(u,'personalized_search',{'search_id':'saved','matches':[{'job_id':r} for r in (active['id'],closed['id'],apps[0]['data']['job_id'])],'checked_at':'2026-10-30T00:00:00Z'})
    before=stored(u);result=client.get('/api/home?visited='+apps[0]['id']).json()
    assert len(result['applications'])==4 and result['applications'][0]['id']==apps[0]['id']
    assert result['applications'][0]['preparation']['stage']=='posting'
    assert len(result['plans'])==1 and result['plans'][0]['id']==plan['id']
    assert result['plans'][0]['next_step']['text']=='Learn SQL' and result['plans'][0]['completed']==0
    assert result['suggestions']['jobs'][0]['id']==active['id'] and len(result['suggestions']['jobs'])==1
    assert len(result['profile'])<=3 and any('Needs description' in r['text'] for r in result['profile'])
    assert result['chart']['cohort_count']==6 and stored(u)==before
    other=client.post('/api/auth/register',json={'username':'other-home','password':'fictional-test-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
    result=client.get('/api/home?visited='+apps[0]['id']).json()
    assert result['applications']==[] and result['plans']==[] and result['suggestions']['jobs']==[]


def test_overlap_cleanup_preserves_distinct_quantities_and_limitations():
    assert linked.equivalent('Built a local retrieval prototype for roadway document review.','Built a local retrieval prototype for roadway document review.')
    assert not linked.equivalent('Tested the local retrieval prototype on 10 roadway documents.','Tested the local retrieval prototype on 300 roadway documents.')
    assert not linked.equivalent('Tested the local retrieval prototype with incomplete validation.','Tested the local retrieval prototype with complete validation.')


def test_home_chart_summary_is_bounded_without_applicant_detail_lists(client,account):
    result=client.get('/api/home').json()
    assert 'paths' not in result['chart'] and 'chart_dates' not in result['chart']
    assert len(result['chart']['submissions'])<=13


def test_automatic_supporting_detail_keeps_its_own_provenance(client,account):
    u=account['id'];role=experience(u,category='employment',title='Intern',description='Reviewed data.')
    project=experience(u,category='project',title='Prototype',description='Built a retrieval tool.',linked_employment_ids=[role['id']])
    answer=db.save(u,'profile_answer',{'status':'confirmed','answer_kind':'experience','experience_ids':[project['id']],'title':'Testing detail','text':'Tested approximately 10 documents with validation still incomplete.','version':3,'sources':[{'builder':'resume','user_quotes':['Tested approximately 10 documents with validation still incomplete.'],'reviewed_at':'2026-10-30'}]})
    posting=db.save(u,'job',{'title':'Analyst','description':'Review data.'});s=guided.start(u,ConversationStart(job_id=posting['id']));rows=linked.entries(guided.source(u,s['data']))
    borrowed=[i for i in rows[role['id']]['content_items'] if i.get('project_source')]
    detail=next(i for i in borrowed if '10 documents' in i['original'])
    assert detail['project_source']['reviewed_answer_sources'][0]['id']==answer['id']
    assert detail['project_source']['reviewed_answer_sources'][0]['version']==3
    ordinary=next(i for i in borrowed if i['original']=='Built a retrieval tool.')
    assert ordinary['project_source']['reviewed_answer_sources']==[]
