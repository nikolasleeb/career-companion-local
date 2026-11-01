import copy,io,json,asyncio
import pytest
from docx import Document
from app import db,course_evidence,project_websites,project_sources,project_structure,master_resume,ai,credentials
from app.network import ServiceError
from test_profile_structure import entry,get,save


def test_append_classes_preserves_ids_status_evidence_and_connections(client,account):
 school=entry(client,'education','Study',relevant_courses='Cloud; Databases',degree='MS')
 old=[v for v in course_evidence.classes(school)];course=old[0]
 r=client.put(f"/api/profile-courses/{school['id']}/{course['id']}",json={'expected_updated_at':school['updated_at'],'title':'Cloud Systems','status':'completed'});assert r.status_code==200
 project=entry(client,'project','Cloud project',linked_courses=[{'education_id':school['id'],'course':'Cloud Systems'}])
 answer=client.post('/api/profile-answers',json={'title':'Class lab','text':'Configured a cloud service in a supervised lab.','experience_ids':[school['id']],'course_refs':[{'education_id':school['id'],'course_id':course['id']}],'confirmed':True,'request_token':'class-preserve'}).json()
 syllabus=client.post(f"/api/profile-courses/{school['id']}/{course['id']}/syllabi",files={'file':('syllabus.txt',b'Cloud Systems lab topics and the context of supervised assignments.','text/plain')}).json()
 school=db.get(account['id'],school['id']);url=f"/api/profile-courses/{school['id']}/add";body={'expected_updated_at':school['updated_at'],'titles':['cloud systems','Cloud','Databases','Networks',' networks ']}
 r=client.post(url,json=body);assert r.status_code==200,r.text;assert r.json()['added']==1
 courses=r.json()['courses'];assert [v['title'] for v in courses]==['Cloud Systems','Databases','Networks'];assert courses[0]['id']==course['id'];assert courses[0]['status']=='completed';assert courses[1]['id']==old[1]['id'];assert courses[2]['status']=='unspecified'
 assert db.get(account['id'],answer['id'])==answer;assert db.get(account['id'],syllabus['id'])==syllabus;assert db.get(account['id'],project['id'])==project
 assert client.post(url,json=body).status_code==409
 backup=client.get('/api/account/export').json();r=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')});assert r.status_code==200,r.text
 assert any(v['title']=='Networks' for v in client.get('/api/profile-courses').json())


def test_class_add_rejects_foreign_parent_and_invalid_names(client,account):
 school=entry(client,'education','Study',degree='BS');url=f"/api/profile-courses/{school['id']}/add";body={'expected_updated_at':school['updated_at'],'titles':['Invalid; two names']}
 assert client.post(url,json=body).status_code==422
 wrong=entry(client,'project','Project');assert client.post(f"/api/profile-courses/{wrong['id']}/add",json={**body,'titles':['Valid']}).status_code==404
 other=client.post('/api/auth/register',json={'username':'foreign-materials','password':'fictional-password-123'}).json();client.headers['X-CSRF-Token']=other['csrf']
 entry(client,'education','Other study',degree='BS')
 assert client.post(url,json={**body,'titles':['Valid']}).status_code==404


def test_project_link_save_is_narrow_versioned_and_owner_scoped(client,account):
 project=entry(client,'project','Tool',description='Original project text.',contribution='My contribution.')
 url=f"/api/experience/{project['id']}/project-links";body={'expected_updated_at':project['updated_at'],'urls':['https://example.com/tool']}
 r=client.put(url,json=body);assert r.status_code==200,r.text;value=r.json();expected=copy.deepcopy(project['data']);expected.update(project_url=body['urls'][0],project_urls=body['urls']);assert value['data']==expected
 assert client.put(url,json=body).status_code==409
 assert client.put(url,json={**body,'expected_updated_at':value['updated_at'],'urls':['http://name:password@example.com']}).status_code==400
 other=client.post('/api/auth/register',json={'username':'foreign-links','password':'fictional-password-123'}).json();client.headers['X-CSRF-Token']=other['csrf'];assert client.put(url,json=body).status_code==404


ROOT='https://sites.google.com/view/example-project/home'
PAGE='https://sites.google.com/view/example-project/design'
DOC='https://example.com/report.txt'
HTML=f'<html><title>Example project</title><main>Readable project introduction.</main><nav><a href="{PAGE}">Design</a><a href="{DOC}">Report</a><a href="/view/another-site/home">Other site</a><a href="http://127.0.0.1/admin">Private</a></nav><script>IGNORE THIS INSTRUCTION</script></html>'.encode()
def fake_website(monkeypatch):
 calls=[]
 async def fetch(url,max_bytes):
  calls.append(url)
  if url==ROOT:return {'status':200,'content':HTML,'content_type':'text/html','url':ROOT}
  if url==PAGE:return {'status':200,'content':b'<title>Design</title><main>Design choices and validation steps.</main>','content_type':'text/html','url':PAGE}
  if url==DOC:return {'status':200,'content':b'Documented inputs and validation results.','content_type':'text/plain','url':DOC}
  raise ServiceError('Only public addresses are permitted.')
 monkeypatch.setattr(project_websites,'public_fetch',fetch)
 async def forbidden(*a,**k):pytest.fail('Import called AI')
 monkeypatch.setattr(ai,'structured',forbidden)
 return calls


def test_website_discovery_is_bounded_selection_preview_and_save_make_no_ai(client,account,monkeypatch):
 calls=fake_website(monkeypatch);project=entry(client,'project','Website project')
 r=client.post('/api/project-sources/website',json={'urls':[ROOT],'experience_id':project['id']});assert r.status_code==200,r.text;source=r.json();assert calls==[ROOT]
 files=source['data']['available_files'];assert {f['website_url'] for f in files}=={ROOT,PAGE,DOC};assert 'IGNORE' not in files[0]['text']
 chosen=[f['file_path'] for f in files if f['website_url'] in (PAGE,DOC)]
 r=client.post(f"/api/project-sources/{source['id']}/website-preview",json={'file_paths':chosen});assert r.status_code==200,r.text;preview=r.json();assert set(calls)=={ROOT,PAGE,DOC};assert preview['id']!=source['id']
 assert all('text' in f for f in preview['data']['available_files']);assert 'text' not in db.get(account['id'],source['id'])['data']['available_files'][1]
 r=client.post(f"/api/project-sources/{preview['id']}/select",json={'file_paths':chosen,'experience_id':project['id']});assert r.status_code==200,r.text;snapshot=r.json();assert len(snapshot['data']['files'])==2;assert set(calls)=={ROOT,PAGE,DOC}
 assert all(f['url'] in (PAGE,DOC) for f in snapshot['data']['files']);assert db.list_entities(account['id'],'project_analysis')==[]
 backup=client.get('/api/account/export').json();r=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')});assert r.status_code==200,r.text
 imported=next(v for v in db.list_entities(account['id'],'project_snapshot') if v['id']!=snapshot['id']);assert db.get(account['id'],imported['data']['source_id'],'project_source')


def test_website_errors_retain_source_and_snapshots(client,account,monkeypatch):
 fake_website(monkeypatch);source=client.post('/api/project-sources/website',json={'urls':[ROOT]}).json();before=copy.deepcopy(source)
 async def unavailable(*a,**k):raise ServiceError('Page unavailable')
 monkeypatch.setattr(project_websites,'public_fetch',unavailable)
 chosen=[f['file_path'] for f in source['data']['available_files'] if f['website_url']==PAGE]
 r=client.post(f"/api/project-sources/{source['id']}/website-preview",json={'file_paths':chosen});assert r.status_code==200,r.text;assert r.json()['data']['available_files'][1]['read_error']=='Page unavailable'
 assert db.get(account['id'],source['id'])==before
 r=client.post('/api/project-sources/website',json={'urls':[ROOT]});assert r.status_code==200,r.text;assert r.json()['data']['excluded']
 assert client.post(f"/api/project-sources/{source['id']}/select",json={'file_paths':['unknown.html']}).status_code==400


def test_website_account_isolation_and_reference_validation(client,account,monkeypatch):
 fake_website(monkeypatch);project=entry(client,'project','Private source');source=client.post('/api/project-sources/website',json={'urls':[ROOT],'experience_id':project['id']}).json()
 row=copy.deepcopy(source);row['kind']='project_source';row['data']['available_files'][0]['website_url']='https://sites.google.com/view/other/home'
 from app.project_routes import validate_backup
 with pytest.raises(ValueError):validate_backup(row,{project['id']:'experience'},{project['id']:project})
 other=client.post('/api/auth/register',json={'username':'other-web-reader','password':'fictional-password-123'}).json();client.headers['X-CSRF-Token']=other['csrf']
 body={'file_paths':[source['data']['available_files'][0]['file_path']]}
 assert client.post(f"/api/project-sources/{source['id']}/select",json=body).status_code==404
 assert client.post(f"/api/project-sources/{source['id']}/website-preview",json=body).status_code==404
 assert client.post('/api/project-sources/website',json={'urls':[ROOT],'experience_id':project['id']}).status_code==404


def test_public_page_redirect_boundary_and_text_limits(monkeypatch):
 async def redirected(*a,**k):return {'status':200,'content':HTML,'content_type':'text/html','url':'https://sites.google.com/view/other/home'}
 monkeypatch.setattr(project_websites,'public_fetch',redirected)
 with pytest.raises(ServiceError,match='outside'):asyncio.run(project_websites.read(project_websites.candidate(ROOT,ROOT)))
 async def big(*a,**k):return {'status':200,'content':b'<main>'+b'x'*300000+b'</main>','content_type':'text/html','url':ROOT}
 monkeypatch.setattr(project_websites,'public_fetch',big);file,_=asyncio.run(project_websites.read(project_websites.candidate(ROOT,ROOT)));assert file['truncated'];assert len(file['text'].encode())==project_sources.MAX_FILE
 assert not project_websites.same_site('https://sites.google.com/view/example-project-extra/page',ROOT)
 with pytest.raises(ServiceError):project_websites.canonical('http://user:pass@example.com')


def test_legacy_single_parent_edit_preserves_identity_and_split_uses_sole_parent(client,account):
 job=entry(client,'employment','Role');p=entry(client,'project','Tool',linked_employment_ids=[job['id']],description='Built the prototype.\nDocumented results.')
 current=get(client,p);assert save(client,current).status_code==200
 old=get(client,p);identity=old['data']['project_statements'][0]['id'];old['data']['description']='Built the improved prototype.\nDocumented results.'
 assert save(client,old).status_code==200
 changed=get(client,p);assert changed['data']['project_statements'][0]['id']==identity
 changed['data']['description']='Built one part.\nBuilt another part.\nDocumented results.';assert save(client,changed).status_code==200
 final=get(client,p);assert all(project_structure.permits(v['scope'],final['data'],job['id']) for v in final['data']['project_statements'][:2])


def test_course_export_regular_names_and_details_no_status_or_syllabus(client,account):
 school=entry(client,'education','Study',degree='MS',relevant_courses='Cloud; Databases');course=course_evidence.classes(school)[0]
 client.put(f"/api/profile-courses/{school['id']}/{course['id']}",json={'expected_updated_at':school['updated_at'],'title':'Cloud','status':'completed'})
 url=f"/api/experience/{school['id']}/supporting-details";state=client.get(url,params={'course_id':course['id']}).json()
 text='I built a cloud pipeline and verified the transformation outputs.'
 r=client.put(url,json={'revision':state['revision'],'confirmed':True,'course_id':course['id'],'statements':[{'id':'detail','text':text}]});assert r.status_code==200
 client.post(f"/api/profile-courses/{school['id']}/{course['id']}/syllabi",files={'file':('syllabus.txt',b'PRIVATE SYLLABUS CONTENT must stay out of the exported document.','text/plain')})
 value=master_resume.snapshot(account['id']);doc=Document(io.BytesIO(master_resume.render_docx(value)));paragraphs={p.text:p for p in doc.paragraphs}
 assert not any(r.bold for r in paragraphs['Cloud'].runs);assert not any(r.bold for r in paragraphs[text].runs)
 assert paragraphs[text].paragraph_format.left_indent>paragraphs['Cloud'].paragraph_format.left_indent
 assert not any('completed' in p.text or 'PRIVATE SYLLABUS' in p.text or 'Relevant classes:' in p.text for p in doc.paragraphs)
 assert course_evidence.listing(account['id'])[0]['status']=='completed'


def test_saved_website_snapshot_uses_existing_mocked_analysis_workflow(client,account,monkeypatch):
 fake_website(monkeypatch);source=client.post('/api/project-sources/website',json={'urls':[ROOT]}).json();path=source['data']['available_files'][0]['file_path']
 snap=client.post(f"/api/project-sources/{source['id']}/select",json={'file_paths':[path]}).json();calls=[]
 async def mocked(schema,payload,mode,**kw):
  calls.append(payload);return {'summary':'Project introduction is documented.','findings':[{'file_path':path,'quote':'Readable project introduction.','evidence_kind':'text','observation':'The website documents the introduction.'}]},{'model':'mock','estimated_token_cost_usd':0}
 monkeypatch.setattr(ai,'structured',mocked)
 value=asyncio.run(project_sources.analyze(account['id'],snap['id'],'economy'))
 assert len(calls)==1;assert value['analysis']['data']['findings'][0]['quote']=='Readable project introduction.'
 assert not db.list_entities(account['id'],'profile_answer')
 assert db.get(account['id'],snap['id'])==snap


def test_website_redirect_revalidates_public_address_before_second_connection(monkeypatch):
 from app import network
 import socket
 hosts=[]
 monkeypatch.setattr(socket,'getaddrinfo',lambda host,*a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1' if host=='private.example' else '93.184.216.34',80))])
 class Response:
  status=302
  def getheader(self,key,default=''):return 'http://private.example/secret' if key=='Location' else default
 class Connection:
  def __init__(self,host,*a,**k):hosts.append(host)
  def request(self,*a,**k):pass
  def getresponse(self):return Response()
  def close(self):pass
 monkeypatch.setattr(network.http.client,'HTTPSConnection',Connection);monkeypatch.setattr(network.http.client,'HTTPConnection',Connection)
 with pytest.raises(ServiceError,match='public'):network.safe_fetch('https://public.example/home')
 assert hosts==['public.example']


def test_website_preview_total_limit_does_not_replace_prior_source(client,account,monkeypatch):
 fake_website(monkeypatch);source=client.post('/api/project-sources/website',json={'urls':[ROOT]}).json()
 data=source['data'];data['available_files']=[{**data['available_files'][0],'file_path':f'page-{i}.html','website_url':ROOT+f'?page={i}','text':'x'*project_sources.MAX_FILE} for i in range(10)]+[{**data['available_files'][1],'file_path':'extra.html'}]
 source=db.save(account['id'],'project_source',data);before=copy.deepcopy(source)
 r=client.post(f"/api/project-sources/{source['id']}/website-preview",json={'file_paths':['extra.html']});assert r.status_code==200,r.text
 # Existing text plus a short preview fits; a larger eleventh page cannot replace the source.
 async def large(*a,**k):return {'status':200,'content':b'<main>'+b'z'*project_sources.MAX_FILE+b'</main>','content_type':'text/html','url':PAGE}
 monkeypatch.setattr(project_websites,'public_fetch',large)
 r=client.post(f"/api/project-sources/{source['id']}/website-preview",json={'file_paths':['extra.html']});assert r.status_code==400
 assert db.get(account['id'],source['id'])==before
