import copy,json
from app import db,skills,skill_catalog

def profile(user,names,confirmed=True):return db.save(user,'experience',{'category':'skills','title':'Practice topics','confirmed':confirmed,'skill_items':[{'name':s,'level':'unknown'} for s in names]})

def test_free_matching_uses_reviewed_relationships_without_mutation(client,account):
 u=account['id'];profile(u,['Data modeling','Python']);profile(u,['AWS'],False)
 db.save(u,'experience',{'category':'project','title':'Narrative','confirmed':True,'description':'Azure secret project'})
 before=copy.deepcopy(db.list_entities(u,'experience'));v=client.get('/api/skills/options',params={'include_related':True,'include_resources':False}).json()
 assert not v['resources'] and len(v['suggested_topics'])<=10
 assert {'Data modeling','Python'}<=set(v['suggestions']) and 'AWS' not in v['suggestions'] and 'Azure' not in v['suggestions']
 assert any(any(s['kind']=='related' for s in r['sources']) for r in v['suggested_topics'])
 assert 'database-concurrency-control' not in skill_catalog.index()['data-modeling']['related']
 assert {'sql','sql-schemas','sql-table-constraints'}<=set(skill_catalog.index()['data-modeling']['related'])
 for r in v['suggested_topics']:
  for s in r['sources']:
   if s['kind']=='related':assert r['id'] in skill_catalog.index()[s['topic_id']]['related']
 assert db.list_entities(u,'experience')==before and not db.list_entities(u,'usage_event')
 assert all(not t['label'].startswith(':') for t in skill_catalog.data()['skills'])


def test_combined_multiselect_union_inside_intersection_across_and_legacy(client,account):
 params=[('topic_ids','Python'),('topic_ids','SQL'),('fields','Tech & Data'),('providers','Codecademy'),('providers','DataCamp'),('formats','course'),('accesses','freemium'),('levels','unspecified'),('sort','title')]
 response=client.get('/api/skills/resources',params=params);assert response.status_code==200,response.text
 v=response.json();assert {r['id'] for r in v['resources']}=={'codecademy-python','codecademy-sql','datacamp-python','datacamp-sql'}
 assert set(v['facets']['providers'])=={'Codecademy','DataCamp'} and v['total']==4
 titles=[r['display_title'].casefold() for r in v['resources']];assert titles==sorted(titles)
 assert v==client.get('/api/skills/resources',params=params).json()
 # Conflicting filters yield an honest empty result and keep the selected facets.
 empty=client.get('/api/skills/resources',params=params+[('fields','Engineering'),('levels','advanced')]).json();assert empty['total']==4 # OR within fields and levels
 empty=client.get('/api/skills/resources',params=[('topics','Python'),('fields','Engineering'),('providers','Codecademy')]).json();assert empty['total']==0
 assert 'Engineering' in empty['facets']['fields'] and 'Codecademy' in empty['facets']['providers']
 old=client.get('/api/skills/resources?topics=Python&provider=DataCamp&format=course&access=freemium&level=unspecified').json();assert [r['id'] for r in old['resources']]==['datacamp-python']
 assert client.get('/api/skills/resources?fields=imaginary').status_code==422
 assert client.get('/api/skills/resources?levels=imaginary').status_code==422
 assert client.get('/api/skills/resources?topics=SQL').json()['total']>=6
 assert client.get('/api/skills/resources?q=Amazon%20Web%20Services').json()['total']>0
 assert client.get('/api/skills/resources?q=Apache%20Spark').json()['total']>0


def test_recommended_ranking_context_sources_alias_search_and_account_isolation(client,account):
 profile(account['id'],['Data modeling','Python'])
 job=db.save(account['id'],'job',{'title':'SQL analyst','description':'Use SQL to inspect data.'})
 client.put('/api/profile/career-goals',json={'text':'Develop AWS projects','expected_revision':0})
 params=[('job_id',job['id']),('sources','posting'),('sources','goal'),('fields','Tech & Data'),('sort','recommended')]
 v=client.get('/api/skills/resources',params=params).json();assert v['resources']
 assert all(any(s.get('origin_kind',s['kind']) in ('posting','goal') for s in r['recommendation_reasons']) for r in v['resources'])
 assert all(s.get('record_id') for r in v['resources'] for s in r['recommendation_reasons'])
 one=client.get('/api/skills/resources?sort=title&limit=12').json();two=client.get('/api/skills/resources?sort=title&offset=12').json()
 assert len(one['resources'])==len(two['resources'])==12 and not {r['id'] for r in one['resources']}&{r['id'] for r in two['resources']}
 foreign=client.post('/api/auth/register',json={'username':'cardsother','password':'fictional-password'}).json();client.headers['X-CSRF-Token']=foreign['csrf']
 empty=client.get('/api/skills/options?include_related=true&include_resources=false').json();assert empty['suggested_topics']==[]
 result=client.get('/api/skills/resources?sort=recommended').json();assert all(not r['recommendation_reasons'] for r in result['resources'])
 assert [r['id'] for r in result['resources']]==[r['id'] for r in client.get('/api/skills/resources?sort=title').json()['resources']]
 assert client.get('/api/skills/resources?job_id='+job['id']).status_code==404
 assert not db.list_entities(account['id'],'usage_event') and not db.list_entities(foreign['id'],'usage_event')


def test_presentable_metadata_does_not_rewrite_resource_identity_or_source():
 row=next(r for r in skills.library() if r['url'].endswith('ddl-constraints.html'));original=copy.deepcopy(row)
 shown=skills.display_resource(row)
 assert 'PostgreSQL:' not in shown['display_title'] and 'Documentation:' not in shown['display_title'] and 'Constraints' in shown['display_title']
 for key in ('id','url','title','source_title'):assert shown[key]==original[key]
 assert row==original and len(skills.candidates(['Python','SQL','Spark']))<=24


def test_legacy_provider_names_and_all_field_support_remain_compatible(client,account):
 rows=client.get('/api/skills/resources?topics=Python&provider=www.datacamp.com').json()['resources']
 assert [r['id'] for r in rows]==['datacamp-python']
 for field in skills.FIELDS:
  rows=client.get('/api/skills/resources',params={'kind':'support','field':field,'limit':24}).json()['resources']
  assert any(r['id']=='practice' for r in rows)


def test_clean_card_titles_drop_document_structure_and_anchor_glyphs_only():
 cases={
  'Chapter 2. The SQL Language':'The SQL Language',
  'Chapter 21. Database Roles':'Database Roles',
  'Section IV: Processing data':'Processing data',
  '1.1. Linear Models #':'Linear Models',
  'An Informal Introduction to Python ¶':'An Informal Introduction to Python',
  'Chart visualization #':'Chart visualization',
  'Getting Started #':'Python — Getting Started',
  'C#':'C#', 'F#':'F#','3D Coordinate Systems & Vectors':'3D Coordinate Systems & Vectors',
 }
 for title,expected in cases.items():
  original={'id':'stable','url':'https://example.edu/reference','provider':'Example','title':title,'source_title':title,'learning_topics':['Python']}
  shown=skills.display_resource(original)
  assert shown['display_title']==expected
  assert all(shown[k]==original[k] for k in ('id','url','title','source_title'))
 for original in skills.library():
  title=skills.display_resource(original)['display_title']
  assert not __import__('re').search(r'[¶🔗]|\s#\s*$|^chapter\s+\d',title,__import__('re').I),title
