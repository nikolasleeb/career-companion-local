import copy
import hashlib
import json
from pathlib import Path
import pytest
from fastapi import HTTPException
from app import ai,db,work_style,work_style_neo as neo,profile_answers


def ratings(value=3):return {q['id']:value for q in neo.catalog()['items']}
def payload(version=1,answers=None,**kw):return {'expected_version':version,'answers':answers if answers is not None else ratings(), 'page':0,**kw}
def start(client):return client.post('/api/work-style').json()
def finish(client,row,**kw):return client.post('/api/work-style/'+row['id']+'/score',json=payload(row['data']['version'],**kw))


def test_complete_published_catalog_and_key():
    cat=neo.catalog();items=cat['items'];facets=cat['facets']
    assert len(items)==len({q['id'] for q in items})==120
    assert len(facets)==30 and all(len(f['items'])==4 for f in facets)
    assert len(cat['dimensions'])==5 and cat['page_size']==8
    assert sum(not q['positive'] for q in items)==55
    assert next(q for q in items if q['id']=='N1-1')['text']=='Worry about things.'
    assert next(q for q in items if q['id']=='O6-1')['text']=='Tend to vote for liberal political candidates.'
    assert all(not q['positive'] for q in items if q['facet_id']=='C6')
    # Pin every bundled statement, facet and sign against the inspected official source.
    source=Path(neo.__file__).with_name('ipip_neo120.json').read_bytes()
    assert hashlib.sha256(source).hexdigest()=='c9db3afc31ba30720251db6cdd819e85b622681aa88dabc05164ef90546f996d'
    assert len(cat['comparisons'])==12 and len({p['theme'] for p in cat['comparisons']})==6
    cat['items'][0]['text']='changed'
    assert neo.catalog()['items'][0]['text']!='changed'


def test_published_scoring_high_low_neutral_and_independent_preferences():
    cat=neo.catalog();high={q['id']:5 if q['positive'] else 1 for q in cat['items']}
    top=neo.score(high,{})
    assert [x['total'] for x in top['facets']]==[20]*30
    assert [x['total'] for x in top['domains']]==[120]*5
    low=neo.score({k:6-v for k,v in high.items()},{})
    assert [x['total'] for x in low['facets']]==[4]*30
    assert [x['total'] for x in low['domains']]==[24]*5
    mid=neo.score(ratings(),{})
    assert [x['mean'] for x in mid['facets']+mid['domains']]==[3]*35
    left=neo.score(ratings(),{'p1':'left'});right=neo.score(ratings(),{'p1':'right'})
    assert left['domains']==right['domains']==mid['domains'] and left['facets']==right['facets']
    assert left['preferences'][0]['selected']!=right['preferences'][0]['selected']
    assert not mid['preferences']


@pytest.mark.parametrize('answer,comp', [({'foreign':3},{}),({'N1-1':True},{}),({'N1-1':0},{}),({'N1-1':6},{}),({}, {'p13':'left'}),({}, {'p1':'middle'})])
def test_invalid_responses(answer,comp):
    with pytest.raises(HTTPException) as error:neo.validate(answer,comp)
    assert error.value.status_code==422


def test_autosave_conflicts_missing_completion_retake_and_privacy(client,account,monkeypatch):
    async def forbidden(*a,**kw):raise AssertionError('Private scoring never calls AI')
    monkeypatch.setattr(ai,'structured',forbidden);monkeypatch.setattr(ai,'call_api',forbidden)
    cat=client.get('/api/work-style/catalog').json();assert cat['version']==neo.VERSION
    row=start(client);assert start(client)['id']==row['id']
    url='/api/work-style/'+row['id'];body=payload(1,{'N1-1':4},comparison_answers={'p1':'left'},page=16)
    saved=client.put(url+'/progress',json=body);assert saved.status_code==200
    assert client.put(url+'/progress',json=body).status_code==409
    incomplete=client.post(url+'/score',json=payload(2,{'N1-1':4}));assert incomplete.status_code==400
    stored=next(r for r in client.get('/api/work-style').json() if r['id']==row['id'])
    assert stored['data']['answers']=={'N1-1':4} and stored['data']['comparison_answers']=={'p1':'left'}
    result=client.post(url+'/score',json=payload(2,comparison_answers={}));assert result.status_code==200
    data=result.json()['data'];assert len(data['report']['facets'])==30 and not data['report']['preferences']
    assert data['catalog']==cat and data['status']=='completed'
    assert client.put(url+'/progress',json=payload(3)).status_code==409
    assert start(client)['id']!=row['id']
    assert profile_answers.confirmed(account['id'])==[]
    evidence=client.get('/api/profile-evidence').json()
    assert not any(r.get('kind')=='work_style' for r in evidence)
    assert not db.list_entities(account['id'],'story_prompts') and not db.list_entities(account['id'],'answer_draft') and not db.list_entities(account['id'],'usage_event')


def test_legacy_draft_and_completed_history_stay_usable(client,account):
    cat=work_style.legacy_catalog();old=db.save(account['id'],'work_style',{'version':1,'catalog_version':work_style.VERSION,'catalog':cat,'status':'draft','answers':{},'page':0,'scores':[]})
    new=start(client);assert new['id']!=old['id'] and db.get(account['id'],old['id'],'work_style')==old
    answer={str(i):3 for i in range(1,51)}
    complete=client.post('/api/work-style/'+old['id']+'/score',json=payload(1,answer,page=4));assert complete.status_code==200
    data=complete.json()['data'];assert data['scores']==work_style.score(answer) and 'report' not in data and data['catalog']==cat
    assert client.put('/api/work-style/'+old['id']+'/progress',json=payload(2,answer)).status_code==409


def test_private_report_backup_restore_and_tamper_detection(client,account):
    row=start(client);result=finish(client,row,comparison_answers={'p2':'right'});assert result.status_code==200
    backup=client.get('/api/account/export').json()
    restored=client.post('/api/account/import',files={'file':('private.json',json.dumps(backup),'application/json')})
    assert restored.status_code==200,restored.text
    assert len(db.list_entities(account['id'],'work_style'))==2
    records=db.list_entities(account['id'],'work_style');assert records[0]['data']['report']==records[1]['data']['report']
    bad=copy.deepcopy(backup);next(r for r in bad['records'] if r['kind']=='work_style')['data']['report']['domains'][0]['mean']=99
    assert client.post('/api/account/import',files={'file':('bad.json',json.dumps(bad),'application/json')}).status_code==400
    assert len(db.list_entities(account['id'],'work_style'))==2


def test_assessment_ownership_and_csrf(client,account):
    row=start(client)
    other=client.post('/api/auth/register',json={'username':'other_person','password':'fictional-password-123'}).json();client.headers['X-CSRF-Token']=other['csrf']
    assert client.get('/api/work-style').json()==[]
    assert client.put('/api/work-style/'+row['id']+'/progress',json=payload()).status_code==404
    assert finish(client,row).status_code==404
    client.headers.pop('X-CSRF-Token')
    assert client.post('/api/work-style').status_code==403
