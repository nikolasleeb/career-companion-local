"""Comparison consumes the current Profile without promoting draft/private context."""
import asyncio
import copy
import json
from app import ai,db,project_structure


def test_comparison_receives_current_scoped_profile_evidence(client,account,sample,monkeypatch):
    user=account['id']
    def experience(**values):
        response=client.post('/api/experience',json={'confirmed':True,**values})
        assert response.status_code==200,response.text
        return response.json()
    school=experience(category='education',title='MS Data Science',degree='MS',organization='Fictional University',relevant_courses='Cloud Data Systems')
    course=next(c for c in client.get('/api/profile-courses').json() if c['education_id']==school['id'])
    changed=client.put('/api/profile-courses/'+school['id']+'/'+course['id'],json={'expected_updated_at':school['updated_at'],'title':course['title'],'status':'completed'})
    assert changed.status_code==200,changed.text
    skills=experience(category='skills',title='Programming',skill_items=[{'name':'Python','level':'advanced'},{'name':'SQL','level':'intermediate'}])
    employment=experience(category='employment',title='Research Assistant',organization='Example Agency',description='Prepared research data.')
    project=experience(category='project',title='Pipeline Study',description='Built the initial pipeline.',linked_education_ids=[school['id']],linked_employment_ids=[employment['id']])
    def details(record,text,**scope):
        path='/api/experience/'+record['id']+'/supporting-details'
        current=client.get(path,params=scope).json()
        saved=client.put(path,json={'revision':current['revision'],'confirmed':True,'statements':[{'id':'new','text':text}],**scope})
        assert saved.status_code==200,saved.text
        return saved.json()['statements'][0]['id']
    details(school,'Built an Azure transformation pipeline for a short course assignment.',course_id=course['id'])
    details(skills,'Validated source rows and rejected invalid Python inputs.',skill_id=skills['data']['skill_items'][0]['id'])
    details(project,'Designed the pipeline validation checks.')
    draft=db.save(user,'profile_answer',{'status':'draft','answer_kind':'experience','title':'Unreviewed detail','text':'UNREVIEWED_SENTINEL','experience_ids':[project['id']]})
    db.update_settings(user,{'us_citizen':'yes','authorized_us':'yes','sponsorship_now':'no','sponsorship_future':'no'})
    before={r['id']:copy.deepcopy(r) for kind in ('experience','profile_answer') for r in db.list_entities(user,kind)}
    captured=[]
    async def structured(schema,payload,*args,**kwargs):
        captured.append(payload)
        return {'summary':'Fictional comparison.','requirements':[], 'duty_assessments':[], 'job_details':[], 'recommendations':[], 'suggestions':[], 'keywords':[], 'questions':[]},{}
    monkeypatch.setattr(ai,'structured',structured)
    result=asyncio.run(ai.analyze(user,sample['data'],'economy'))
    assert result['schema_version']==3 and len(captured)==1
    payload=captured[0];effective={r['id']:r['data'] for r in payload['retrieved'] if r['kind']=='experience'}
    assert 'Coursework — Cloud Data Systems (completed): Built an Azure transformation pipeline' in effective[school['id']]['contribution']
    assert 'Skill — Python: Validated source rows' in effective[skills['id']]['contribution']
    assert 'Skill — SQL: Validated source rows' not in json.dumps(payload)
    assert effective[project['id']]['relationship_context']
    assert effective[project['id']]['project_attribution'][0]['allowed_parent_ids']==project_structure.destinations(effective[project['id']]['project_attribution'][0]['scope'],project['data'])
    passages=payload['professional_evidence_catalog']
    assert any(p['record_id']==project['id'] and p['quote']=='Designed the pipeline validation checks.' for p in passages)
    assert any('Skill — Python:' in p['quote'] for p in passages)
    assert any('Coursework — Cloud Data Systems (completed):' in p['quote'] for p in passages)
    assert all(not p['record_id'].startswith('profile:') for p in passages)
    assert payload['private_eligibility_catalog'] and all(p['record_id'].startswith('profile:') for p in payload['private_eligibility_catalog'])
    assert 'UNREVIEWED_SENTINEL' not in json.dumps(payload)
    assert draft['id'] not in effective
    assert before=={r['id']:r for kind in ('experience','profile_answer') for r in db.list_entities(user,kind)}
