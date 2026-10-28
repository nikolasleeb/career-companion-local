"""Account-scoped career exploration from attributed public snapshots, without AI."""
import hashlib,json,re,unicodedata
from pathlib import Path
from typing import Annotated,Literal
from fastapi import APIRouter,Depends,HTTPException,Query
from pydantic import Field
from . import auth,db
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
PROGRAM_WORDS={code:subject(title) for code,title in DATA['programs'].items()}

class Explore(StrictModel):
 mode:Literal['studies','browse']='browse'
 major:str=Field(default='',max_length=300)
 courses:str=Field(default='',max_length=2000)
 profile_course_ids:list[Annotated[str,Field(pattern=r'^[a-f0-9]{24}$')]]=Field(default_factory=list,max_length=1000)
 query:str=Field(default='',max_length=120)
 industry:str=Field(default='',max_length=8)
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
 majors=[];skills=[];course_rows={}
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
  skills.extend(s['name'] for s in d.get('skill_items',[]) if isinstance(s,dict) and isinstance(s.get('name'),str))
 unique=lambda v:list(dict.fromkeys(x.strip() for x in v if isinstance(x,str) and x.strip()))
 choices=sorted(course_rows.values(),key=lambda x:x['title'].casefold())
 return {'majors':unique(majors)[:6],'courses':[c['title'] for c in choices],'course_options':choices,'skills':unique(skills)}

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

def summary(code,reason='',also=''):
 o=OCCUPATIONS[code]
 return {k:o[k] for k in ('title','description','job_zone','median_wage','wage_year','wage_note','growth','growth_note','openings')}|{'code':code,'preparation':ZONES.get(o['job_zone'],'Preparation not reported'),'reason':reason,'also':also,'onet_url':'https://www.onetonline.org/link/summary/'+code,'dataset_version':META['version']}

@router.get('/options')
def options(user=Depends(auth.current)):
 p=profile(user['id'])
 return {'profile':{k:p[k] for k in ('majors','courses','course_options')},'industries':DATA['sectors'],'metadata':META,'occupations':len(OCCUPATIONS),'saved_limit':MAX_SAVED}

@router.post('/explore')
def explore(body:Explore,user=Depends(auth.current)):
 if body.industry and body.industry not in {s['naics'] for s in DATA['sectors']}:raise HTTPException(422,'Choose an industry from the list.')
 selected_courses=[]
 if body.mode=='studies':
  choices={c['id']:c['title'] for c in profile(user['id'])['course_options']}
  if any(id not in choices for id in body.profile_course_ids):raise HTTPException(409,'A selected course is no longer in your confirmed Profile. Reload Career Explorer and review your selection.')
  selected_courses=[choices[id] for id in dict.fromkeys(body.profile_course_ids)]
  if not (body.major.strip() or body.courses.strip() or selected_courses):raise HTTPException(422,'Enter a major, select a Profile course, or choose Explore other directions.')
 links,matched=study_links(body,selected_courses) if body.mode=='studies' else ({},[])
 query=body.query.strip();need=words(query);rows=[]
 for code,o in OCCUPATIONS.items():
  if body.preparation=='college' and o['job_zone'] not in (4,5):continue
  if body.industry and o['sectors'].get(body.industry,0)<1:continue
  if body.mode=='studies' and code not in links:continue
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
  if body.sort in ('pay','growth'):
   value=o['median_wage' if body.sort=='pay' else 'growth']
   return (value is None,-value if value is not None else 0,o['title'])
  if body.sort=='title':return (o['title'],)
  return (-quality,-tier,-o['sectors'].get(body.industry,0),o['title'])
 rows.sort(key=order)
 return {'results':[summary(code,reason,also) for code,_,_,reason,also in rows[body.offset:body.offset+body.limit]],'total':len(rows),'offset':body.offset,'matched_programs':matched,'metadata':META,'notice':'No education-program connection was found. Try a fuller major name, or Explore other directions.' if body.mode=='studies' and not matched else ''}

@router.get('/occupations/{code}')
def detail(code:str,user=Depends(auth.current)):
 o=occupation(code);p=profile(user['id']);known={frozenset(words(s)) for s in p['skills']}
 def annotate(item):return {**item,'profile_status':'Recorded in Profile' if frozenset(words(item['name'])) in known else 'Not documented in Profile'}
 return {**summary(code),'skills':[annotate(s) for s in o['skills']],'technologies':[annotate(t) for t in o['technologies']],'industries':[{'naics':s['naics'],'title':s['title'],'share':o['sectors'][s['naics']]} for s in DATA['sectors'] if s['naics'] in o['sectors']],'related':[{'code':c,'title':OCCUPATIONS[c]['title']} for c in o['related'] if c in OCCUPATIONS],'metadata':META}

def saved_list(user):
 rows=list(reversed(db.list_entities(user,'saved_career')))
 return {'careers':[{'id':r['id'],'created_at':r['created_at'],**(summary(r['data']['code']) if r['data']['code'] in OCCUPATIONS else {**r['data'],'unavailable':True})} for r in rows],'limit':MAX_SAVED}

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
def saved(user=Depends(auth.current)):return saved_list(user['id'])
@router.post('/saved')
def add(body:SaveCareer,user=Depends(auth.current)):
 save(user['id'],body);return saved_list(user['id'])
@router.delete('/saved/{id}')
def remove(id:str,user=Depends(auth.current)):
 if not db.get(user['id'],id,'saved_career'):raise HTTPException(404,'Saved career not found.')
 db.delete(user['id'],id);return saved_list(user['id'])

def validate_backup(record):
 if record['kind']=='saved_career':SavedCareer.model_validate(record['data'])
def validate_import(user,records):
 codes={r['data']['code'] for r in db.list_entities(user,'saved_career')}
 codes.update(r['data']['code'] for r in records if r['kind']=='saved_career')
 if len(codes)>MAX_SAVED:raise ValueError('Too many saved careers.')
def restore(user,data):save(user,SaveCareer(code=data['code'],source=data['source']),restored=SavedCareer.model_validate(data).model_dump())
