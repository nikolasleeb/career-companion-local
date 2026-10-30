"""Explicit project associations with owned Profile jobs, never employer postings."""
import json
from fastapi import HTTPException

def unresolved(c,user,data):
 missing=[]
 for id in data.get('linked_employment_ids',[]):
  row=c.execute("SELECT payload FROM entities WHERE id=? AND user_id=? AND kind='experience'",(id,user)).fetchone()
  target=json.loads(row['payload']) if row else {}
  if target.get('category')!='employment' or not target.get('confirmed'):missing.append(id)
 return missing

def validate(c,user,data,previous=None,restoring=False):
 ids=data.get('linked_employment_ids',[])
 if ids and data.get('category')!='project':raise HTTPException(422,'Only projects can have related jobs.')
 if len(ids)>10 or len(set(ids))!=len(ids):raise HTTPException(422,'Choose up to ten different jobs.')
 previous=set((previous or {}).get('linked_employment_ids',[]))
 if not restoring and any(id not in previous for id in unresolved(c,user,data)):
  raise HTTPException(422,'Choose confirmed jobs from your own Profile.')

def available(user,data):
 from . import db
 with db.connect() as c:return not unresolved(c,user,data)

def backup_markers(value,known):
 """Mark missing historical references in the export only; never rewrite records."""
 if isinstance(value,list):
  for row in value:backup_markers(row,known)
 elif isinstance(value,dict):
  from .profile_answers import experience_ids
  if 'experience_ids' in value or value.get('experience_id'):
   value['unavailable_experience_ids']=[id for id in experience_ids(value) if id not in known]
  if 'linked_employment_ids' in value:value['unavailable_employment_ids']=[id for id in value['linked_employment_ids'] if id not in known]
  for key,row in list(value.items()):
   if key not in ('unavailable_experience_ids','unavailable_employment_ids'):backup_markers(row,known)
