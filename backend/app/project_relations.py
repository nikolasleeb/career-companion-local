"""Explicit project associations with owned Profile experience, never postings."""
import json,re
from fastapi import HTTPException

FIELDS=('linked_employment_ids','linked_education_ids','linked_courses')
def courses(text):
 return list(dict.fromkeys(v.strip() for v in re.split(r'[\n;,]+',text or '') if v.strip()))

def targets(data):
 for id in data.get('linked_employment_ids',[]):yield ('employment',id,'')
 for id in data.get('linked_education_ids',[]):yield ('education',id,'')
 for link in data.get('linked_courses',[]):yield ('course',link['education_id'],link['course'])

def unresolved(c,user,data):
 missing=[]
 for kind,id,course in targets(data):
  row=c.execute("SELECT payload FROM entities WHERE id=? AND user_id=? AND kind='experience'",(id,user)).fetchone()
  target=json.loads(row['payload']) if row else {}
  allowed=('education',) if kind=='course' else ('education','coursework') if kind=='education' else ('employment',)
  if target.get('category') not in allowed or not target.get('confirmed') or course and course not in courses(target.get('relevant_courses','')):missing.append((kind,id,course))
 return missing

def validate(c,user,data,previous=None,restoring=False):
 links=list(targets(data))
 if links and data.get('category') not in ('project','employment'):raise HTTPException(422,'Only projects and jobs can have related education.')
 if data.get('category')=='employment' and data.get('linked_employment_ids'):raise HTTPException(422,'Jobs can link to education and courses, not other jobs.')
 if len(links)>10 or len(set(links))!=len(links):raise HTTPException(422,'Choose up to ten different jobs, education entries or courses.')
 previous=set(targets(previous or {}))
 if not restoring and any(link not in previous for link in unresolved(c,user,data)):
  raise HTTPException(422,'Choose confirmed education, courses and jobs from your own Profile.')

def available(user,data):
 from . import db
 with db.connect() as c:return not unresolved(c,user,data)

def validate_backup(data,kinds,records):
 links=list(targets(data))
 if links and data.get('category') not in ('project','employment') or len(links)>10 or len(set(links))!=len(links):raise ValueError()
 if data.get('category')=='employment' and data.get('linked_employment_ids'):raise ValueError()
 for kind,id,course in links:
  marker='unavailable_employment_ids' if kind=='employment' else 'unavailable_education_ids'
  if id not in kinds:
   if id not in data.get(marker,[]):raise ValueError()
  else:
   target=records[id]['data'];allowed=('employment',) if kind=='employment' else ('education',) if kind=='course' else ('education','coursework')
   if kinds[id]!='experience' or target.get('category') not in allowed:raise ValueError()
 # Historical course names may have been edited; keep the exact saved association unresolved.

def backup_markers(value,known):
 """Mark missing historical references in the export only; never rewrite records."""
 if isinstance(value,list):
  for row in value:backup_markers(row,known)
 elif isinstance(value,dict):
  from .profile_answers import experience_ids
  if 'experience_ids' in value or value.get('experience_id'):
   value['unavailable_experience_ids']=[id for id in experience_ids(value) if id not in known]
  if 'linked_employment_ids' in value:value['unavailable_employment_ids']=[id for id in value['linked_employment_ids'] if id not in known]
  if 'linked_education_ids' in value or 'linked_courses' in value:value['unavailable_education_ids']=list(dict.fromkeys(id for kind,id,course in targets(value) if kind!='employment' and id not in known))
  for key,row in list(value.items()):
   if key not in ('unavailable_experience_ids','unavailable_employment_ids','unavailable_education_ids'):backup_markers(row,known)
