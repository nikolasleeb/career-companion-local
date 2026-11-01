import copy,io,json
from datetime import date
from docx import Document
from app import db,course_evidence as courses,master_resume,project_structure as structure
from test_profile_structure import entry,get,save
from test_profile_timeline_cleanup import add_detail


def test_completion_defaults_and_calendar_boundaries():
 def record(**values):return {'id':'school','updated_at':'v','data':{'category':'education','relevant_courses':'A; B',**values}}
 for end,today,expected in [('2025-05',date(2025,5,31),'unspecified'),('2025-05',date(2025,6,1),'completed'),('2025',date(2025,12,31),'unspecified'),('2025',date(2026,1,1),'completed'),('2025-05-04',date(2025,5,4),'unspecified'),('2025-05-04',date(2025,5,5),'completed')]:
  assert courses.classes(record(end_date=end),today=today)[0]['status']==expected
 assert courses.classes(record(expected_graduation='May 2025'),today=date(2025,6,1))[0]['status']=='completed'
 assert courses.classes(record(end_date='2027-05',expected_graduation='2025-05'),today=date(2026,1,1))[0]['status']=='unspecified'
 assert courses.classes(record(),today=date(2026,1,1))[0]['status']=='unspecified'
 assert courses.classes(record(end_date='Present',expected_graduation='2025-05'),today=date(2026,1,1))[0]['status']=='unspecified'


def test_fifty_existing_classes_default_without_mutating_stored_records(client,account):
 school=entry(client,'education','Degree',degree='BS',end_date='2020-05',relevant_courses='; '.join('Class '+str(i) for i in range(50)))
 before=copy.deepcopy(db.get(account['id'],school['id']))
 rows=[v for v in client.get('/api/profile-courses').json() if v['education_id']==school['id']]
 assert len(rows)==50 and all(v['status']=='completed' and v['status_source']=='education_dates' for v in rows)
 assert db.get(account['id'],school['id'])==before
 response=client.post('/api/profile-courses/'+school['id']+'/add',json={'expected_updated_at':before['updated_at'],'titles':['New class','Class 1']})
 assert response.status_code==200,response.text
 assert response.json()['added']==1 and all(v['status']=='completed' for v in response.json()['courses'])
 assert all(v['status']=='unspecified' for v in db.get(account['id'],school['id'])['data']['course_items'])
 assert {v['id'] for v in rows}<={v['id'] for v in response.json()['courses']}


def test_explicit_status_save_list_reopen_stale_and_old_save_metadata(client,account):
 school=entry(client,'education','Degree',degree='BS',end_date='2020-05',relevant_courses='A; B')
 target=next(v for v in client.get('/api/profile-courses').json() if v['education_id']==school['id'])
 url='/api/profile-courses/'+school['id']+'/'+target['id']
 for status in ['planned','in_progress','completed','unspecified']:
  old=copy.deepcopy(target)
  response=client.put(url,json={'expected_updated_at':target['parent_updated_at'],'title':target['title'],'status':status})
  assert response.status_code==200,response.text
  target=response.json();assert target['status']==status and target['status_override'] is True
  assert next(v for v in client.get('/api/profile-courses').json() if v['id']==target['id'])['status']==status
  stale=client.put(url,json={'expected_updated_at':old['parent_updated_at'],'title':'Do not overwrite','status':'completed'})
  assert stale.status_code==409
 current=get(client,school);del current['data']['course_items'][0]['status_override']
 assert save(client,current).status_code==200
 stored=next(v for v in db.get(account['id'],school['id'])['data']['course_items'] if v['id']==target['id'])
 assert stored['status_override'] is True and stored['status']=='unspecified'
 # Generic legacy editors omitting the additive class list also retain overrides.
 data={**school['data'],'title':'Renamed degree'};data.pop('course_items',None)
 assert client.put('/api/experience/'+school['id'],json=data).status_code==200
 assert next(v for v in client.get('/api/profile-courses').json() if v['id']==target['id'])['status']=='unspecified'


def test_legacy_explicit_statuses_win_and_backup_preserves_raw_defaults(client,account):
 school=entry(client,'education','Degree',degree='BS',end_date='2020-05',relevant_courses='A; B; C')
 current=get(client,school);rows=courses.classes(db.get(account['id'],school['id']),effective=False)
 current['data']['course_items']=[{k:v for k,v in row.items() if k in ('id','title','aliases','status')} for row in rows]
 current['data']['course_items'][0]['status']='planned';current['data']['course_items'][1]['status']='in_progress'
 current['data']['course_items'][2]['status_override']=True
 assert save(client,current).status_code==200
 response=client.get('/api/account/export');assert response.status_code==200
 payload=response.json();saved=next(v for v in payload['records'] if v['id']==school['id'])['data']['course_items']
 assert [v['status'] for v in saved]==['planned','in_progress','unspecified']
 client.post('/api/auth/logout');user=client.post('/api/auth/register',json={'username':'round2-import','password':'fictional-test-password'}).json();client.headers['X-CSRF-Token']=user['csrf']
 imported=client.post('/api/account/import',files={'file':('backup.json',response.content,'application/json')});assert imported.status_code==200,imported.text
 statuses=[v['status'] for v in client.get('/api/profile-courses').json() if v['education_title']=='Degree']
 assert statuses==['planned','in_progress','unspecified']
 imported_school=next(v for v in db.list_entities(user['id'],'experience') if v['data'].get('title')=='Degree')
 assert imported_school['data']['course_items'][2]['status_override'] is True
 assert client.put('/api/profile-courses/'+school['id']+'/'+rows[0]['id'],json={'title':'Stolen','status':'completed','expected_updated_at':school['updated_at']}).status_code==404


def test_pending_summary_names_counts_resolution_and_owner_isolation(client,account):
 school=entry(client,'education','School',degree='BS');job=entry(client,'employment','Job')
 project=entry(client,'project','Shared pending tool',linked_education_ids=[school['id']],linked_employment_ids=[job['id']],description='Built the tool.\nEvaluated the tool.')
 detail=add_detail(client,project,'Investigated the processing failure and recorded the result.')
 simple=entry(client,'project','Simple tool',linked_education_ids=[school['id']],description='Built another tool.')
 response=client.get('/api/profile/master-resume').json();pending=response['pending_project_assignments']
 assert pending==[{'project_id':project['id'],'title':'Shared pending tool','overview_count':2,'detail_count':1}]
 assert response['pending_projects']==len(pending)
 current=get(client,project)
 for row in current['data']['project_statements']:row['scope']={'kind':'project','stage_ids':[]}
 assert save(client,current).status_code==200
 assert client.get('/api/profile/master-resume').json()['pending_project_assignments'][0]['overview_count']==0
 url='/api/experience/'+project['id']+'/supporting-details';state=client.get(url).json()
 assert client.put(url,json={'revision':state['revision'],'confirmed':True,'statements':[]}).status_code==200
 assert client.get('/api/profile/master-resume').json()['pending_projects']==0
 archived=db.get(account['id'],detail['statements'][0]['id'],'profile_answer')
 db.save(account['id'],'profile_answer',{**archived['data'],'status':'draft','text':'Unreviewed detail should not create assignment work.'})
 assert client.get('/api/profile/master-resume').json()['pending_projects']==0
 client.post('/api/auth/logout');user=client.post('/api/auth/register',json={'username':'round2-other','password':'fictional-test-password'}).json()
 assert client.get('/api/profile/master-resume').json()['pending_project_assignments']==[]


def test_certifications_separate_export_order_and_project_month_dates(client,account):
 skill=entry(client,'skills','Programming',skill_items=[{'name':'Python','level':'unknown'}])
 cert=entry(client,'skills','Cloud certification',certification_items=[{'name':'Cloud Credential','issuer':'Example','credential_url':'https://example.com/verify'}])
 school=entry(client,'education','Degree',degree='BS')
 project=entry(client,'project','Single project',linked_education_ids=[school['id']],start_date='2020-01-12',end_date='2020-05-25',description='Built the project.')
 before=db.get(account['id'],project['id']);snapshot=master_resume.snapshot(account['id']);blocks=snapshot['blocks']
 titles=[v['text'] for v in blocks if v['kind']=='section'];assert titles[-2:]==['Skills','Certifications']
 assert 'Skills and Certifications' not in titles
 assert sum(v['text']=='Python' for v in blocks)==1
 assert any('Cloud Credential' in v['text'] for v in blocks)
 assert any(v['text']=='January 2020 – May 2020' for v in blocks)
 assert db.get(account['id'],project['id'])==before
 document=Document(io.BytesIO(master_resume.render_docx(snapshot)))
 assert 'Certifications' in [v.text for v in document.paragraphs]
 assert master_resume.project_month('2020')=='2020'
 assert master_resume.project_dates({'dates':'January 12, 2020 – May 25, 2020'})=='January 2020 – May 2020'


def test_completion_defaults_use_owner_timezone_not_server_day(client,account,monkeypatch):
 from datetime import datetime,timezone
 class Clock(datetime):
  instant=datetime(2025,6,1,0,30,tzinfo=timezone.utc)
  @classmethod
  def now(cls,tz=None):return cls.instant.astimezone(tz) if tz else cls.instant.replace(tzinfo=None)
 monkeypatch.setattr(courses,'datetime',Clock)
 db.update_settings(account['id'],{'usage_timezone':'America/Phoenix'})
 school=entry(client,'education','Phoenix degree',degree='BS',end_date='2025-05',relevant_courses='Calendar class')
 row=next(v for v in client.get('/api/profile-courses').json() if v['education_id']==school['id'])
 assert row['status']=='unspecified'
 assert courses.account_today(account['id']).isoformat()=='2025-05-31'
 assert courses.account_today(now=Clock.instant).isoformat()=='2025-06-01'
 # Saving just the name before Phoenix midnight must return the local status.
 response=client.put('/api/profile-courses/'+school['id']+'/'+row['id'],json={'expected_updated_at':row['parent_updated_at'],'title':row['title'],'status':'unspecified'})
 assert response.status_code==200 and response.json()['status']=='unspecified'
 assert response.json()['status_override'] is True
 Clock.instant=datetime(2025,6,1,7,0,tzinfo=timezone.utc)
 assert courses.account_today(account['id']).isoformat()=='2025-06-01'
 assert next(v for v in client.get('/api/profile-courses').json() if v['id']==row['id'])['status']=='unspecified'
 added=client.post('/api/profile-courses/'+school['id']+'/add',json={'expected_updated_at':response.json()['parent_updated_at'],'titles':['Later class']})
 assert added.status_code==200
 assert next(v for v in added.json()['courses'] if v['title']=='Later class')['status']=='completed'
 # A separate account at the same UTC instant has its own configured date.
 client.post('/api/auth/logout');other=client.post('/api/auth/register',json={'username':'tokyo-calendar','password':'fictional-test-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
 db.update_settings(other['id'],{'usage_timezone':'Asia/Tokyo'});Clock.instant=datetime(2025,6,1,0,30,tzinfo=timezone.utc)
 other_school=entry(client,'education','Tokyo degree',degree='BS',expected_graduation='2025-05',relevant_courses='Calendar class')
 assert next(v for v in client.get('/api/profile-courses').json() if v['education_id']==other_school['id'])['status']=='completed'
 assert courses.classes(db.get(account['id'],school['id']))[1]['status']=='unspecified'


def test_timezone_calendar_year_and_exact_day_boundaries(client,account,monkeypatch):
 from datetime import datetime,timezone
 class Clock(datetime):
  instant=datetime(2025,1,1,0,30,tzinfo=timezone.utc)
  @classmethod
  def now(cls,tz=None):return cls.instant.astimezone(tz) if tz else cls.instant.replace(tzinfo=None)
 monkeypatch.setattr(courses,'datetime',Clock)
 db.update_settings(account['id'],{'usage_timezone':'America/Phoenix'})
 record={'id':'school','user_id':account['id'],'updated_at':'v','data':{'category':'education','end_date':'2024','relevant_courses':'Class'}}
 assert courses.classes(record)[0]['status']=='unspecified'
 Clock.instant=datetime(2025,1,1,7,0,tzinfo=timezone.utc)
 assert courses.classes(record)[0]['status']=='completed'
 record['data']['end_date']='2025-06-12';Clock.instant=datetime(2025,6,13,6,59,tzinfo=timezone.utc)
 assert courses.classes(record)[0]['status']=='unspecified'
 Clock.instant=datetime(2025,6,13,7,0,tzinfo=timezone.utc)
 assert courses.classes(record)[0]['status']=='completed'
 assert courses.classes(record,effective=False)[0]['status']=='unspecified'
