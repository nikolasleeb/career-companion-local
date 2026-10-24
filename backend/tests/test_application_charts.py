"""All application stages share one bounded, provenance-aware chart cohort."""
import copy
import pytest
from app import ai,applications,db


def entry(id,status='applied',applied='',added='2026-10-22T02:00:00+00:00',**more):
 return {'id':id,'created_at':added,'data':{'title':id,'status':status,'applied_date':applied,'history':[],'interviews':[],**more}}


def test_every_status_and_archived_entry_counts_once_in_range():
 rows=[entry(str(i),status,'2026-10-20',history=[{'status':'screening'},{'status':'interviewing'}],interviews=[{},{}]) for i,status in enumerate(applications.STAGES)]
 rows.append(entry('archived','rejected','2026-10-20',archived=True));before=copy.deepcopy(rows)
 result=applications.dashboard(rows,'2026-01-01','2026-12-31','month',include_archived=True)
 assert result['cohort_count']==10 and sum(b['count'] for b in result['submissions'])==10
 assert set(result['paths'])=={r['id'] for r in rows} and result['paths']['0']==['preparing']
 assert sum(n['count'] for n in result['nodes'] if n['id'] in ('applied','preparing'))==10
 assert result['counts']['preparing']==1 and result['counts']['submitted']==9
 assert rows==before
 assert applications.dashboard(rows,'2026-01-01','2026-12-31','month')['cohort_count']==9


def test_real_application_date_wins_and_added_fallback_obeys_local_timezone():
 rows=[entry('unknown'),entry('known',applied='2026-10-22'),entry('preparing','preparing')]
 result=applications.dashboard(rows,'2026-10-21','2026-10-21','week','America/Phoenix')
 assert result['cohort_count']==2 and set(result['added_date_ids'])=={'unknown','preparing'}
 assert result['chart_dates']['unknown']=={'date':'2026-10-21','source':'added'}
 assert 'known' not in result['paths']
 result=applications.dashboard(rows,'2026-10-22','2026-10-22','week','America/Phoenix')
 assert result['chart_dates']=={'known':{'date':'2026-10-22','source':'applied'}}
 assert result['applied_date_count']==1
 assert all(not r['data']['applied_date'] for r in rows if r['id']!='known')


def test_all_entries_within_inclusive_range_and_no_outside_entries():
 rows=[entry('start',applied='2026-01-01'),entry('end',applied='2026-12-31'),entry('before',applied='2025-12-31'),entry('after',applied='2027-01-01'),entry('added-in',added='2026-06-01T00:00:00Z'),entry('added-out',added='2025-01-01T00:00:00Z')]
 result=applications.dashboard(rows,'2026-01-01','2026-12-31','month')
 assert set(result['paths'])=={'start','end','added-in'} and sum(b['count'] for b in result['submissions'])==3
 assert len(result['submissions'])==12 and sum(b['count']==0 for b in result['submissions'])==9


@pytest.mark.parametrize('period',['week','month'])
def test_full_leap_year_with_zero_buckets_and_no_applications(period):
 result=applications.dashboard([],'2024-01-01','2024-12-31',period)
 assert result['cohort_count']==0 and all(b['count']==0 for b in result['submissions'])
 assert len(result['submissions'])==(53 if period=='week' else 12)
 assert result['submissions'][0]['date']=='2024-01-01'


def test_missing_all_dates_is_explicit_and_does_not_guess_today():
 result=applications.dashboard([entry('missing',added='invalid')],'2026-01-01','2026-12-31','month')
 assert result['missing_date_ids']==['missing'] and result['cohort_count']==0 and not result['chart_dates']


def test_dashboard_api_scoped_read_only_and_full_year(client,account,monkeypatch):
 uid=account['id'];mine=db.save(uid,'application',entry('mine','preparing')['data'])
 def forbidden(*a,**kw):raise AssertionError('Charts must never call a provider')
 monkeypatch.setattr(ai,'structured',forbidden)
 result=client.get('/api/applications/dashboard?start=2026-01-01&end=2026-12-31&period=month&include_archived=true&timezone_name=America%2FPhoenix')
 assert result.status_code==200,result.text
 value=result.json();assert mine['id'] in value['chart_dates'] and value['paths'][mine['id']]==['preparing']
 assert db.get(uid,mine['id'],'application')==mine
 assert len(value['submissions'])==12
 other=client.post('/api/auth/register',json={'username':'another-chart-user','password':'fictional-chart-password'}).json()
 db.save(other['id'],'application',entry('theirs',applied='2026-01-02')['data'])
 from conftest import onboard_test_account
 onboard_test_account(other)
 client.headers['X-CSRF-Token']=other['csrf']
 assert client.get('/api/applications/dashboard?start=2026-01-01&end=2026-12-31').json()['cohort_count']==1


@pytest.mark.parametrize('query',['start=2025-01-01&end=2026-12-31','start=2026-12-31&end=2026-01-01','start=2026-02-30&end=2026-03-01','timezone_name=not-a-real-zone'])
def test_invalid_chart_ranges_and_timezone_fail_clearly(client,account,query):
 assert client.get('/api/applications/dashboard?'+query).status_code==422
