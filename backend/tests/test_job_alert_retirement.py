import asyncio,json
import pytest
from app import db,job_alerts,job_search,main
from conftest import onboard_test_account

ENDPOINTS=[('PUT','/api/job-search/schedule'),('GET','/api/job-search/schedule'),('POST','/api/job-search/schedule'),('DELETE','/api/job-search/schedule'),('POST','/api/job-search/check-now'),('GET','/api/job-search/notifications'),('GET','/api/job-search/push-key'),('POST','/api/job-search/push'),('DELETE','/api/job-search/push'),('POST','/api/job-search/email/verify'),('POST','/api/job-search/email/confirm'),('GET','/api/job-search/alerts/2026-10-31/jobs')]

@pytest.mark.parametrize('method,path',ENDPOINTS)
def test_retired_endpoints_authenticate_then_refuse_all_execution(client,account,monkeypatch,method,path):
 calls=[]
 async def forbidden(*args,**kwargs):calls.append(args);raise AssertionError('No provider calls permitted')
 monkeypatch.setattr(job_search,'discover',forbidden)
 before=db.list_entities(account['id'],'job_alert')
 response=client.request(method,path,json={'enabled':True,'email':'fictional@example.org'})
 assert response.status_code==410,response.text
 assert 'retired' in response.json()['detail']
 assert db.list_entities(account['id'],'job_alert')==before and not calls
 client.cookies.clear();client.headers.pop('X-CSRF-Token',None)
 assert client.request(method,path,json={}).status_code==401

def test_enabled_legacy_schedules_survive_restart_as_inactive_data(client,account,monkeypatch):
 legacy=job_alerts.save(account['id'],'job_alert',job_alerts.Schedule(enabled=True,browser=True,email_enabled=True,email='fictional@example.org').model_dump())
 async def forbidden(*args,**kwargs):raise AssertionError('Retired schedules must not search')
 monkeypatch.setattr(job_search,'discover',forbidden)
 assert not any(hasattr(job_alerts,n) for n in ('scheduler','run_daily','deliver','email_api','push_key'))
 async def restart():
  async with main.lifespan(main.app):await asyncio.sleep(.01)
 asyncio.run(restart())
 assert db.get(account['id'],legacy['id'],'job_alert')==legacy
 data=client.get('/api/job-search/preferences').json()
 assert data['schedule']['data']['enabled'] is False
 assert not data['capabilities']['scheduler'] and not data['capabilities']['browser_push'] and not data['capabilities']['email']
 assert data['capabilities']['alerts_retired']

def test_legacy_backup_restores_search_and_jobs_but_cannot_reactivate_alerts(client,account):
 from app.models import SearchRequest
 prefs={'query':SearchRequest(interests=['Nursing','Marketing'],sources=['ashby']).model_dump()}
 assert client.put('/api/job-search/preferences',json=prefs).status_code==200
 job=db.save(account['id'],'job',{'title':'Fictional nurse','company':'Example','url':'https://example.org/nurse','interest_state':'saved'})
 legacy=job_alerts.save(account['id'],'job_alert',job_alerts.Schedule(enabled=True,browser=True,email_enabled=True,email='fictional@example.org').model_dump())
 backup=client.get('/api/account/export').json()
 assert any(r['id']==legacy['id'] for r in backup['records'])
 other=client.post('/api/auth/register',json={'username':'secondaccount','password':'fictional-other-password'}).json();onboard_test_account(other);client.headers['X-CSRF-Token']=other['csrf']
 assert db.list_entities(other['id'],'job')==[]
 assert client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup))}).status_code==200
 restored=db.list_entities(other['id'],'job_alert')[0]['data']
 assert not restored['enabled'] and not restored['email_enabled'] and not restored['browser']
 assert client.get('/api/job-search/preferences').json()['preferences']['data']['query']['interests']==['Nursing','Marketing']
 assert db.list_entities(other['id'],'job')[0]['data']['interest_state']=='saved'
 assert client.put('/api/job-search/jobs/'+job['id']+'/interest',json={'state':'none'}).status_code==404
 assert db.get(account['id'],legacy['id'],'job_alert')==legacy


def test_retirement_is_available_to_authenticated_accounts_before_setup(client):
 user=client.post('/api/auth/register',json={'username':'freshretirement','password':'fictional-retirement-password'}).json()
 client.headers['X-CSRF-Token']=user['csrf']
 for method,path in ENDPOINTS:
  assert client.request(method,path,json={}).status_code==410
