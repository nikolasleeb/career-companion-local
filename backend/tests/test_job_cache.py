"""Retention, public coverage and protected history; fictional records, no network."""
import asyncio,json,time
from datetime import datetime,timezone
import pytest
from app import db,config,job_cache as cache,job_results as results,public_job_feeds as feeds,integrations as x,job_search
from app.models import SearchRequest
from app.network import ServiceError
from conftest import onboard_test_account

def run(value):return asyncio.run(value)
def posting(i='one',**extra):return {'title':'Data Analyst','company':'Fictional Employer','location':'Richmond, VA','country':'US','url':'https://employer.example/jobs/'+i,'description':'Use SQL to analyze data. No experience required.','published_at':db.now(),'source_identity':'ashby:fictional:'+i,'origin_key':'ashby:fictional','hard_filter_status':'matches',**extra}
def save(user,data,stamp=None):
 row=db.save(user,'job',data)
 with db.connect() as c:
  if stamp is not None:c.execute('UPDATE entities SET created_at=? WHERE id=?',(cache.iso(stamp),row['id']));row['created_at']=cache.iso(stamp)
  cache.bind(c,user,row)
 return row

def search(user,rows):return results.save_search(user,{'jobs':rows,'query':SearchRequest(interests=['Data analysis'],sources=['ashby']).model_dump(),'sources':[]})
def page(client,s,view='all'):return client.get('/api/job-search/searches/'+s['id']+'/results?view='+view).json()

def test_thirty_day_boundary_read_never_reconfirms_and_old_search_filters(client,account,monkeypatch):
 now=time.time();r=save(account['id'],posting(),now-30*cache.DAY+1);s=search(account['id'],[r])
 assert page(client,s)['total']==1
 with db.connect() as c:before=dict(c.execute('SELECT * FROM cc_job_lifecycle').fetchone())
 assert client.get('/api/workspace').status_code==200
 with db.connect() as c:assert dict(c.execute('SELECT * FROM cc_job_lifecycle').fetchone())==before
 monkeypatch.setattr(cache.time,'time',lambda:now+2)
 assert page(client,s)['total']==0 and page(client,s,'archived')['total']==1
 assert page(client,s,'archived')['counts']['matches']==0
 assert results.public_search(account['id'],s)['data']['jobs']==[]
 assert cache.cleanup()['purged_posting_bodies']==1
 assert db.get(account['id'],r['id'],'job')['data']['cache_tombstone']
 assert cache.cleanup()['purged_posting_bodies']==0

def test_deadlines_date_only_timezone_and_dst():
 assert cache.deadline({'deadline':'2026-10-24'})==datetime(2026,10,25,tzinfo=timezone.utc).timestamp()
 # Closing day spans DST; derive next local midnight, never add a fixed 24h interval.
 assert cache.deadline({'deadline':'2026-11-01','deadline_timezone':'America/New_York'})==datetime(2026,11,2,5,tzinfo=timezone.utc).timestamp()
 assert cache.deadline({'deadline':'2026-11-01T12:30:00-07:00'})==datetime(2026,11,1,19,30,tzinfo=timezone.utc).timestamp()
 assert cache.deadline({'deadline':'unknown','validThrough':'2026-11-01'}) is not None
 assert cache.deadline({'deadline':'2026-11-01','deadline_timezone':'invalid'}) is None

def test_complete_partial_closure_reopening_and_old_confirmation(client,account):
 u=account['id'];t=time.time()-300;job=posting();cache.observe('ashby:fictional',[job],t,complete=True,authoritative=True);r=save(u,job);s=search(u,[r])
 cache.observe('ashby:fictional',[],t+50,complete=False,authoritative=True)
 assert page(client,s)['total']==1
 cache.observe('ashby:fictional',[],t+100,complete=True,authoritative=True)
 assert page(client,s)['total']==0
 cache.observe('github:community',[job],t+150)
 assert page(client,s)['total']==0 # mirror cannot reopen employer closure
 cache.observe('ashby:fictional',[job],t+200,complete=True,authoritative=True)
 assert page(client,s)['total']==1
 cache.observe('ashby:fictional',[{**job,'deadline':'2020-01-01'}],t,authoritative=True)
 assert page(client,s)['total']==1 # old snapshots cannot replace newer deadlines


def test_saved_application_resume_ai_evidence_and_orphan_cleanup(client,account):
 u=account['id'];old=time.time()-31*cache.DAY;rows=[save(u,posting(str(i)),old) for i in range(5)];s=search(u,rows)
 db.save(u,'job',{**rows[0]['data'],'interest_state':'saved'},rows[0]['id'])
 app=db.save(u,'application',{'job_id':rows[1]['id'],'status':'interview','notes':'Keep this'})
 resume=db.save(u,'resume',{'job_id':rows[2]['id'],'text':'Approved resume'})
 review=db.save(u,'ai_job_match',{'state':'completed','assessments':{rows[3]['id']:{'fit':'possible'}},'posting_versions':{rows[3]['id']:rows[3]['data']}})
 orphan=db.save(u,'job_snapshot',posting('orphan'))
 before={r['id']:r for r in [app,resume,review]};cache.cleanup()
 for r in rows[:4]:assert db.get(u,r['id'],'job')['data']['description']==r['data']['description']
 assert db.get(u,rows[4]['id'],'job')['data']['cache_tombstone']
 assert db.get(u,orphan['id'],'job_snapshot') is None
 assert client.get('/api/job-search/searches/saved/results?view=archived').json()['total']==1
 for id,r in before.items():assert db.get(u,id,r['kind'])==r
 # Existing applications remain intact even though expired jobs cannot start new ones.
 assert page(client,s)['total']==0
 assert len(results.all_rows(u,s['id']))==0


def test_public_cache_concurrent_accounts_partial_failure_and_clock(client,account,monkeypatch):
 calls=[];clock=[time.time()];monkeypatch.setattr(cache.time,'time',lambda:clock[0])
 async def provider(board,query):calls.append(board);await asyncio.sleep(.01);return x.BoardRows([posting()],complete=True)
 monkeypatch.setattr(x,'board_jobs',provider)
 a={'provider':'ashby','board':'fictional','company':'Account A private label'};b={**a,'company':'Account B private label'}
 async def both():return await asyncio.gather(feeds.employer(a),feeds.employer(b))
 one,two=run(both());assert len(calls)==1 and one[0][0]['company']!=two[0][0]['company']
 with db.connect() as c:
  public=c.execute('SELECT payload FROM cc_public_job_snapshots').fetchone()[0];verified=c.execute('SELECT verified_at FROM cc_job_observations').fetchone()[0]
 assert 'private label' not in public and account['id'] not in public
 clock[0]+=3*cache.DAY # outage must not confirm jobs again
 async def failure(*a,**k):raise ServiceError('Fictional outage')
 monkeypatch.setattr(x,'board_jobs',failure);rows,meta=run(feeds.employer(a));assert rows and meta['stale'] and meta['error']
 with db.connect() as c:assert c.execute('SELECT verified_at FROM cc_job_observations').fetchone()[0]==verified
 # A partial successful response does not erase the older body or refresh its clock.
 clock[0]+=61
 async def partial(*a):return x.BoardRows([posting('two')],complete=False)
 monkeypatch.setattr(x,'board_jobs',partial);rows,meta=run(feeds.employer(a))
 assert len(rows)==2 and next(v for v in rows if v['url'].endswith('/one'))['_last_verified_epoch']==verified


def test_usajobs_exact_coverage_shared_across_accounts_missing_queries_fetched(client,account,monkeypatch):
 calls=[]
 async def provider(q,location):calls.append((q,location));return [posting(q)]
 monkeypatch.setattr(job_search,'_usajobs_raw',provider)
 run(job_search.usajobs('analyst','Virginia'));run(job_search.usajobs('analyst','Virginia'))
 run(job_search.usajobs('engineering','Virginia'))
 assert len(calls)==2
 with db.connect() as c:assert c.execute('SELECT count(*) FROM cc_public_job_snapshots').fetchone()[0]==2


def test_private_imports_cannot_seed_public_or_reconfirm(client,account):
 u=account['id'];t=time.time()-31*cache.DAY
 imported=save(u,posting(_cache_scope='account',last_verified_at=cache.iso(t)))
 cache.migrate()
 with db.connect() as c:assert c.execute('SELECT count(*) FROM cc_job_observations').fetchone()[0]==0
 assert not cache.is_active(u,imported['id'])
 with pytest.raises(ValueError):cache.observe('adzuna',[posting()],time.time())
 cache.observe('adzuna',[posting()],time.time(),scope=u)
 other=client.post('/api/auth/register',json={'username':'cache-other','password':'fictional-password'}).json();onboard_test_account(other)
 r=save(other['id'],posting(_cache_scope='account',last_verified_at=cache.iso(t)))
 assert not cache.is_active(other['id'],r['id'])
 assert client.get('/api/job-search/searches/'+search(u,[imported])['id']+'/results').status_code==404


def test_policy_hosted_enforcement_local_choices_and_purged_no_resurrection(client,account,monkeypatch):
 monkeypatch.setattr(cache,'hosted',lambda:True)
 assert client.get('/api/settings/job-cache').json()['retention_days']==30
 assert client.put('/api/settings/job-cache',json={'retention_days':90}).status_code==403
 monkeypatch.setattr(cache,'hosted',lambda:False)
 for value in [1,7,14,30,60,90,365]:assert client.put('/api/settings/job-cache',json={'retention_days':value}).json()['retention_days']==value
 for value in [0,366,3.5,True,'7']:assert client.put('/api/settings/job-cache',json={'retention_days':value}).status_code==422
 client.put('/api/settings/job-cache',json={'retention_days':7});r=save(account['id'],posting(),time.time()-8*cache.DAY);s=search(account['id'],[r]);cache.cleanup()
 client.put('/api/settings/job-cache',json={'retention_days':90})
 assert page(client,s)['total']==0


def test_migration_preserves_snapshot_success_and_original_dates(client,account):
 u=account['id'];t=time.time()-35*cache.DAY
 with db.connect() as c:c.execute('INSERT INTO cc_public_job_snapshots VALUES(?,?,?,?,?,?)',('ashby:fictional',json.dumps([posting()]),'old-revision',t,t,''))
 row=db.save(u,'job',posting());
 with db.connect() as c:c.execute('UPDATE entities SET created_at=? WHERE id=?',(cache.iso(t),row['id']))
 cache.migrate();assert not cache.is_active(u,row['id'])
 with db.connect() as c:assert c.execute('SELECT verified_at FROM cc_job_lifecycle').fetchone()[0]==t
 cache.cleanup()
 with db.connect() as c:assert c.execute('SELECT count(*) FROM cc_public_job_snapshots').fetchone()[0]==0


def test_backup_restore_keeps_verification_closure_and_private_scope(client,account):
 u=account['id'];verified=time.time()-10*cache.DAY
 r=save(u,posting(interest_state='saved'),time.time()-40*cache.DAY)
 cache.observe('ashby:fictional',[r['data']],verified,authoritative=True)
 cache.observe('ashby:fictional',[],verified+60,complete=True,authoritative=True)
 s=search(u,[r]);backup=client.get('/api/account/export').json()
 exported=next(v for v in backup['records'] if v['id']==r['id'])
 assert cache.epoch(exported['data']['last_verified_at'])==pytest.approx(verified)
 assert cache.epoch(exported['data']['source_closed_at'])==pytest.approx(verified+60)
 other=client.post('/api/auth/register',json={'username':'restore-cache','password':'fictional-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
 response=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')})
 assert response.status_code==200,response.text
 imported=db.list_entities(other['id'],'job')[0]
 with db.connect() as c:
  row=c.execute('SELECT * FROM cc_job_lifecycle WHERE user_id=? AND job_id=?',(other['id'],imported['id'])).fetchone()
  assert row['scope']==other['id'] and row['verified_at']==pytest.approx(verified) and row['closed_at']==pytest.approx(verified+60)
  assert c.execute('SELECT count(*) FROM cc_job_observations WHERE scope=?',(other['id'],)).fetchone()[0]==0
 assert client.get('/api/job-search/searches/saved/results?view=archived').json()['total']==1
 assert db.get(other['id'],imported['id'],'job')['data']['description']==r['data']['description']
