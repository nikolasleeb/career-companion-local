import json,hashlib,copy
from app import db,profile_import,combined_import
from app.models import ExperienceItem

def source(user,text,kind='resume'):
 return db.save(user,'document',{'filename':kind+'.txt' if kind=='resume' else 'linkedin.pdf','text':text,'purpose':'resume','import_source_kind':kind,'resume_parse':profile_import.parse(text,kind)})
def prepare(client,*docs,**extra):
 r=client.post('/api/profile-import/preview',json={'document_ids':[d['id'] for d in docs],**extra});assert r.status_code==200,r.text;return r.json()
def approve(client,p,entries=None,**extra):
 return client.post('/api/profile-import/'+p['id']+'/approve',json={'reviewed':True,'entries':entries if entries is not None else [{'id':e['id'],'data':e['data']} for e in p['data']['resume_parse']['entries']],**extra})
def text(description='Built a dashboard.',name='Alex Example'):
 return name+'\nExperience\nData Analyst | Fictional Labs | Jan 2024 - Present\n'+description

def test_exact_duplicates_one_proposal_no_profile_write_and_two_sources(client,account):
 a=source(account['id'],text());b=source(account['id'],text(),'linkedin_pdf');before=db.list_entities(account['id'],'experience');p=prepare(client,a,b);entries=p['data']['resume_parse']['entries'];assert len(entries)==1 and len(entries[0]['sources'])==2 and not entries[0]['conflicts'];assert db.list_entities(account['id'],'experience')==before
 r=approve(client,p);assert r.status_code==200,r.text;assert r.json()['created']==1
 created=next(r for r in db.list_entities(account['id'],'experience') if r['id'] not in {x['id'] for x in before});assert len(created['data']['source_references'])==2 and created['data']['confirmed']
 assert approve(client,p).json()==r.json();assert len(db.list_entities(account['id'],'experience'))==len(before)+1
 backup=client.get('/api/account/export').json();restored=client.post('/api/account/import',files={'file':('fictional.json',json.dumps(backup),'application/json')});assert restored.status_code==200,restored.text
 assert len([x for x in db.list_entities(account['id'],'experience') if x['data'].get('source_references')])==2

def test_conflict_requires_explicit_source_and_merge_confirmation(client,account):
 a=source(account['id'],text());b=source(account['id'],text('Investigated a different dataset.'),'linkedin_pdf');p=prepare(client,a,b);e=p['data']['resume_parse']['entries'][0];assert 'description' in e['conflicts'] and e['requires_merge_confirmation']
 assert approve(client,p).status_code==422
 choices={k:'0' for k in e['conflicts']};data={**e['data'],**{k:opts[0]['value'] for k,opts in e['conflicts'].items()}}
 assert approve(client,p,[{'id':e['id'],'data':data}],choices={e['id']:choices}).status_code==422
 r=approve(client,p,[{'id':e['id'],'data':data}],choices={e['id']:choices},confirmed_merges=[e['id']]);assert r.status_code==200,r.text
 p2=prepare(client,a,b,separate_groups=[e['id']]);assert len(p2['data']['resume_parse']['entries'])==2

def test_personal_conflict_edited_and_empty_approval(client,account):
 a=source(account['id'],text(name='Alex Example'));b=source(account['id'],text(name='Jordan Example'),'linkedin_pdf');p=prepare(client,a,b);parsed=p['data']['resume_parse'];assert 'name' in parsed['profile_conflicts'] and parsed['profile']['name']==''
 assert approve(client,p,[],profile_updates={'name':'Reviewed Example'}).status_code==422
 r=approve(client,p,[],profile_updates={'name':'Reviewed Example'},profile_choices={'name':'edited'});assert r.status_code==200,r.text;assert db.settings(account['id'])['name']=='Reviewed Example'
 assert approve(client,p,[]).status_code==422

def test_stale_source_and_target_atomic_rollback(client,account):
 a=source(account['id'],text());p=prepare(client,a);e=p['data']['resume_parse']['entries'][0];old=db.save(account['id'],'experience',ExperienceItem(category='employment',title='Data Analyst',organization='Fictional Labs',description='Old evidence',confirmed=True).model_dump())
 p=prepare(client,a);db.save(account['id'],'experience',{**old['data'],'description':'Newer evidence'},old['id']);updates=[{'id':e['id'],'data':e['data'],'record_id':old['id'],'expected_updated_at':old['updated_at'],'fields':['description']}]
 r=approve(client,p,[],updates=updates);assert r.status_code==409 and db.get(account['id'],old['id'])['data']['description']=='Newer evidence'
 p=prepare(client,a);db.save(account['id'],'document',{**a['data'],'text':text('Corrected text')},a['id']);assert approve(client,p).status_code==409

def test_foreign_missing_types_and_deleted_source(client,account):
 a=source(account['id'],text());b=source(account['id'],text('Second resume'));assert client.post('/api/profile-import/preview',json={'document_ids':[a['id'],b['id']]}).status_code==422
 assert client.post('/api/profile-import/preview',json={'document_ids':[a['id'],a['id']]}).status_code==422
 p=prepare(client,a);assert approve(client,p).status_code==200;assert client.delete('/api/records/'+a['id']).status_code==200
 assert approve(client,p).status_code==404
 backup=client.get('/api/account/export').json();assert client.post('/api/account/import',files={'file':('fictional.json',json.dumps(backup),'application/json')}).status_code==200
 other=client.post('/api/auth/register',json={'username':'foreign-combined','password':'fictional-password'}).json();client.headers['X-CSRF-Token']=other['csrf'];assert client.post('/api/profile-import/preview',json={'document_ids':[b['id']]}).status_code==404
 assert approve(client,p).status_code==404

def test_edit_preserves_provenance_and_marks_user_wording(client,account):
 a=source(account['id'],text());p=prepare(client,a);assert approve(client,p).status_code==200
 r=next(r for r in db.list_entities(account['id'],'experience') if r['data'].get('source_references'));body={**r['data'],'description':'My current wording'};edited=client.put('/api/experience/'+r['id'],json=body);assert edited.status_code==200,edited.text
 refs=edited.json()['data']['source_references'];assert 'description' in refs[0]['edited_fields'] and 'description' not in refs[0]['fields']

def test_late_validation_failure_rolls_back_all_selected_changes(client,account):
 a=source(account['id'],text()+'\nPROJECTS\nFictional project\nBuilt a demonstration.')
 p=prepare(client,a);items=[{'id':e['id'],'data':e['data']} for e in p['data']['resume_parse']['entries']];assert len(items)==2
 before=db.list_entities(account['id'],'experience');items[1]['id']='not-part-of-review'
 r=approve(client,p,items,profile_updates={'name':'Do not save this either'})
 assert r.status_code==422 and db.list_entities(account['id'],'experience')==before and db.settings(account['id']).get('name','')==''

def test_approved_source_values_cannot_be_forged(client,account):
 a=source(account['id'],text());b=source(account['id'],text('Other dataset.'),'linkedin_pdf');p=prepare(client,a,b);e=p['data']['resume_parse']['entries'][0]
 data={**e['data'],'description':'Invented replacement'};choices={k:'0' for k in e['conflicts']}
 r=approve(client,p,[{'id':e['id'],'data':data}],choices={e['id']:choices},confirmed_merges=[e['id']]);assert r.status_code==422
 assert len(db.list_entities(account['id'],'experience'))==1
