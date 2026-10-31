"""Multiple locations reuse the existing query model and never initiate discovery on save."""
import pytest
from app import ai,db,job_filters,job_search,network
from app.models import SearchRequest
from conftest import onboard_test_account

@pytest.mark.parametrize('location,expected',[
 ('Richmond, VA',True),('Boston, MA',True),('Seattle, WA',False),('Not stated',None),
])
def test_locations_are_or_with_unknowns_preserved(location,expected):
 request=SearchRequest(location='Richmond, VA',locations=['Richmond, VA','Boston, MA'])
 assert job_filters.location({'location':location},request) is expected

def test_multisite_posting_records_the_matching_location():
 job={'location':'Seattle, WA','locations':[{'location':'Boston, MA'}]}
 assert job_filters.location(job,SearchRequest(locations=['Virginia','Massachusetts'])) is True
 assert job['matching_location']=='Boston, MA'

def test_preferences_history_restore_and_isolation_without_provider_requests(client,account,monkeypatch):
 async def forbidden(*a,**k):raise AssertionError('Changing or viewing preferences must not search')
 monkeypatch.setattr(job_search,'discover',forbidden);monkeypatch.setattr(ai,'structured',forbidden);monkeypatch.setattr(network,'public_fetch',forbidden)
 places=['Richmond, VA','Boston, MA','West Coast']
 body={'account_id':account['id'],'query':{'title':'Data analyst','location':places[0],'locations':places,'sources':['ashby']},'job_type_mode':'manual'}
 response=client.put('/api/job-search/preferences',json=body);assert response.status_code==200,response.text
 restored=client.get('/api/job-search/preferences').json()['preferences']['data']
 assert restored['query']['locations']==places and restored['query']['location']==places[0]
 assert set(places)<=set(restored['location_history'])
 # Historical description-based searches also supply all their locations to the picker.
 db.save(account['id'],'search',{'query':{'location':'United States','locations':['Phoenix, AZ','Tucson, AZ']}})
 assert {'Phoenix, AZ','Tucson, AZ'}<=set(client.get('/api/job-search/preferences').json()['preferences']['data']['location_history'])
 other=client.post('/api/auth/register',json={'username':'other-locations','password':'fictional-location-password'}).json();onboard_test_account(other)
 assert client.get('/api/job-search/preferences').json()['preferences']['data']['location_history']==['United States']
 client.headers['X-CSRF-Token']=other['csrf']
 assert client.put('/api/job-search/preferences',json=body).status_code==409

def test_ten_location_limit_legacy_single_and_return_to_single(client,account):
 body={'query':{'title':'Analyst','location':'Boston, MA','locations':['Boston, MA','Virginia'],'sources':['ashby']}}
 assert client.put('/api/job-search/preferences',json=body).status_code==200
 body['query']['locations']=[]
 assert client.put('/api/job-search/preferences',json=body).status_code==200
 assert client.get('/api/job-search/preferences').json()['preferences']['data']['query']['locations']==[]
 body['query']['locations']=['City '+str(i) for i in range(11)]
 assert client.put('/api/job-search/preferences',json=body).status_code==422
