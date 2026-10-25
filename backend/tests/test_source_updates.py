import httpx,pytest
from app import updates
from test_updates_local import mock_github

@pytest.mark.parametrize('ancestry,state',[('ahead','source_available'),('behind','ahead'),('diverged','diverged'),('identical','up_to_date')])
def test_source_ancestry_no_credentials(client,monkeypatch,ancestry,state):
 calls=[]
 def handler(req):
  calls.append(str(req.url));assert req.url.host=='api.github.com'
  assert 'authorization' not in req.headers and 'cookie' not in req.headers and not req.content
  if str(req.url)==updates.SOURCE_API:return httpx.Response(200,json={'sha':'b'*40})
  assert str(req.url)==f'https://api.github.com/repos/{updates.REPOSITORY}/compare/'+('a'*40)+'...'+('b'*40)
  return httpx.Response(200,json={'status':ancestry,'ahead_by':2,'behind_by':1})
 mock_github(monkeypatch,handler)
 result=updates.check_source({'revision':'a'*40},{},10)
 assert result['state']==state and len(calls)==2

def test_source_unknown_build_and_exact_revision(client,monkeypatch):
 calls=[]
 mock_github(monkeypatch,lambda req:(calls.append(req) or httpx.Response(200,json={'sha':'b'*40})))
 assert updates.check_source({'revision':'unknown'},{},10)['state']=='unknown_build'
 assert updates.check_source({'revision':'b'*40},{},10)['state']=='up_to_date'
 assert updates.check_source({'revision':('b'*40)+'-dirty'},{},10)['state']=='unknown_build'
 assert len(calls)==3

def test_source_works_without_a_release(client,monkeypatch):
 monkeypatch.setattr(updates,'installed',lambda:{'version':'dev','revision':'a'*40,'channel':'source'})
 def handler(req):
  if str(req.url)==updates.API_URL:return httpx.Response(404)
  if str(req.url)==updates.SOURCE_API:return httpx.Response(200,json={'sha':'b'*40})
  return httpx.Response(200,json={'status':'ahead'})
 mock_github(monkeypatch,handler)
 result=updates.check()
 assert result['release_state']=='no_published_release' and result['source']['state']=='source_available'
 assert result['installed']['revision']=='a'*40 and result['latest'] is None

def test_source_errors_do_not_claim_current(client,monkeypatch):
 mock_github(monkeypatch,lambda req:httpx.Response(404))
 result=updates.check_source({'revision':'a'*40},{'revision':'b'*40,'checked_at':1},10)
 assert result['state']=='unable_to_check' and result['checked_at']==1
