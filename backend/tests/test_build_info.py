import json
import pytest
from app import config,build_info,onboarding

def test_version_requires_authentication(client):
    assert client.get('/api/version').status_code==401

def test_version_available_before_education_setup_and_not_cached(client,tmp_path,monkeypatch):
    client.post('/api/auth/register',json={'username':'new-student','password':'fictional-test-password'})
    monkeypatch.setattr(config,'STATIC_DIR',tmp_path)
    identity='a'*32
    (tmp_path/'build-info.json').write_text(json.dumps({'build_id':identity}))
    response=client.get('/api/version')
    assert response.status_code==200
    assert response.json()=={'build_id':identity}
    assert 'no-store' in response.headers['cache-control']
    assert response.headers['vary']=='Cookie'
    assert not onboarding.restricted('/api/version')

@pytest.mark.parametrize('content',['not json','[]','null','{"build_id":123}','{"build_id":"private-path"}'])
def test_missing_or_invalid_build_metadata_does_not_invent_an_update(tmp_path,monkeypatch,content):
    monkeypatch.setattr(config,'STATIC_DIR',tmp_path)
    assert build_info.current() is None
    (tmp_path/'build-info.json').write_text(content)
    assert build_info.current() is None

def test_html_revalidates_after_a_deployment(client,tmp_path,monkeypatch):
    monkeypatch.setattr(config,'STATIC_DIR',tmp_path)
    (tmp_path/'index.html').write_text('<html>fictional build</html>')
    for path in ('/','/index.html','/some-page'):
        assert client.get(path).headers['cache-control']=='no-cache'
