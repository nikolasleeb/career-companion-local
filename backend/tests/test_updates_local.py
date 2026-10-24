import json
from pathlib import Path
import httpx
import pytest
from app import updates, db


def release(version='1.0.1'):
    return {'tag_name': 'v'+version, 'draft': False, 'prerelease': False,
            'published_at': '2026-01-01T00:00:00Z', 'assets': [
                {'name': name, 'state': 'uploaded'} for name in (
                    'compose.localhost.yaml', 'SHA256SUMS',
                    f'career-companion-{version}-linux-amd64.tar.gz',
                    f'career-companion-{version}-linux-arm64.tar.gz')]}


@pytest.fixture
def image(monkeypatch):
    monkeypatch.setattr(updates, 'installed', lambda: {'version': '1.0.0', 'revision': 'a'*40, 'built_at': '', 'channel': 'release', 'edition': 'localhost'})


def mock_github(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr(updates.httpx, 'Client', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))


def test_update_check_is_authenticated_and_csrf_protected(client):
    assert client.get('/api/updates').status_code == 401
    assert client.post('/api/updates/check', json={}).status_code == 401
    user = client.post('/api/auth/register', json={'username': 'updater', 'password': 'fictional-password'}).json()
    assert client.get('/api/updates').status_code == 200
    assert client.post('/api/updates/check', json={}).status_code == 403


def test_available_update_sends_no_account_information(client, account, image, monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        assert str(request.url) == updates.API_URL
        assert not request.content and 'authorization' not in request.headers and 'cookie' not in request.headers
        return httpx.Response(200, json=release(), headers={'etag': 'fixture'})
    mock_github(monkeypatch, handler)
    result = client.post('/api/updates/check', json={}).json()
    assert result['state'] == 'update_available'
    assert result['latest']['version'] == '1.0.1'
    assert result['latest']['url'].endswith('/releases/tag/v1.0.1')
    assert len(calls) == 1
    client.post('/api/updates/check', json={'force': True})
    assert len(calls) == 1
    assert not db.list_entities(account['id'], 'usage_event')
    assert b'update-check' not in client.get('/api/account/export').content


@pytest.mark.parametrize('version,state', [('1.0.0','up_to_date'), ('0.9.9','ahead'), ('1.0.0.1','update_available'), ('1.0.10','update_available')])
def test_numeric_versions(client, account, image, monkeypatch, version, state):
    mock_github(monkeypatch, lambda req: httpx.Response(200, json=release(version)))
    assert updates.check()['state'] == state


def test_custom_build_does_not_claim_release_equivalence(client, monkeypatch):
    monkeypatch.setattr(updates, 'installed', lambda: {'version':'dev','channel':'custom'})
    mock_github(monkeypatch, lambda req: httpx.Response(200, json=release()))
    assert updates.check()['state'] == 'custom'


@pytest.mark.parametrize('change', [lambda r: r.update(draft=True), lambda r: r.update(prerelease=True), lambda r: r.update(assets=[]), lambda r: r.update(tag_name='v1.0.2-rc1'), lambda r: r.update(html_url='https://evil.example') or r.update(tag_name='../../evil')])
def test_incomplete_and_untrusted_releases_are_rejected(client, image, monkeypatch, change):
    value = release(); change(value)
    mock_github(monkeypatch, lambda req: httpx.Response(200, json=value))
    result = updates.check()
    assert result['state'] == 'unable_to_check' and result['latest'] is None


@pytest.mark.parametrize('code', [401,403,404,429,500])
def test_errors_preserve_previous_information_and_do_not_claim_current(client, image, monkeypatch, code):
    updates._save({'latest':{'version':'1.0.0','url':updates.RELEASES_URL+'/tag/v1.0.0'},'checked_at':1})
    mock_github(monkeypatch, lambda req: httpx.Response(code))
    result = updates.check()
    assert result['state'] == 'unable_to_check' and result['stale']
    assert result['latest']['version'] == '1.0.0' and result['checked_at'] == 1
    assert not result['needs_check']


def test_daily_cache_and_conditional_refresh(client, image, monkeypatch):
    now = 200000
    monkeypatch.setattr(updates.time, 'time', lambda: now)
    updates._save({'latest':{'version':'1.0.0','url':updates.RELEASES_URL},'checked_at':now-100,'etag':'original'})
    calls=[]
    def handler(req):
        calls.append(req); assert req.headers['if-none-match']=='original'
        return httpx.Response(304)
    mock_github(monkeypatch, handler)
    assert updates.check()['state']=='up_to_date' and not calls
    now += updates.DAY
    result=updates.check()
    assert len(calls)==1 and not result['stale'] and result['checked_at']==now


def test_timeout_and_bad_json_do_not_expose_response_data(client, image, monkeypatch):
    def handler(req): raise httpx.ReadTimeout('fixture', request=req)
    mock_github(monkeypatch, handler)
    assert updates.check()['state']=='unable_to_check'
    updates._save({})


@pytest.mark.parametrize('host', ['remote.example','localhost.evil.example','192.0.2.4','user@localhost','localhost:99999'])
def test_nonlocal_hosts_are_rejected(client, host):
    assert client.get('/api/health', headers={'host':host}).status_code==403


@pytest.mark.parametrize('headers', [{'Forwarded':'host=localhost'}, {'X-Forwarded-Host':'localhost'}, {'X-Forwarded-For':'127.0.0.1'}, {'Via':'fixture'}])
def test_forwarding_cannot_enable_remote_mode(client, headers):
    assert client.get('/api/health', headers=headers).status_code==403


@pytest.mark.parametrize('host', ['localhost','localhost:3002','127.0.0.1:3000','[::1]:3000'])
def test_loopback_hosts_work(client, host):
    assert client.get('/api/health', headers={'host':host}).status_code==200


def test_cross_origin_mutations_are_rejected(client):
    assert client.post('/api/auth/register', headers={'Origin':'https://other.example'}, json={'username':'localuser','password':'fictional-password'}).status_code==403


def test_localhost_compose_does_not_publish_lan_or_mount_machine_files():
    import os
    root=Path(os.getenv('CAREER_TEST_SOURCE', str(Path(__file__).resolve().parents[2])))
    for name in ('compose.yaml','compose.localhost.yaml'):
        text=(root/name).read_text()
        assert '127.0.0.1:${PORT:-3000}:3000' in text
        assert 'account_data:/data' in text and 'private_vault_key:/secrets' in text
        assert 'docker.sock' not in text and 'network_mode' not in text
