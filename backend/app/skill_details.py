"""Stable individual skills and single-skill evidence over existing Profile records."""
import copy,hashlib,json,re
from fastapi import HTTPException
from . import db,certifications

def is_group(data):return data.get('category')=='skills' and not certifications.is_group(data)
def items(data,record_id):
 if not is_group(data):return []
 rows=data.get('skill_items') or [{'name':v.strip(),'level':'unknown'} for v in re.split(r'[,;\n]+',data.get('tools','')) if v.strip()]
 return [{**v,'id':v.get('id') or hashlib.sha256((record_id+':skill:'+str(i)+':'+v['name']).encode()).hexdigest()[:32]} for i,v in enumerate(rows)]
def decorate(row):
 if is_group(row['data']):row={**row,'data':{**row['data'],'skill_items':items(row['data'],row['id'])}}
 return row

def require(c,user,group,skill):
 row=db.decode(c.execute("SELECT * FROM entities WHERE id=? AND user_id=? AND kind='experience'",(group,user)).fetchone())
 value=next((v for v in items(row['data'],group) if v['id']==skill),None) if row else None
 if not value:raise HTTPException(404,'Skill not found in this Profile group.')
 return row,value

def validate_ref(c,user,data):
 ref=data.get('skill_ref')
 if not ref:return
 from . import profile_answers
 if set(ref)!={'experience_id','skill_id'} or ref['experience_id'] not in profile_answers.experience_ids(data) or data.get('course_refs'):raise HTTPException(422,'Choose one individual skill in the linked skill group.')
 require(c,user,ref['experience_id'],ref['skill_id'])

def pending(data,records):
 if data.get('skill_ref'):return False
 from . import profile_answers
 return any(is_group(records[id]['data']) for id in profile_answers.experience_ids(data) if id in records)

def prepare(c,user,record_id,data,previous=None,resolutions=None,restoring=False):
 old=previous or {};before=items(old,record_id)
 if not is_group(data):
  after=[]
 elif not data.get('skill_items') and not old.get('skill_items'):
  # Legacy tools-only clients retain their fields; readers project repeatable IDs.
  after=items(data,record_id)
 else:
  after=[];used=set()
  for v in data.get('skill_items') or [{'name':v.strip(),'level':'unknown'} for v in re.split(r'[,;\n]+',data.get('tools','')) if v.strip()]:
   v=copy.deepcopy(v)
   if not v.get('id'):
    match=next((s for s in before if s['name']==v['name'] and s['id'] not in used),None)
    v['id']=match['id'] if match else db.uid()
   if v['id'] in used:raise HTTPException(422,'Each skill needs a unique identity.')
   used.add(v['id']);after.append(v)
  data={**data,'skill_items':after}
 identities={v['id'] for v in after}
 if identities&{'pending','archive'} or any(not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',id) for id in identities):raise HTTPException(422,'Use a unique generated identity for each skill.')
 if identities:
  slots=','.join('?' for _ in identities)
  if c.execute('SELECT 1 FROM entities WHERE user_id=? AND id IN ('+slots+')',(user,*identities)).fetchone():raise HTTPException(422,'Skill identities must be separate from record identities.')
  for raw in c.execute("SELECT * FROM entities WHERE user_id=? AND kind='experience' AND id!=?",(user,record_id)):
   other=db.decode(raw)
   if identities&{v['id'] for v in items(other['data'],other['id'])}:raise HTTPException(422,'Each skill must have its own identity within your account.')
 removed={v['id'] for v in before}-{v['id'] for v in after}
 if removed and not restoring:
  for raw in c.execute("SELECT * FROM entities WHERE user_id=? AND kind='profile_answer'",(user,)).fetchall():
   row=db.decode(raw);a=row['data'];ref=a.get('skill_ref') or {}
   if ref.get('experience_id')!=record_id or ref.get('skill_id') not in removed:continue
   choice='pending' if a.get('status')=='archived' else (resolutions or {}).get(ref['skill_id'])
   if not choice:raise HTTPException(409,'This skill has Supporting Details. Choose another skill, Awaiting assignment, or Archive before removing it. Your edits are kept.')
   a=copy.deepcopy(a);a.setdefault('history',[]).append({**copy.deepcopy(a),'history':[]});a['version']=a.get('version',0)+1
   if choice=='archive':a['status']='archived';a.pop('skill_ref',None)
   elif choice=='pending':a.pop('skill_ref',None)
   elif choice in {v['id'] for v in after}:a['skill_ref']={'experience_id':record_id,'skill_id':choice}
   else:raise HTTPException(422,'Choose a remaining skill for these statements.')
   c.execute("UPDATE entities SET payload=?,updated_at=? WHERE id=? AND user_id=? AND kind='profile_answer'",(json.dumps(a),db.now(),row['id'],user))
 return data

def validate_backup(record,kinds,records):
 d=record['data']
 if record['kind']=='experience' and is_group(d):
  values=items(d,record['id'])
  if len({v['id'] for v in values})!=len(values):raise ValueError('Duplicate skill identity')
 if record['kind']=='profile_answer' and d.get('skill_ref'):
  ref=d['skill_ref'];group=records.get(ref.get('experience_id'))
  from . import profile_answers
  if not group and ref.get('experience_id') in d.get('unavailable_experience_ids',[]) and d.get('status')=='archived':return
  if set(ref)!={'experience_id','skill_id'} or not group or group['kind']!='experience' or ref['experience_id'] not in profile_answers.experience_ids(d) or d.get('course_refs') or not any(v['id']==ref['skill_id'] for v in items(group['data'],group['id'])):raise ValueError('Invalid individual skill reference')
