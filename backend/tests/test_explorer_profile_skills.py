import json
from app import db,career_explorer as explorer,career_evidence
BASE='/api/career-explorer'

def skill_record(user,names,**extra):
 return db.save(user,'experience',{'category':'skills','title':'Reviewed technical skills','confirmed':True,'skill_items':[{'name':name,'level':'intermediate'} for name in names],**extra})

def choices(client):return client.get(BASE+'/options').json()['profile']['skill_options']

def test_only_explicit_confirmed_skills_are_available_and_aliases_merge(client,account):
 u=account['id'];skill_record(u,['Python','SQL','PowerBI'])
 skill_record(u,['Microsoft Power BI',' python '],title='Another reviewed record',organization='Fictional organization')
 skill_record(u,['Secret draft'],confirmed=False)
 db.save(u,'experience',{'category':'project','confirmed':True,'description':'I used Docker and AWS','tools':'Docker, AWS'})
 db.save(u,'private_answer',{'text':'Private skill example'})
 rows=choices(client)
 assert len(rows)==3 and {career_evidence.canonical(r['title']) for r in rows}=={'python','sql','power bi'}
 assert len(next(r for r in rows if career_evidence.canonical(r['title'])=='power bi')['sources'])==2
 assert client.post(BASE+'/explore',json={}).json()['total']==len(explorer.OCCUPATIONS)
 assert all(not r['matched_skills'] for r in client.post(BASE+'/explore',json={}).json()['results'])

def test_selected_skills_match_published_names_and_order_without_ai(client,account):
 u=account['id'];skill_record(u,['PowerBI','Python','Uncatalogued fictional skill'])
 rows=choices(client);ids={r['title']:r['id'] for r in rows}
 before=db.list_entities(u,'experience')
 body={'profile_skill_ids':[ids['PowerBI'],ids['Python'],ids['Python']], 'limit':24}
 result=client.post(BASE+'/explore',json=body);assert result.status_code==200,result.text
 result=result.json();expected={code for code,names in explorer.OCCUPATION_SKILLS.items() if {'power bi','python'}&names}
 assert result['total']==len(expected)>0
 assert {r['code'] for r in result['results']}<=expected
 assert [len(r['matched_skills']) for r in result['results']]==sorted([len(r['matched_skills']) for r in result['results']],reverse=True)
 assert any('PowerBI' in r['matched_skills'] for r in result['results'])
 later=client.post(BASE+'/explore',json={**body,'offset':24}).json()
 assert not {r['code'] for r in result['results']}&{r['code'] for r in later['results']}
 sorted_rows=client.post(BASE+'/explore',json={**body,'sort':'title'}).json()['results']
 assert [r['title'] for r in sorted_rows]==sorted(r['title'] for r in sorted_rows)
 studies=client.post(BASE+'/explore',json={**body,'mode':'studies','major':'Data Science'}).json()
 assert studies['total']>0 and all(r['reason'] and r['matched_skills'] for r in studies['results'])
 missing=client.post(BASE+'/explore',json={'profile_skill_ids':[ids['Uncatalogued fictional skill']]}).json()
 assert missing['total']==0 and missing['unmatched_skills']==['Uncatalogued fictional skill']
 assert db.list_entities(u,'experience')==before and not db.list_entities(u,'usage_event') and not db.list_entities(u,'task')

def test_skill_ids_reject_other_account_and_revoked_records(client,account):
 u=account['id'];record=skill_record(u,['Python']);identity=choices(client)[0]['id']
 other=client.post('/api/auth/register',json={'username':'otherskills','password':'fictional-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
 skill_record(other['id'],['Python']);other_id=choices(client)[0]['id']
 assert identity!=other_id
 assert client.post(BASE+'/explore',json={'profile_skill_ids':[identity]}).status_code==409
 db.delete(other['id'],next(r['id'] for r in db.list_entities(other['id'],'experience')))
 assert client.post(BASE+'/explore',json={'profile_skill_ids':[other_id]}).status_code==409

def test_saved_skills_restore_with_aliases_missing_review_and_backup(client,account):
 u=account['id'];record=skill_record(u,['PowerBI','Python']);ids=[r['id'] for r in choices(client)]
 saved=client.post(BASE+'/searches',json={'name':'Skills exploration','query':{'profile_skill_ids':ids}}).json()
 loaded=client.get(BASE+'/searches/'+saved['id']+'/load').json()
 assert loaded['data']['query']['profile_skill_ids']==ids and not loaded['unavailable_skills']
 backup=client.get('/api/account/export').json()
 other=client.post('/api/auth/register',json={'username':'restoreskills','password':'fictional-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
 assert client.get(BASE+'/searches/'+saved['id']+'/load').status_code==404
 restored=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')});assert restored.status_code==200,restored.text
 imported=client.get(BASE+'/searches').json()['searches'][0]
 load=client.get(BASE+'/searches/'+imported['id']+'/load').json()
 assert not load['unavailable_skills'] and set(load['data']['query']['profile_skill_ids']).isdisjoint(ids)
 assert client.post(BASE+'/explore',json=load['data']['query']).json()['total']>0
 assert client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')}).status_code==200
 assert len(client.get(BASE+'/searches').json()['searches'])==1
 for r in db.list_entities(other['id'],'experience'):db.delete(other['id'],r['id'])
 skill_record(other['id'],['Microsoft Power BI'])
 load=client.get(BASE+'/searches/'+imported['id']+'/load').json()
 assert load['unavailable_skills']==['Python'] and len(load['data']['query']['profile_skill_ids'])==1
 assert client.post(BASE+'/explore',json=load['data']['query']).json()['total']>0

def test_legacy_search_defaults_to_no_skills(client,account):
 old={'name':'Legacy','query':{'query':'analyst'},'course_refs':[]}
 row=db.save(account['id'],explorer.SEARCH_KIND,old)
 value=client.get(BASE+'/searches/'+row['id']+'/load').json()
 assert value['data']['query']['profile_skill_ids']==[] and value['unavailable_skills']==[]
 assert explorer.search_digest(old)==explorer.search_digest(value['data'])
