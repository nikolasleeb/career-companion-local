import json,time,hashlib
from pathlib import Path
import pytest
from app import db,credentials,account_cleanup as cleanup,private_profile,career_goals,work_preferences

def preview(client,categories,**extra):
 r=client.post('/api/account/cleanup/preview',json={'categories':categories,**extra});assert r.status_code==200,r.text;return r.json()
def apply(client,p,**extra):
 return client.post('/api/account/cleanup/apply',json={'preview_id':p['preview_id'],'confirmation':'DELETE' if p['action']=='delete' else 'CONFIRM','password':'correct horse battery staple',**extra})
def fix_password(client,user):
 from app import auth
 with db.connect() as c:c.execute('UPDATE users SET password=? WHERE id=?',(auth.hasher.hash('correct horse battery staple'),user))

def test_preview_clear_goals_personal_preserves_identity_keys_costs_and_welcome(client,account):
 u=account['id'];fix_password(client,u);credentials.save(u,'sk-fictional-preserve');db.update_settings(u,{'name':'Fictional Person','custom_model':'gpt-6.1-sol'})
 client.post('/api/onboarding/welcome/dismiss');before=client.get('/api/onboarding').json()['welcome_dismissed_at']
 career_goals.save(u,career_goals.Change(text='Explore science',use_for_ai=True,expected_revision=0));cost=db.save(u,'usage_event',{'public':'preserve'})
 p=preview(client,['personal','goals']);assert p['personal_fields'] and p['records']
 assert career_goals.read(u)['text'];r=apply(client,p);assert r.status_code==200,r.text
 assert not career_goals.context(u)['use_for_ai'] and not career_goals.read(u)['items'];assert credentials.get(u)=='sk-fictional-preserve'
 assert db.get(u,cost['id']);assert db.settings(u).get('name','')=='';assert db.settings(u)['custom_model']=='gpt-6.1-sol'
 me=client.get('/api/me').json();assert me['id']==u and me['cleanup_revision']==1
 assert client.get('/api/onboarding').json()['welcome_dismissed_at']==before
 assert apply(client,p).json()==r.json()
 assert client.put('/api/settings',json={'name':'stale'}).status_code==409
 client.headers['X-Account-Data-Revision']='1';assert client.put('/api/settings',json={'name':'current'}).status_code==200

def test_clear_education_relocks_apps_but_not_resources_and_keeps_historical_copy(client,account):
 u=account['id'];fix_password(client,u);school=db.list_entities(u,'experience')[0]
 story=db.save(u,'profile_answer',{'status':'confirmed','answer_kind':'experience','text':'Historical text','experience_id':school['id'],'experience_ids':[school['id']],'backed_fields':{'description':'Historical text'}})
 doc=db.save(u,'resume',{'title':'Independent saved copy','sections':[]});p=preview(client,['profile:education']);r=apply(client,p);assert r.status_code==200,r.text
 assert not client.get('/api/me').json()['onboarding']['completed'];assert client.get('/api/applications').status_code==403
 assert client.get('/api/career-coach/chats').status_code==200;assert db.get(u,doc['id'])
 assert db.get(u,story['id'])['data']['status']=='archived'
 assert client.get('/api/account/cleanup').status_code==200

def test_stale_expired_wrong_password_and_foreign_previews(client,account):
 u=account['id'];fix_password(client,u);db.update_settings(u,{'name':'Fictional'});p=preview(client,['personal']);assert apply(client,p,password='wrong').status_code==403
 db.update_settings(u,{'name':'changed'});assert apply(client,p).status_code==409
 p=preview(client,['personal']);
 with db.connect() as c:c.execute('UPDATE cc_cleanup_operations SET expires_at=? WHERE id=?',(time.time()-1,p['preview_id']))
 assert apply(client,p).status_code==409
 other=client.post('/api/auth/register',json={'username':'other-cleanup','password':'fictional-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
 assert apply(client,p).status_code==404;assert client.get('/api/account/cleanup/'+p['preview_id']).status_code==404

def test_active_task_and_run_block_cleanup_without_cancelling(client,account):
 u=account['id'];fix_password(client,u);p=preview(client,['personal'])
 with db.connect() as c:c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',('busy',u,'preparation','cancelling','{}','',db.now(),db.now()))
 assert apply(client,p).status_code==409
 with db.connect() as c:assert c.execute('SELECT status FROM tasks WHERE id=?',('busy',)).fetchone()[0]=='cancelling'

def test_application_archive_restore_and_date_boundaries(client,account):
 u=account['id'];fix_password(client,u)
 a=db.save(u,'application',{'title':'Summer','status':'applied','applied_date':'2026-06-01','archived':False,'attachments':[]})
 b=db.save(u,'application',{'title':'Autumn','status':'applied','applied_date':'2026-09-01','archived':False,'attachments':[]})
 p=preview(client,['applications'],action='archive',start='2026-06-01',end='2026-08-31');assert [r['id'] for r in p['records']]==[a['id']]
 assert apply(client,p).status_code==200;assert db.get(u,a['id'])['data']['archived'] and not db.get(u,b['id'])['data']['archived']
 client.headers['X-Account-Data-Revision']='1';p=preview(client,['applications'],action='restore',application_scope='archived');assert apply(client,p).status_code==200
 assert not db.get(u,a['id'])['data']['archived']

def test_exclusive_files_queued_shared_files_retained_and_retry(client,account,monkeypatch):
 from app import config
 u=account['id'];fix_password(client,u);folder=config.DATA_DIR/'uploads'/u;folder.mkdir(parents=True)
 a=db.save(u,'application',{'title':'One','archived':False});b=db.save(u,'application',{'title':'Two','archived':False})
 exclusive=db.save(u,'document',{'filename':'exclusive.pdf','purpose':'application','application_id':a['id']});shared=db.save(u,'document',{'filename':'shared.pdf','purpose':'application','application_id':a['id']})
 for r in (exclusive,shared):(folder/r['id']).write_bytes(b'fictional file')
 db.save(u,'application',{**b['data'],'attachments':[{'kind':'document','record_id':shared['id']}]},b['id'])
 p=preview(client,['applications']);# Both current applications selected: make second outside selected dates.
 db.save(u,'application',{**db.get(u,b['id'])['data'],'applied_date':'2025-01-01'},b['id'])
 p=preview(client,['applications'],start='2026-01-01');assert exclusive['id'] in p['files'] and shared['id'] in p['preserved_shared_records']
 r=apply(client,p);assert r.status_code==200,r.text;assert (folder/exclusive['id']).exists();assert db.get(u,shared['id'])
 original=Path.unlink
 def fail(path,*a,**kw):
  if path.name==exclusive['id']:raise OSError('fictional failure')
  return original(path,*a,**kw)
 with monkeypatch.context() as m:m.setattr(Path,'unlink',fail);cleanup.remove_files();assert client.get('/api/account/cleanup/'+p['preview_id']).json()['files_pending']==1
 cleanup.remove_files();assert not (folder/exclusive['id']).exists() and (folder/shared['id']).exists()
 assert client.get('/api/account/cleanup/'+p['preview_id']).json()['files_pending']==0

def test_private_and_work_style_cleanup_disables_consent_and_scrubs_recovery(client,account):
 u=account['id'];fix_password(client,u)
 db.update_settings(u,{'us_citizen':'yes'})
 from app.work_preferences import identity
 db.save(u,'work_preferences',{'revision':2,'summary':'I enjoy a clear plan.','preferences':[],'use_for_ai':True,'reviewed':True,'coach_report_access':True},identity(u))
 db.save(u,'work_style',{'status':'completed','answers':{'secret':'private'}})
 with db.connect() as c:c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',('old',u,'preparation','completed',json.dumps({'secret':'recovery copy'}),'',db.now(),db.now()))
 p=preview(client,['private','work_summary','work_assessments']);assert p['private_sections'];assert apply(client,p).status_code==200
 assert not work_preferences.context(u)['preferences'];assert not db.list_entities(u,'work_style')
 with db.connect() as c:
  assert not c.execute('SELECT * FROM cc_private_profile WHERE user_id=?',(u,)).fetchall()
  assert 'recovery copy' not in c.execute('SELECT result FROM tasks WHERE id=?',('old',)).fetchone()[0]

@pytest.mark.parametrize('category,kind,data',[
 ('profile:employment','experience',{'category':'employment','title':'Role','confirmed':True}),
 ('profile:project','experience',{'category':'project','title':'Project','confirmed':True}),
 ('profile:volunteering','experience',{'category':'volunteering','title':'Volunteer','confirmed':True}),
 ('profile:skills','experience',{'category':'skills','title':'Skills','confirmed':True}),
 ('profile:coursework','experience',{'category':'coursework','title':'Course','confirmed':True}),
 ('profile:certifications','experience',{'category':'skills','title':'Certificate','certification_items':[{'name':'Fictional'}],'confirmed':True}),
 ('supporting','answer_draft',{'title':'Draft','status':'draft'}),('uploads','project_snapshot',{'label':'Source','text':'retained only if unselected'}),
 ('documents','cover_revision',{'title':'Letter'}),('document_conversations','resume_conversation',{'title':'Resume chat'}),('careers','saved_career',{'title':'Career'}),('plans','coach_plan',{'title':'Plan'}),
 ('coach','assistant_message',{'content':'Conversation'}),('interviews','interview_voice',{'reviewed_transcript':'Reviewed words'}),('skills','prep',{'title':'Skills plan'}),('jobs','ai_search',{'prompt':'search history'})])
def test_each_cleanup_category_removes_only_selected_owned_records(client,account,category,kind,data):
 u=account['id'];fix_password(client,u);selected=db.save(u,kind,data);retained=db.save(u,'board',{'company':'Unselected preferences','provider':'lever','board':'fictional-kept'})
 p=preview(client,[category]);assert selected['id'] in p['record_ids'] and retained['id'] not in p['record_ids'];assert apply(client,p).status_code==200
 assert not db.get(u,selected['id']) and db.get(u,retained['id'])

def test_old_approved_proposal_cannot_recreate_cleared_supporting_detail(client,account):
 from app import profile_answers
 u=account['id'];fix_password(client,u)
 old=db.save(u,'profile_answer',{'title':'Old detail','text':'I checked a dataset.','status':'confirmed'})
 conversation=db.save(u,'resume_conversation',{'version':1,'job_id':'old-posting','questions':[],'asked_questions':[],'proposals':[{'id':'old-proposal','status':'approved','profile_answer_id':old['id'],'category':'project','approved_values':{'description':'I checked a dataset.'}}]})
 p=preview(client,['supporting']);assert apply(client,p).status_code==200
 profile_answers.migrate(u);assert not db.list_entities(u,'profile_answer');assert db.get(u,conversation['id'])['data']['proposals'][0]['cleanup_unavailable']

def test_shared_posting_preserved_and_old_task_recovery_is_unavailable(client,account):
 u=account['id'];fix_password(client,u);db.save(u,'search',{'title':'Old search history'});job=db.save(u,'job',{'title':'Saved posting'});app=db.save(u,'application',{'job_id':job['id'],'title':'Kept application','archived':False})
 with db.connect() as c:c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',('cleanup-old-result',u,'preparation','completed',json.dumps({'_task_result':{'secret':'historical recovery'}}),'',db.now(),db.now()))
 p=preview(client,['jobs']);assert job['id'] in p['preserved_shared_records'];assert apply(client,p).status_code==200
 assert db.get(u,job['id']) and db.get(u,app['id']);assert client.get('/api/tasks/cleanup-old-result').status_code==410

def test_document_conversations_are_a_separate_historical_copy_choice(client,account):
 u=account['id'];fix_password(client,u);document=db.save(u,'resume',{'title':'Independent resume'});chat=db.save(u,'resume_conversation',{'title':'Retained writing conversation'})
 p=preview(client,['documents']);assert document['id'] in p['record_ids'] and chat['id'] not in p['record_ids'];assert apply(client,p).status_code==200
 assert db.get(u,chat['id']) and not db.get(u,document['id'])

def test_empty_selection_does_not_invalidate_recovery_and_daily_history_is_clearable(client,account):
 u=account['id'];fix_password(client,u)
 assert client.post('/api/account/cleanup/preview',json={'categories':[]}).status_code==422
 p=preview(client,['goals']);assert apply(client,p).status_code==422;assert client.get('/api/me').json()['cleanup_revision']==0
 with db.connect() as c:c.execute('INSERT INTO cc_job_alert_runs VALUES(?,?,?,?,?)',(u,'2026-10-28','done',0,json.dumps({'new_jobs':[]})))
 p=preview(client,['jobs']);assert p['search_history_counts']['cc_job_alert_runs']==1;assert apply(client,p).status_code==200
 with db.connect() as c:assert not c.execute('SELECT 1 FROM cc_job_alert_runs WHERE user_id=?',(u,)).fetchone()


def test_file_worker_retries_temporary_database_failure(monkeypatch):
 import asyncio
 calls=[]
 def remove():
  calls.append(1)
  if len(calls)==1:raise OSError('temporary database failure')
 async def sleep(seconds):
  assert seconds==5
  if len(calls)==2:raise asyncio.CancelledError()
 monkeypatch.setattr(cleanup,'remove_files',remove);monkeypatch.setattr(cleanup.asyncio,'sleep',sleep)
 with pytest.raises(asyncio.CancelledError):asyncio.run(cleanup.maintain())
 assert len(calls)==2
