import hashlib,json,io
from app import db,resume_parser,profile_import,career_coach,optimization
from app.models import ExperienceItem

def document(user,text,kind='resume'):
 parsed=profile_import.parse(text,kind)
 return db.save(user,'document',{'filename':'fictional.pdf','text':text,'resume_parse':parsed,'purpose':'resume','import_source_kind':kind})

def test_overlap_preview_updates_only_approved_fields_and_conflicts_atomically(client,account):
 old=db.save(account['id'],'experience',ExperienceItem(category='employment',title='Data Analyst',organization='Example Company',description='Built a dashboard.',tools='SQL',confirmed=True).model_dump())
 doc=document(account['id'],'Alex Example\nExperience\nData Analyst | Example Company | Jan 2024 - Present\nBuilt a dashboard with quality checks.\nTools: SQL, Python')
 entry=doc['data']['resume_parse']['entries'][0];preview=client.get('/api/documents/'+doc['id']+'/import-preview').json()
 assert old['id'] in preview[entry['id']]['matches']
 patch={'id':entry['id'],'data':entry['data'],'record_id':old['id'],'expected_updated_at':preview['_versions'][old['id']],'fields':['description']}
 url='/api/documents/'+doc['id']+'/import-resume'
 result=client.post(url,json={'text_hash':doc['data']['resume_parse']['text_hash'],'updates':[patch],'reviewed':True});assert result.status_code==200,result.text
 saved=db.get(account['id'],old['id'],'experience');assert saved['data']['description']==entry['data']['description'];assert saved['data']['tools']=='SQL'
 receipt=db.get(account['id'],doc['id'],'document')['data']['import_history'][0];assert receipt['updated'][0]['before']['description']=='Built a dashboard.'
 assert client.post(url,json={'text_hash':doc['data']['resume_parse']['text_hash'],'updates':[patch],'entries':[{'id':entry['id'],'data':entry['data']}],'reviewed':True}).status_code in (400,409)
 assert client.post(url,json={'text_hash':doc['data']['resume_parse']['text_hash'],'updates':[patch],'reviewed':True}).status_code==409
 assert len([r for r in db.list_entities(account['id'],'experience') if r['data']['category']=='employment'])==1
 bad={**patch,'expected_updated_at':saved['updated_at'],'fields':['confirmed']};assert client.post(url,json={'text_hash':doc['data']['resume_parse']['text_hash'],'updates':[bad],'reviewed':True}).status_code==400

def test_import_update_cannot_target_another_account_or_erase_fields(client,account):
 doc=document(account['id'],'Alex Example\nExperience\nData Analyst | Example Company | 2024 - Present\nBuilt a dashboard.')
 entry=doc['data']['resume_parse']['entries'][0]
 other=client.post('/api/auth/register',json={'username':'other-import','password':'fictional-password'}).json()
 target=db.save(other['id'],'experience',ExperienceItem(category='employment',title='Data Analyst',organization='Example Company').model_dump())
 client.post('/api/auth/login',json={'username':'student','password':'fictional-test-password'});client.headers['X-CSRF-Token']=client.get('/api/me').json()['csrf']
 patch={'id':entry['id'],'data':entry['data'],'record_id':target['id'],'expected_updated_at':target['updated_at'],'fields':['description']}
 assert client.post('/api/documents/'+doc['id']+'/import-resume',json={'text_hash':doc['data']['resume_parse']['text_hash'],'updates':[patch],'reviewed':True}).status_code==404
 assert client.get('/api/documents/'+doc['id']+'/import-preview').status_code==200

def test_linkedin_parser_roles_dates_duplicate_identity_and_pdf_validation(client,account,monkeypatch):
 text='Alex Example\nhttps://linkedin.com/in/example\nExperience\nExample Company\nData Analyst\nJanuary 2024 - Present (2 years)\nBuilt a SQL dashboard.\nEducation\nExample University\nBachelor of Science, Data Science\n2019 - 2023\nPage 1 of 1'
 parsed=profile_import.parse(text,'linkedin_pdf');role=next(r for r in parsed['entries'] if r['data']['category']=='employment')
 assert role['data']['title']=='Data Analyst';assert role['data']['organization']=='Example Company';assert 'Example Company\nData Analyst' in role['source_text'];assert parsed['text_hash']==hashlib.sha256(text.encode()).hexdigest()
 assert client.post('/api/documents?purpose=resume&source_kind=linkedin_pdf',files={'file':('fake.txt',b'text')}).status_code==422
 existing={'id':'degree','updated_at':'v1','data':ExperienceItem(category='education',title='BS',degree='BS',organization='Example University').model_dump()}
 p={'entries':[{'id':'p','data':ExperienceItem(category='education',degree='Bachelor of Science',title='Degree',organization='Example University').model_dump()}]}
 assert profile_import.preview(p,[existing])['p']['matches']==['degree']

def test_headline_toggle_saved_and_generation_application_never_reintroduces_it(client,account):
 assert client.put('/api/settings',json={'use_professional_headline':False}).status_code==200
 assert client.get('/api/account/export').json()['profile']['use_professional_headline'] is False
 base={'use_professional_headline':False,'headline':'Old headline','sections':[]}
 assert optimization.apply(base,{'entries':[],'headline':'Generated headline'})['headline']==''
 assert base['headline']=='Old headline'

def test_delete_coach_chat_is_account_owned_and_removes_history_not_profile(client,account):
 chat=client.post('/api/career-coach/chats',json={'title':'Fictional plan'}).json();id=chat['id']
 msg=db.save(account['id'],'coach_message',{'chat_id':id,'content':'Private fictional chat'})
 plan=db.save(account['id'],'coach_plan',{'chat_id':id,'recommendations':[]})
 before=db.list_entities(account['id'],'experience')
 result=client.delete('/api/career-coach/chats/'+id);assert result.status_code==200,result.text
 assert client.get('/api/career-coach/chats/'+id).status_code==404
 assert not db.get(account['id'],msg['id'],'coach_message') and not db.get(account['id'],plan['id'],'coach_plan')
 assert db.list_entities(account['id'],'experience')==before
 assert client.delete('/api/career-coach/chats/'+id).status_code==404

def test_delete_protects_other_accounts_and_running_chat_then_redacts_completed_tasks(client,account):
 chat=client.post('/api/career-coach/chats',json={'title':'Private goal'}).json();id=chat['id'];stamp=db.now();task=db.uid()
 with db.connect() as c:c.execute('INSERT INTO tasks(id,user_id,kind,status,result,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(task,account['id'],'career_coach','cancelling',json.dumps({'inputs':{'chat_id':id,'text':'Private old question'}}),stamp,stamp))
 assert client.delete('/api/career-coach/chats/'+id).status_code==409
 with db.connect() as c:c.execute('UPDATE tasks SET status=? WHERE id=?',('completed',task))
 other=client.post('/api/auth/register',json={'username':'coach-deletion-other','password':'fictional-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
 from conftest import onboard_test_account
 onboard_test_account(other)
 assert client.delete('/api/career-coach/chats/'+id).status_code==404
 client.post('/api/auth/login',json={'username':'student','password':'fictional-test-password'});client.headers['X-CSRF-Token']=client.get('/api/me').json()['csrf']
 assert client.delete('/api/career-coach/chats/'+id).status_code==200
 with db.connect() as c:
  value=json.loads(c.execute('SELECT result FROM tasks WHERE id=?',(task,)).fetchone()[0]);assert value=={'deleted_chat_id':id}
