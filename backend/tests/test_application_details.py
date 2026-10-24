import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from app import db,documents,config
from test_application_documents import application,upload,pdf


def test_promote_existing_other_preserves_original_and_is_idempotent(client,account,monkeypatch):
    job,app=application(client);raw=pdf();response=upload(client,app,'other',raw=raw).json();document=response['document'];before=response['application']['data'];path='/api/applications/'+app['id']+'/documents/'+document['id']
    def no_extraction(*args,**kwargs):raise AssertionError('Promotion must not extract or generate content')
    monkeypatch.setattr(documents,'extract',no_extraction)
    request={'expected_updated_at':document['updated_at']}
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:client.post(path+'/use-as-resume',json=request),range(4)))
    results=[client.post(path+'/use-as-resume',json=request) if r.status_code==503 else r for r in results]
    assert all(r.status_code==200 for r in results),[r.text for r in results]
    value=results[0].json();rid=value['resume']['id'];assert {r.json()['resume']['id'] for r in results}=={rid}
    assert value['document']['data']['category']=='resume' and value['document']['data']['sha256']==document['data']['sha256']
    assert value['application']['data']['status']==before['status'] and value['application']['data']['submitted_resume_id']==before['submitted_resume_id']
    assert value['application']['data']['history']==before['history']
    assert len(db.list_entities(account['id'],'document'))==1 and len(db.list_entities(account['id'],'resume'))==1
    assert client.get(path+'/download').content==raw
    assert client.get('/api/resumes/'+rid+'/export/original').content==raw
    assert not value['resume']['data']['source_reviewed'] and not db.list_entities(account['id'],'usage_event')


def test_promotion_keeps_existing_submitted_version_and_backup_references(client,account):
    job,app=application(client);original=db.save(account['id'],'resume',{'title':'Submitted version','job_id':job['id']})
    data={**app['data'],'resume_ids':[original['id']],'submitted_resume_id':original['id'],'status':'applied','applied_date':'2026-10-20'}
    response=client.put('/api/applications/'+app['id'],json=data);assert response.status_code==200,response.text
    value=upload(client,response.json(),'other').json();document=value['document'];path='/api/applications/'+app['id']+'/documents/'+document['id']
    result=client.post(path+'/use-as-resume',json={'expected_updated_at':document['updated_at']}).json()
    assert result['application']['data']['submitted_resume_id']==original['id'] and result['application']['data']['status']=='applied'
    backup=client.get('/api/account/export').json();assert client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode())}).status_code==200
    assert len(db.list_entities(account['id'],'application'))==2


def test_promote_checks_owner_scope_version_and_original_file(client,account):
    _,app=application(client);value=upload(client,app,'other').json();document=value['document'];path='/api/applications/'+app['id']+'/documents/'+document['id']+'/use-as-resume'
    assert client.post(path,json={'expected_updated_at':'stale'}).status_code==409
    _,other=application(client)
    assert client.post('/api/applications/'+other['id']+'/documents/'+document['id']+'/use-as-resume',json={'expected_updated_at':document['updated_at']}).status_code==404
    file=config.DATA_DIR/'uploads'/account['id']/document['id'];file.write_bytes(b'changed file')
    assert client.post(path,json={'expected_updated_at':document['updated_at']}).status_code==409
    assert not db.list_entities(account['id'],'resume')


def test_application_save_conflicts_after_file_upload_and_can_retry_against_latest(client,account):
    _,app=application(client);value=upload(client,app,'other').json();data={**app['data'],'notes':'Unsaved note'}
    # URL encoding is done by the frontend; use params here because timestamps contain +.
    response=client.put('/api/applications/'+app['id'],params={'expected_updated_at':app['updated_at']},json=data)
    assert response.status_code==409
    current=client.get('/api/applications/'+app['id']).json();assert current['data']['notes']==app['data']['notes']
    data={**current['data'],'notes':'Unsaved note'};r=client.put('/api/applications/'+app['id'],params={'expected_updated_at':current['updated_at']},json=data);assert r.status_code==200,r.text
    assert r.json()['data']['notes']=='Unsaved note' and len(r.json()['data']['attachments'])==1


def test_promotion_cross_account_is_not_disclosed(client,account):
    from fastapi.testclient import TestClient
    from app.main import app as api
    from conftest import onboard_test_account
    _,app=application(client);document=upload(client,app,'other').json()['document']
    with TestClient(api,base_url='http://localhost') as outsider:
        u=outsider.post('/api/auth/register',json={'username':'outsider','password':'fictional-test-password'}).json();onboard_test_account(u);outsider.headers['X-CSRF-Token']=u['csrf']
        assert outsider.get('/api/applications/'+app['id']).status_code==404
        assert outsider.post('/api/applications/'+app['id']+'/documents/'+document['id']+'/use-as-resume',json={'expected_updated_at':document['updated_at']}).status_code==404
