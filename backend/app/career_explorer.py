"""Account-scoped career exploration from attributed public snapshots, without AI."""
import hashlib,json,re,unicodedata
from pathlib import Path
from typing import Annotated,Literal
from fastapi import APIRouter,Depends,HTTPException,Query
from pydantic import Field
from . import auth,db,career_evidence,career_wages,credentials,salary_areas
from .models import StrictModel
from .resume_conversation import write

router=APIRouter(prefix='/api/career-explorer')
DATA=json.loads(Path(__file__).with_name('career_explorer_data.json').read_text())
OCCUPATIONS=DATA['occupations'];META=DATA['metadata'];MAX_SAVED=50
CODE=r'^\d{2}-\d{4}\.\d{2}$'
ZONES={1:'Little preparation',2:'Some preparation',3:'Medium preparation',4:'Considerable preparation · often bachelor’s-level',5:'Extensive preparation · often graduate-level'}
ALIASES={'gis':'geographic information systems','hr':'human resources','it':'information technology','mis':'management information systems','cs':'computer science','cis':'computer information systems'}
FILLER={'and','of','the','in','to','a','an','general','other','studies','introduction','intro'}

def words(value):
 value=unicodedata.normalize('NFKC',str(value)).casefold()
 return set(re.findall(r'[a-z0-9]+(?:\+\+|#)?',value))
def subject(value):
 value=ALIASES.get(value.strip().casefold(),value)
 return words(value)-FILLER
def covers(need,have):return bool(need) and all(any(t.startswith(w) for t in have) for w in need)
TITLE_WORDS={code:words(o['title']) for code,o in OCCUPATIONS.items()}
ALT_WORDS={code:[(title,words(title)) for title in o['titles']] for code,o in OCCUPATIONS.items()}
OCCUPATION_SKILLS={code:{career_evidence.canonical(item['name']) for item in o['skills']+o['technologies']} for code,o in OCCUPATIONS.items()}
PROGRAM_WORDS={code:subject(title) for code,title in DATA['programs'].items()}

class Explore(StrictModel):
 mode:Literal['studies','browse']='browse'
 major:str=Field(default='',max_length=300)
 courses:str=Field(default='',max_length=2000)
 profile_course_ids:list[Annotated[str,Field(pattern=r'^[a-f0-9]{24}$')]]=Field(default_factory=list,max_length=1000)
 profile_skill_ids:list[Annotated[str,Field(pattern=r'^[a-f0-9]{24}$')]]=Field(default_factory=list,max_length=1000)
 query:str=Field(default='',max_length=120)
 industry:str=Field(default='',max_length=8)
 industries:list[Annotated[str,Field(min_length=1,max_length=8)]]=Field(default_factory=list,max_length=len(DATA['sectors']))
 salary_area:str=Field(default='US',max_length=40)
 preparation:Literal['all','college']='all'
 sort:Literal['relevance','title','pay','growth']='relevance'
 offset:int=Field(default=0,ge=0,le=1100)
 limit:int=Field(default=12,ge=1,le=24)

class SaveCareer(StrictModel):
 code:str=Field(pattern=CODE)
 source:Literal['generator','search']='search'

class SavedCareer(SaveCareer):
 title:str=Field(min_length=1,max_length=300)
 dataset_version:str=Field(default='',max_length=100)

def occupation(code):
 if code not in OCCUPATIONS:raise HTTPException(404,'Occupation not found in the bundled catalog.')
 return OCCUPATIONS[code]

def profile(user):
 majors=[];skills=[];course_rows={};skill_rows={}
 def add_course(title,record):
  title=re.sub(r'\s+',' ',title).strip()
  if not title:return
  key=unicodedata.normalize('NFKC',title).casefold()
  if key not in course_rows:course_rows[key]={'id':hashlib.sha256((user+':course:'+key).encode()).hexdigest()[:24],'title':title,'sources':[]}
  source=record.get('organization') or record.get('title') or 'Confirmed Profile record'
  if source not in course_rows[key]['sources']:course_rows[key]['sources'].append(source)
 for r in db.list_entities(user,'experience'):
  d=r['data']
  if not d.get('confirmed'):continue
  if d.get('category')=='education':
   majors.extend(d.get('majors') or []);majors.extend(d.get('minors') or [])
  if d.get('category') in ('education','coursework'):
   raw=d.get('relevant_courses') or ''
   # Transcript-reviewed lists use semicolons; keep punctuation inside those titles.
   for value in re.split(r'[;\n]' if re.search(r'[;\n]',raw) else ',',raw):add_course(value,d)
   if d.get('category')=='coursework' and d.get('title','').strip().casefold() not in ('coursework','courses','relevant coursework','relevant courses'):add_course(d.get('title',''),d)
  for item in d.get('skill_items',[]):
   if not isinstance(item,dict) or not isinstance(item.get('name'),str):continue
   title=re.sub(r'\s+',' ',item['name']).strip();key=career_evidence.canonical(title)
   if not key:continue
   if key not in skill_rows:skill_rows[key]={'id':hashlib.sha256((user+':skill:'+key).encode()).hexdigest()[:24],'title':title,'sources':[]}
   source=d.get('organization') or d.get('title') or 'Confirmed Profile skills'
   if source not in skill_rows[key]['sources']:skill_rows[key]['sources'].append(source)
   skills.append(title)
 unique=lambda v:list(dict.fromkeys(x.strip() for x in v if isinstance(x,str) and x.strip()))
 choices=sorted(course_rows.values(),key=lambda x:x['title'].casefold())
 return {'majors':unique(majors)[:6],'courses':[c['title'] for c in choices],'course_options':choices,'skills':unique(skills),'skill_options':sorted(skill_rows.values(),key=lambda x:x['title'].casefold())}

def programs(text):
 need=subject(text)
 if not need:return []
 rows=[]
 for code,have in PROGRAM_WORDS.items():
  title=DATA['programs'][code]
  if ('teacher' in have or 'education' in have) and not ({'teacher','education','teaching'}&need):continue
  if need<=have:rows.append((have!=need,len(have-need),code,title))
 return [{'code':code,'title':title,'exact':not loose} for loose,_,code,title in sorted(rows)[:3]]

def study_links(body,selected_courses=()):
 links={};matched=[]
 for kind,texts in (('major',re.split(r'[;\n]',body.major)),('course',list(selected_courses)+re.split(r'[;\n]',body.courses))):
  seen=set()
  for text in texts:
   key=re.sub(r'\s+',' ',text).strip().casefold()
   if not key or key in seen:continue
   seen.add(key)
   lookup=re.sub(r'^[A-Z]{2,8}\s*\d{2,4}[A-Za-z]?\s*[-:–—]?\s+','',text.strip()) if kind=='course' else text.strip()
   for p in programs(lookup):
    matched.append({**p,'input':text.strip(),'kind':kind})
    for code in DATA['program_links'].get(p['code'],[]):
     if code not in OCCUPATIONS:continue
     tier=(5 if p['exact'] else 3) if kind=='major' else 1
     why=f"Education crosswalk: {text.strip()} → {p['title']} (CIP {p['code']}). This is a study connection, not a qualification."
     if code not in links or tier>links[code][0]:links[code]=(tier,why)
 for code,(tier,_) in list(links.items()):
  if tier>=3:
   for other in OCCUPATIONS[code]['related'][:5]:
    related_tier=4 if tier==5 else 2
    if other in OCCUPATIONS and (other not in links or links[other][0]<related_tier):links[other]=(related_tier,'O*NET lists this as related to '+OCCUPATIONS[code]['title']+'.')
 return links,matched

def summary(code,reason='',also='',salary_area='US'):
 o=OCCUPATIONS[code]
 return {k:o[k] for k in ('title','description','job_zone','median_wage','wage_year','wage_note','growth','growth_note','openings')}|{'code':code,'preparation':ZONES.get(o['job_zone'],'Preparation not reported'),'reason':reason,'also':also,'onet_url':'https://www.onetonline.org/link/summary/'+code,'dataset_version':META['version'],'salary':career_wages.pay(code,salary_area)}

@router.get('/options')
def options(user=Depends(auth.current)):
 p=profile(user['id'])
 return {'profile':{k:p[k] for k in ('majors','courses','course_options','skill_options')},'industries':DATA['sectors'],'metadata':META,'occupations':len(OCCUPATIONS),'saved_limit':MAX_SAVED,'salary_areas':salary_areas.catalog(),'wage_metadata':career_wages.data()['metadata'],'work_style':{k:v for k,v in career_evidence.style(user['id']).items() if k!='summary'}}

@router.post('/explore')
def explore(body:Explore,user=Depends(auth.current)):
 career_wages.area(body.salary_area)
 selected_industries=set(body.industries)|({body.industry} if body.industry else set())
 if selected_industries-{s['naics'] for s in DATA['sectors']}:raise HTTPException(422,'Choose industries from the list.')
 def industry_share(o):return max((o['sectors'].get(code,0) for code in selected_industries),default=0)
 p=profile(user['id'])
 skill_choices={s['id']:s['title'] for s in p['skill_options']}
 if any(id not in skill_choices for id in body.profile_skill_ids):raise HTTPException(409,'A selected skill is no longer in your confirmed Profile. Reload Career Explorer and review your selection.')
 selected_skills=list(dict.fromkeys(skill_choices[id] for id in body.profile_skill_ids))
 selected_keys={name:career_evidence.canonical(name) for name in selected_skills}
 skill_matches={code:[name for name,key in selected_keys.items() if key in names] for code,names in OCCUPATION_SKILLS.items()} if selected_skills else {}
 selected_courses=[]
 if body.mode=='studies':
  choices={c['id']:c['title'] for c in p['course_options']}
  if any(id not in choices for id in body.profile_course_ids):raise HTTPException(409,'A selected course is no longer in your confirmed Profile. Reload Career Explorer and review your selection.')
  selected_courses=[choices[id] for id in dict.fromkeys(body.profile_course_ids)]
  if not (body.major.strip() or body.courses.strip() or selected_courses):raise HTTPException(422,'Enter a major, select a Profile course, or choose Explore other directions.')
 links,matched=study_links(body,selected_courses) if body.mode=='studies' else ({},[])
 query=body.query.strip();need=words(query);rows=[]
 for code,o in OCCUPATIONS.items():
  if body.preparation=='college' and o['job_zone'] not in (4,5):continue
  if selected_industries and industry_share(o)<1:continue
  if body.mode=='studies' and code not in links:continue
  if selected_skills and not skill_matches[code]:continue
  quality=0;also=''
  if query:
   if code.startswith(query) or covers(need,TITLE_WORDS[code]):quality=3
   else:
    also=min((t for t,w in ALT_WORDS[code] if covers(need,w)),key=len,default='')
    if also:quality=2
    elif covers(need,words(o['description'])):quality=1
    else:continue
  tier,reason=links.get(code,(0,''))
  rows.append((code,quality,tier,reason,also))
 def order(row):
  code,quality,tier,_,_=row;o=OCCUPATIONS[code]
  if body.sort=='pay':return (*career_wages.sort_key(code,body.salary_area),o['title'])
  if body.sort=='growth':
   value=career_wages.median(code,body.salary_area) if body.sort=='pay' else o['growth']
   return (value is None,-value if value is not None else 0,o['title'])
  if body.sort=='title':return (o['title'],)
  return (-quality,-len(skill_matches.get(code,[])),-tier,-industry_share(o),o['title'])
 rows.sort(key=order)
 return {'results':[{**summary(code,reason,also,body.salary_area),'matched_skills':skill_matches.get(code,[])} for code,_,_,reason,also in rows[body.offset:body.offset+body.limit]],'total':len(rows),'offset':body.offset,'matched_programs':matched,'unmatched_skills':[name for name in selected_skills if not any(selected_keys[name] in names for names in OCCUPATION_SKILLS.values())],'metadata':META,'notice':'No education-program connection was found. Try a fuller major name, or Explore other directions.' if body.mode=='studies' and not matched else ''}

@router.get('/occupations/{code}')
def detail(code:str,salary_area:str='US',user=Depends(auth.current)):
 from . import explicit_context
 o=occupation(code);rows=career_evidence.sources(user['id']);style=career_evidence.style(user['id'])
 return {**summary(code,salary_area=salary_area),'context_ref':explicit_context.occupation_reference(code,None if salary_area=='US' else salary_area),'occupation_link':explicit_context.occupation_link(code),'skills':[career_evidence.matches(s,rows) for s in o['skills']],'technologies':[career_evidence.matches(t,rows) for t in o['technologies']],'ai_available':bool(credentials.get(user['id'])),'ai_mode':db.settings(user['id']).get('mode','economy'),'profile_revision':career_evidence.revision(rows),'work_style':{k:v for k,v in style.items() if k!='summary'},'industries':[{'naics':s['naics'],'title':s['title'],'share':o['sectors'][s['naics']]} for s in DATA['sectors'] if s['naics'] in o['sectors']],'related':[{'code':c,'title':OCCUPATIONS[c]['title']} for c in o['related'] if c in OCCUPATIONS],'metadata':META}

def saved_list(user,salary_area='US'):
 career_wages.area(salary_area)
 rows=list(reversed(db.list_entities(user,'saved_career')))
 return {'careers':[{'id':r['id'],'created_at':r['created_at'],**(summary(r['data']['code'],salary_area=salary_area) if r['data']['code'] in OCCUPATIONS else {**r['data'],'unavailable':True})} for r in rows],'limit':MAX_SAVED}

def save(user,body,*,restored=None):
 if restored is None:occupation(body.code)
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE')
  rows=c.execute("SELECT id,payload FROM entities WHERE user_id=? AND kind='saved_career'",(user,)).fetchall()
  if any(json.loads(r['payload'])['code']==body.code for r in rows):return
  if len(rows)>=MAX_SAVED:raise HTTPException(409,'You can save up to 50 careers. Remove one before adding another.')
  value=restored or {'code':body.code,'title':OCCUPATIONS[body.code]['title'],'source':body.source,'dataset_version':META['version']}
  identity=hashlib.sha256((user+':saved-career:'+body.code).encode()).hexdigest()[:32]
  write(c,user,'saved_career',value,identity)

@router.get('/saved')
def saved(salary_area:str='US',user=Depends(auth.current)):return saved_list(user['id'],salary_area)
@router.post('/saved')
def add(body:SaveCareer,user=Depends(auth.current)):
 save(user['id'],body);return saved_list(user['id'])
@router.delete('/saved/{id}')
def remove(id:str,user=Depends(auth.current)):
 if not db.get(user['id'],id,'saved_career'):raise HTTPException(404,'Saved career not found.')
 db.delete(user['id'],id);return saved_list(user['id'])

def validate_backup(record):
 if record['kind']=='saved_career':SavedCareer.model_validate(record['data'])
 if record['kind']=='career_explorer_search':SearchRecord.model_validate(record['data'])
 if record['kind']=='career_explorer_review':
  from .career_reviews import validate_backup
  validate_backup(record['data'])
def validate_import(user,records):
 codes={r['data']['code'] for r in db.list_entities(user,'saved_career')}
 codes.update(r['data']['code'] for r in records if r['kind']=='saved_career')
 if len(codes)>MAX_SAVED:raise ValueError('Too many saved careers.')
 existing=db.list_entities(user,'career_explorer_search');known={search_digest(r['data']) for r in existing}
 incoming={search_digest(r['data']) for r in records if r['kind']=='career_explorer_search'}
 if len(existing)+len(incoming-known)>50:raise ValueError('Too many saved career searches.')
def restore(user,data):save(user,SaveCareer(code=data['code'],source=data['source']),restored=SavedCareer.model_validate(data).model_dump())

SEARCH_KIND='career_explorer_search'
class CourseRef(StrictModel):
 id:str=Field(max_length=64)
 title:str=Field(min_length=1,max_length=2000)
class SearchRecord(StrictModel):
 name:str=Field(min_length=1,max_length=100)
 query:Explore
 course_refs:list[CourseRef]=Field(default_factory=list,max_length=1000)
 skill_refs:list[CourseRef]=Field(default_factory=list,max_length=1000)
class SearchChange(StrictModel):
 name:str=Field(min_length=1,max_length=100)
 query:Explore
 expected_updated_at:str=Field(default='',max_length=100)
def searches(user):return list(reversed(db.list_entities(user,SEARCH_KIND)))
@router.get('/searches')
def saved_searches(user=Depends(auth.current)):return {'searches':searches(user['id']),'limit':50}
def save_search(user,body,id=None):
 if not body.name.strip():raise HTTPException(422,'Name this career search.')
 # Reuse exploration validation, without any external or AI request.
 explore(body.query,{'id':user})
 p=profile(user)
 courses={c['id']:c['title'] for c in p['course_options']}
 skills={s['id']:s['title'] for s in p['skill_options']}
 refs=[{'id':id,'title':courses[id]} for id in dict.fromkeys(body.query.profile_course_ids)] if body.query.mode=='studies' else []
 value=SearchRecord(name=body.name.strip(),query=body.query,course_refs=refs,skill_refs=[{'id':id,'title':skills[id]} for id in dict.fromkeys(body.query.profile_skill_ids)]).model_dump();value['query']['offset']=0
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE')
  if id:
   old=c.execute('SELECT * FROM entities WHERE user_id=? AND id=? AND kind=?',(user,id,SEARCH_KIND)).fetchone()
   if not old:raise HTTPException(404,'Saved career search not found.')
   if old['updated_at']!=body.expected_updated_at:raise HTTPException(409,'This saved search changed. Reload Saved searches before updating.')
  elif c.execute('SELECT count(*) FROM entities WHERE user_id=? AND kind=?',(user,SEARCH_KIND)).fetchone()[0]>=50:raise HTTPException(409,'Keep at most 50 saved career searches.')
  key=id or db.uid();write(c,user,SEARCH_KIND,value,key)
 return db.get(user,key,SEARCH_KIND)
@router.post('/searches')
def create_search(body:SearchChange,user=Depends(auth.current)):return save_search(user['id'],body)
@router.put('/searches/{id}')
def update_search(id:str,body:SearchChange,user=Depends(auth.current)):return save_search(user['id'],body,id)
@router.delete('/searches/{id}')
def delete_search(id:str,user=Depends(auth.current)):
 if not db.get(user['id'],id,SEARCH_KIND):raise HTTPException(404,'Saved career search not found.')
 db.delete(user['id'],id);return {'searches':searches(user['id'])}
@router.get('/searches/{id}/load')
def load_search(id:str,user=Depends(auth.current)):
 row=db.get(user['id'],id,SEARCH_KIND)
 if not row:raise HTTPException(404,'Saved career search not found.')
 d=SearchRecord.model_validate(row['data']).model_dump();p=profile(user['id']);courses={c['title'].casefold():c['id'] for c in p['course_options']};missing=[];ids=[]
 for ref in d['course_refs']:
  match=courses.get(ref['title'].casefold())
  if match:ids.append(match)
  else:missing.append(ref['title'])
 d['query']['profile_course_ids']=list(dict.fromkeys(ids));d['query']['offset']=0
 skills={career_evidence.canonical(s['title']):s['id'] for s in p['skill_options']};missing_skills=[];skill_ids=[]
 for ref in d['skill_refs']:
  match=skills.get(career_evidence.canonical(ref['title']))
  if match:skill_ids.append(match)
  else:missing_skills.append(ref['title'])
 d['query']['profile_skill_ids']=list(dict.fromkeys(skill_ids))
 missing_area=d['query']['salary_area'] not in career_wages.data()['areas']
 return {**row,'data':d,'unavailable_courses':missing,'unavailable_skills':missing_skills,'unavailable_salary_area':missing_area}

class RenameSearch(StrictModel):
 name:str=Field(min_length=1,max_length=100)
 expected_updated_at:str=Field(max_length=100)
@router.patch('/searches/{id}')
def rename_search(id:str,body:RenameSearch,user=Depends(auth.current)):
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT * FROM entities WHERE user_id=? AND id=? AND kind=?',(user['id'],id,SEARCH_KIND)).fetchone()
  if not row:raise HTTPException(404,'Saved career search not found.')
  if row['updated_at']!=body.expected_updated_at:raise HTTPException(409,'This saved search changed. Reload Saved searches.')
  if not body.name.strip():raise HTTPException(422,'Name this career search.')
  value=json.loads(row['payload']);value['name']=body.name.strip();write(c,user['id'],SEARCH_KIND,value,id)
 return db.get(user['id'],id,SEARCH_KIND)


def search_digest(data):
 value=SearchRecord.model_validate(data).model_dump()
 # Course titles survive reference remapping during account backup restoration.
 value['query']['profile_course_ids']=[]
 value['query']['profile_skill_ids']=[]
 value['skill_refs']=sorted({career_evidence.canonical(r['title']) for r in value['skill_refs']})
 value['course_refs']=sorted({r['title'].casefold() for r in value['course_refs']})
 return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
def restore_search(user,data):
 if any(search_digest(r['data'])==search_digest(data) for r in searches(user)):return
 db.save(user,SEARCH_KIND,SearchRecord.model_validate(data).model_dump())
