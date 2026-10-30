"""Current professional evidence and compact relationships, selected locally before AI.

No settings, private answers, assessment ratings or arbitrary entity dumps belong here.
"""
import copy,hashlib,json,re
from . import db,personalization

FIELDS=('title','degree','major','minor','majors','minors','concentration','description','contribution','tools','relevant_courses','accomplishments','gpa','gpa_scale','honors','skill_items','certification_items')
RULE='Relationships provide context, not additional qualifications or separate accomplishments. Reuse each Supporting Detail once.'
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def relationships(records):
 catalog={r['id']:r for r in records}
 def label(record):
  d=record['data']
  return {'id':record['id'],**{k:d[k] for k in ('category','title','organization','dates','start_date','end_date') if d.get(k)}}
 links={id:[] for id in catalog}
 from . import project_relations
 for row in records:
  for kind,id,course in project_relations.targets(row['data']):
   if id not in catalog:continue
   links[row['id']].append({**label(catalog[id]),**({'course':course} if course else {})})
   links[id].append({**label(row),**({'course':course} if course else {})})
 return links
def records(user,*,guidance=True):
 from . import profile_answers
 if guidance and not personalization.allowed(user):return []
 rows=profile_answers.records(user);links=relationships(rows)
 for row in rows:
  row['data']['relationship_context']=links[row['id']]
 return rows
def sources(user):
 from . import job_ai,certifications
 rows=records(user);result=[]
 for row in rows:
  d=row['data'];original=(db.get(user,row['id'],'experience') or row)['data']
  def add(field,text,**extra):
   text=job_ai.clean(text)
   if not text.strip():return
   if field=='context':
    result.append({'id':row['id']+':context','record_id':row['id'],'field':field,'text':text,**extra})
    return
   # Keep complete ordinary bullets/continuations together. Large fields get searchable chunks.
   blocks=re.split(r'\n(?=[•*\-] )',text) if len(text)>2400 else [text]
   chunks=[];chunk=''
   for block in blocks:
    if chunk and len(chunk)+len(block)>2400:chunks.append(chunk);chunk=''
    for at in range(0,len(block),2400):
     part=block[at:at+2400]
     if chunk and len(chunk)+len(part)>2400:chunks.append(chunk);chunk=''
     chunk+='\n'+part if chunk else part
   if chunk:chunks.append(chunk)
   for i,part in enumerate(chunks):
    result.append({'id':row['id']+':'+field+(':'+str(i) if len(chunks)>1 else ''),'record_id':row['id'],'field':field,'text':part,**extra})
  for field in FIELDS:
   value=original.get(field)
   if field=='certification_items' and value:value=[{k:v[k] for k in ('name','issuer','earned_date','expiration_date','does_not_expire') if k in v} for v in certifications.rows(d)]
   if isinstance(value,(dict,list)):value=json.dumps(value,ensure_ascii=False)
   if value not in (None,'',[],{}):add(field,str(value))
  if d.get('individual_project') is True:add('individual_project','Individual project')
  info={k:d[k] for k in ('category','organization','dates','start_date','end_date','expected_graduation','work_arrangement') if d.get(k)}
  info['related_experiences']=d['relationship_context']
  add('context',json.dumps(info,ensure_ascii=False),context_only=True)
  for a in d.get('answer_sources',[]):
   text=job_ai.clean(a['text'])
   if text:result.append({'id':a['id']+':answer','record_id':a['id'],'experience_id':row['id'],'experience_ids':a['experience_ids'],'field':'answer','text':text,'detail_version':a['version'],'provenance':copy.deepcopy(a['provenance'])})
 return result,rows
def select(profile,query='',budget=18000):
 """All sources are eligible; only relevant passages and selected records' context travel."""
 words=set(re.findall(r'[\w+#]{3,}',query.casefold()))-{'the','and','with','your','that','this','for','from','what','how','about','profile'}
 rows=profile['sources'];facts=[s for s in rows if s['field']!='context'];metadata={s['record_id']:s for s in rows if s['field']=='context'}
 def score(s):return len(words&set(re.findall(r'[\w+#]{3,}',s['text'].casefold())))
 ranked=sorted(enumerate(facts),key=lambda x:(-score(x[1]),x[1]['field']!='title',x[0]))
 selected=[];used=0;included=set()
 for _,source in ranked:
  if words and not score(source):continue
  id=source.get('experience_id',source['record_id']);context=metadata.get(id)
  extras=[context] if context and id not in included else []
  cost=len(json.dumps(source,ensure_ascii=False))+sum(len(json.dumps(s,ensure_ascii=False)) for s in extras)
  if used+cost>budget:continue
  selected.extend([source]+extras);used+=cost;included.add(id)
 # A broad request or no lexical match gets a bounded overview, never an empty accidental match.
 if not selected and rows:return select(profile,'',budget) if words else {**profile,'sources':[],'context_limited':True}
 return {**profile,'sources':selected,'context_limited':profile.get('context_limited',False) or len(selected)<len(rows),'context_characters':used}
def profile(user,query='',budget=18000):
 rows,records_=sources(user)
 value={'sources':rows,'record_count':len(records_),'context_limited':False,'revision':digest({'sources':rows,'sharing':personalization.stamp(user),'context_version':personalization.request_version(user)}),'relationship_rules':RULE}
 return select(value,query,budget)
