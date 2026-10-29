"""Bounded read-only occupational/wage operations. No network, SQL or AI here."""
import hashlib,json,re
from typing import Literal
from pydantic import Field
from .models import StrictModel
from . import career_wages as wages,salary_areas
BLS_ID='public:bls-oews';OCC_ID='public:occupations'
class Lookup(StrictModel):
 operation:Literal['find_occupations','find_salary_areas','wages','compare_metros']
 query:str=Field(default='',max_length=200)
 occupation_code:str=Field(default='',max_length=15,pattern=r'^(?:\d{2}-\d{4}\.\d{2})?$')
 salary_area:str=Field(default='US',max_length=40)
 state:str=Field(default='',max_length=60)
 area_ids:list[str]=Field(default_factory=list,max_length=20)
 percentile:Literal['p10','p25','median','p75','p90']='median'
 unit:Literal['year','hour']='year'
 limit:int=Field(default=10,ge=1,le=20)

def public_sources():
 meta=wages.data()['metadata']
 return [{'record_id':BLS_ID,'kind':'public_dataset','label':'BLS OEWS wage tables · '+meta['reference'],'revision':hashlib.sha256(json.dumps(meta,sort_keys=True).encode()).hexdigest(),'status':'published','text':'Published BLS national, state and metro wage percentiles are available through local read operations. Not starting pay, experience levels, cost-of-living adjustments or live vacancies.'}, {'record_id':OCC_ID,'kind':'public_dataset','label':'O*NET occupation catalog','revision':'onet-31','status':'published','text':'Find occupation titles, established alternate titles and descriptions through read operations. Occupational requirements do not establish applicant qualifications.'}]
def occupations(query,limit=10):
 from . import career_explorer as ex
 q=salary_areas.norm(query)
 q={'data engineering':'data engineer','software engineering':'software developer'}.get(q,q)
 if q in ('de','it','bi'):return {'clarification_required':True,'message':'Spell out the occupation or select a specific O*NET occupation; this abbreviation is ambiguous.','candidates':[]}
 if not q:return {'clarification_required':True,'message':'Choose an occupation before comparing wages.','candidates':[]}
 terms=set(q.split());rows=[]
 for code,o in ex.OCCUPATIONS.items():
  titles=[o['title'],*[v[0] for v in ex.ALT_WORDS[code]]]
  exact=any(salary_areas.norm(t)==q for t in titles)
  matched=any(terms<=set(salary_areas.norm(t).split()) for t in titles)
  if exact or matched:rows.append((not exact,o['title'],{'code':code,'title':o['title'],'soc':code.split('.')[0],'matched_alternate_title':next((t for t in titles[1:] if salary_areas.norm(t)==q),''),'description':o['description']}))
 rows.sort(key=lambda r:(r[0],r[1]));exact=[r for r in rows if not r[0]];chosen=exact or rows
 return {'clarification_required':len(chosen)!=1,'candidates':[r[2] for r in chosen[:limit]],'message':'Choose an occupation when several meanings are possible; specialties may share broader wage figures.'}
def code_for(request):
 from . import career_explorer as ex
 if request.occupation_code:
  ex.occupation(request.occupation_code);return request.occupation_code,None
 found=occupations(request.query,request.limit)
 if not found['clarification_required']:return found['candidates'][0]['code'],None
 return None,found

def run(request,excluded=()):
 r=Lookup.model_validate(request);needed=OCC_ID if r.operation=='find_occupations' else BLS_ID
 if needed in excluded:return {'unavailable':True,'message':'This public dataset is excluded from this conversation.'}
 if r.operation=='find_occupations':return occupations(r.query,r.limit)
 if r.operation=='find_salary_areas':return {'areas':salary_areas.search(r.query,r.limit),'message':'Aliases select official published regions. The DMV/Northern Virginia result is the broader Washington metro, including DC, VA, MD and WV.'}
 if OCC_ID in excluded and not r.occupation_code:return {'unavailable':True,'message':'Occupation resolution is excluded; explicitly select an occupation code.'}
 code,uncertain=code_for(r)
 if uncertain:return uncertain
 if r.salary_area not in wages.data()['areas']:
  candidates=salary_areas.search(r.salary_area,20)
  if len(candidates)!=1:return {'clarification_required':True,'areas':candidates,'message':'Select a published salary area.'}
  r=r.model_copy(update={'salary_area':candidates[0]['id']})
 if r.operation=='wages':return {'occupation_code':code,'salary':wages.pay(code,r.salary_area)}
 if r.salary_area!='US' and not r.area_ids:r=r.model_copy(update={'area_ids':[r.salary_area]})
 allowed=None
 if r.state:
  state=salary_areas.norm(r.state);matches=[a for a in salary_areas.catalog() if a['type']=='state' and state in (salary_areas.norm(a['state']),salary_areas.norm(a['title']))]
  if len(matches)!=1:return {'clarification_required':True,'message':'Choose a full state name or two-letter state abbreviation.'}
  allowed=matches[0]['state']
 metro_ids=None
 if r.area_ids:
  requested=[wages.area(id) for id in r.area_ids]
  state_codes={a['state'] for a in requested if a['type']=='state'}
  metro_ids={a['id'] for a in salary_areas.catalog() if a['type']=='metro' and (any(v['id']=='US' for v in requested) or a['id'] in r.area_ids or bool(state_codes & set(a['state_codes'])))}
  if not metro_ids:return {'clarification_required':True,'message':'City comparisons use metro areas. Select a state or metro, or request a wage lookup for a nonmetropolitan area.'}
 rows=[];missing=0;index={'p10':0,'p25':1,'median':2,'p75':3,'p90':4}[r.percentile]
 for a in salary_areas.catalog():
  if a['type']!='metro' or allowed and allowed not in a['state_codes'] or metro_ids is not None and a['id'] not in metro_ids:continue
  pay=wages.pay(code,a['id']);values=pay['values'];v=(values['annual'] if r.unit=='year' else values['hourly'])[index] if values else None
  bound=v=='#';number=pay['reporting_threshold'].get(r.unit) if bound else v
  if not isinstance(number,(int,float)):missing+=1;continue
  rows.append((number,a['title'],{'area':{k:a[k] for k in ('id','title','type','state_codes')},'value':v,'published_floor':number if bound else None,'bounded':bound,'percentiles':{key:(values['annual'] if r.unit=='year' else values['hourly'])[i] for i,key in enumerate(('p10','p25','median','p75','p90'))}}))
 rows.sort(key=lambda x:(-x[0],x[1]))
 return {'occupation_code':code,'soc':code.split('.')[0],'wage_occupation':wages.pay(code)['occupation_title'],'shared_specialty':wages.pay(code)['shared_specialty'],'ranking_measure':r.percentile,'unit':r.unit,'rows':[v[2] for v in rows[:r.limit]],'matched_metros':len(rows),'excluded_missing_or_suppressed':missing,'reference':wages.data()['metadata']['reference'],'source_url':wages.data()['metadata']['url'],'limitations':'Metro areas, not individual city boundaries. Published distributions across workers, not starting salaries or years of experience. Nominal pay is not adjusted for living costs. Bounded estimates are sorted by their published floor, not an invented exact amount; equal floors are not evidence of distinct ranking. Missing local wages are never replaced with national values in rankings.'}

def source(request,result,index):
 text=json.dumps({'request':request,'result':result},ensure_ascii=False,sort_keys=True,indent=2)
 return {'source_id':'bls-lookup:'+str(index)+':'+hashlib.sha256(text.encode()).hexdigest()[:16],'record_id':OCC_ID if request['operation']=='find_occupations' else BLS_ID,'kind':'bls_lookup','label':'Local published lookup · '+request['operation'],'revision':hashlib.sha256(text.encode()).hexdigest(),'url':'https://www.onetonline.org/' if request['operation']=='find_occupations' else wages.data()['metadata']['url'],'text':text,'status':'published'}
