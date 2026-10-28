import concurrent.futures,json
from app import career_explorer as explorer,db
BASE='/api/career-explorer'

def test_fresh_account_exploration_needs_no_setup_or_keys(client):
 u=client.post('/api/auth/register',json={'username':'explorer','password':'fictional-password'}).json();client.headers['X-CSRF-Token']=u['csrf']
 assert not client.get('/api/me').json()['onboarding']['completed']
 options=client.get(BASE+'/options');assert options.status_code==200
 assert options.json()['occupations']==1016 and options.json()['profile']['majors']==[]
 r=client.post(BASE+'/explore',json={'query':'GIS'});assert r.status_code==200
 assert any(v['code']=='15-1299.02' for v in r.json()['results'])
 assert client.post(BASE+'/saved',json={'code':'15-1299.02'}).status_code==200
 assert not db.list_entities(u['id'],'usage_event')
 assert not client.get('/api/me').json()['onboarding']['completed']

def test_study_connections_and_sorting(client,account):
 r=client.post(BASE+'/explore',json={'mode':'studies','major':'Geography'}).json()
 assert r['matched_programs'] and any('Geography' in p['title'] for p in r['matched_programs'])
 assert r['results'] and all(v['reason'] for v in r['results'])
 first={v['code'] for v in r['results']}
 assert '19-3092.00' in first
 codes=[v['code'] for v in r['results']]
 assert codes.index('19-3092.00')<codes.index('19-2041.01') if '19-2041.01' in codes else True
 assert client.post(BASE+'/explore',json={'mode':'studies'}).status_code==422
 empty=client.post(BASE+'/explore',json={'mode':'studies','major':'Unmatched fictional subject'}).json()
 assert empty['total']==0 and empty['notice']
 pay=client.post(BASE+'/explore',json={'sort':'pay','limit':24}).json()['results']
 assert [v['median_wage'] for v in pay]==sorted([v['median_wage'] for v in pay],reverse=True)
 assert client.post(BASE+'/explore',json={'industry':'invented'}).status_code==422
 assert client.post(BASE+'/explore',json={'personality':'mbti'}).status_code==422

def test_full_details_missing_values_and_profile_skill_labels(client,account):
 db.save(account['id'],'experience',{'confirmed':True,'category':'skills','skill_items':[{'name':'Python','level':'beginner'}]})
 db.save(account['id'],'experience',{'confirmed':False,'category':'skills','skill_items':[{'name':'Docker','level':'expert'}]})
 data=client.get(BASE+'/occupations/15-1252.00').json()
 python=next(v for v in data['technologies'] if v['name']=='Python');docker=next(v for v in data['technologies'] if v['name']=='Docker')
 assert python['profile_status']=='Recorded in Profile' and docker['profile_status']=='Not documented in Profile'
 assert len(data['description'])>400 and data['metadata']['growth_period']=='2025–35'
 assert 'h1b_rate' not in data and 'riasec' not in data and 'styles' not in data
 missing=client.get(BASE+'/occupations/11-1031.00').json()
 assert missing['median_wage'] is None and missing['growth'] is None and missing['openings'] is None
 assert client.get(BASE+'/occupations/99-9999.00').status_code==404

def test_only_confirmed_education_is_offered(client,account):
 db.save(account['id'],'experience',{'confirmed':True,'category':'education','majors':['Computer Science'],'minors':[],'relevant_courses':'Statistics; Accounting'})
 db.save(account['id'],'experience',{'confirmed':False,'category':'education','majors':['Secret draft major']})
 r=client.get(BASE+'/options').json()['profile']
 assert 'Computer Science' in r['majors'] and 'Secret draft major' not in r['majors'] and set(r['courses'])=={'Statistics','Accounting'}

def test_course_picker_merges_confirmed_records_without_clipping(client,account):
 u=account['id'];names=['Course '+str(i)+' with a sufficiently descriptive title' for i in range(45)]
 db.save(u,'experience',{'confirmed':True,'category':'education','organization':'Fictional School A','relevant_courses':'; '.join(names+['Statistics','Data, Ethics and Society'])})
 db.save(u,'experience',{'confirmed':True,'category':'coursework','title':' statistics ','organization':'Fictional School B'})
 db.save(u,'experience',{'confirmed':True,'category':'coursework','title':'MATH 101 Accounting','organization':'Fictional School B'})
 db.save(u,'experience',{'confirmed':False,'category':'coursework','title':'Unreviewed course'})
 r=client.get(BASE+'/options').json()['profile'];choices=r['course_options']
 assert len(choices)==48 and len(r['courses'])==48 and len('; '.join(r['courses']))>2000
 assert 'Data, Ethics and Society' in r['courses'] and 'Unreviewed course' not in r['courses']
 stats=next(c for c in choices if c['title'].casefold()=='statistics')
 assert set(stats['sources'])=={'Fictional School A','Fictional School B'}
 before=db.list_entities(u,'experience')
 result=client.post(BASE+'/explore',json={'mode':'studies','profile_course_ids':[c['id'] for c in choices]})
 assert result.status_code==200,result.text
 assert result.json()['matched_programs']
 assert any(p['input']=='MATH 101 Accounting' for p in result.json()['matched_programs'])
 assert db.list_entities(u,'experience')==before and not db.list_entities(u,'usage_event')

def test_selected_courses_are_account_scoped_current_and_deduplicated(client,account):
 u=account['id'];course=db.save(u,'experience',{'confirmed':True,'category':'coursework','title':'Statistics'})
 selected=client.get(BASE+'/options').json()['profile']['course_options'][0]['id']
 body={'mode':'studies','profile_course_ids':[selected,selected],'courses':'Statistics'}
 result=client.post(BASE+'/explore',json=body);assert result.status_code==200
 matches=result.json()['matched_programs'];assert len(matches)==len({(p['kind'],p['input'],p['code']) for p in matches})
 other=client.post('/api/auth/register',json={'username':'courseother','password':'fictional-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
 db.save(other['id'],'experience',{'confirmed':True,'category':'coursework','title':'Statistics'})
 other_id=client.get(BASE+'/options').json()['profile']['course_options'][0]['id'];assert other_id!=selected
 assert client.post(BASE+'/explore',json=body).status_code==409
 assert client.post(BASE+'/explore',json={**body,'mode':'browse'}).status_code==200
 db.delete(other['id'],next(r['id'] for r in db.list_entities(other['id'],'experience') if r['data'].get('title')=='Statistics'))
 assert client.post(BASE+'/explore',json={'mode':'studies','profile_course_ids':[other_id]}).status_code==409

def test_account_isolation_and_idempotent_saving(client,account):
 user=account['id'];before=db.list_entities(user,'experience')
 first=client.post(BASE+'/saved',json={'code':'15-1252.00'}).json()['careers'][0]
 client.post(BASE+'/saved',json={'code':'15-1252.00'})
 assert len(client.get(BASE+'/saved').json()['careers'])==1
 assert db.list_entities(user,'experience')==before and not db.list_entities(user,'career_goals')
 other=client.post('/api/auth/register',json={'username':'otherexplorer','password':'fictional-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
 assert client.get(BASE+'/saved').json()['careers']==[]
 assert client.delete(BASE+'/saved/'+first['id']).status_code==404
 assert db.get(user,first['id'],'saved_career')

def test_concurrent_duplicate_and_limit(client,account):
 u=account['id']
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(lambda _:explorer.save(u,explorer.SaveCareer(code='15-1252.00')),range(8)))
 assert len(db.list_entities(u,'saved_career'))==1
 for code in list(explorer.OCCUPATIONS)[:49]:explorer.save(u,explorer.SaveCareer(code=code))
 assert len(db.list_entities(u,'saved_career'))==50
 assert client.post(BASE+'/saved',json={'code':'15-2051.00'}).status_code==409
 assert client.post(BASE+'/saved',json={'code':'15-1252.00'}).status_code==200

def test_saved_career_backup_is_additive_and_deduplicated(client,account):
 client.post(BASE+'/saved',json={'code':'15-1252.00'})
 backup=client.get('/api/account/export').json();record=next(r for r in backup['records'] if r['kind']=='saved_career')
 def restore(value):return client.post('/api/account/import',files={'file':('backup.json',json.dumps(value).encode(),'application/json')})
 assert restore(backup).status_code==200
 assert len(client.get(BASE+'/saved').json()['careers'])==1
 record['data']['code']='99-9999.99';record['data']['title']='Historical occupation';record['id']='old-occupation'
 assert restore(backup).status_code==200
 values=client.get(BASE+'/saved').json()['careers'];assert len(values)==2 and any(v.get('unavailable') for v in values)
 count=len(db.list_entities(account['id'],'saved_career'));record['data']['code']='malformed'
 assert restore(backup).status_code==400
 assert len(db.list_entities(account['id'],'saved_career'))==count

def test_catalog_integrity_and_paging(client,account):
 assert all(o['job_zone'] is None or 1<=o['job_zone']<=5 for o in explorer.OCCUPATIONS.values())
 assert all(0<=v['importance']<=5 for o in explorer.OCCUPATIONS.values() for v in o['skills'])
 assert all(code in explorer.OCCUPATIONS for o in explorer.OCCUPATIONS.values() for code in o['related'])
 assert all('h1b' not in k and k not in ('styles','riasec') for o in explorer.OCCUPATIONS.values() for k in o)
 a=client.post(BASE+'/explore',json={'preparation':'college','limit':12}).json()
 b=client.post(BASE+'/explore',json={'preparation':'college','limit':12,'offset':12}).json()
 assert not {v['code'] for v in a['results']} & {v['code'] for v in b['results']}
 assert a['total']==378 and all(v['job_zone'] in (4,5) for v in a['results'])
