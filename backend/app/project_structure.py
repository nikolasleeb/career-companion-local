"""Canonical project statements and explicit, account-owned attribution stages.

Legacy projection is read-only. An unreviewed multi-parent statement belongs only
on the project, never on any of its parents. Stage IDs survive backup remapping.
"""
import copy,hashlib,json,re
from fastapi import HTTPException
from .models import ProjectStatementScope,ProjectStage,ProjectStatement

FIELDS=('description','contribution','accomplishments')
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def parents(data):
 return list(dict.fromkeys([*data.get('linked_employment_ids',[]),*data.get('linked_education_ids',[]),*[v['education_id'] for v in data.get('linked_courses',[])]]))
def timeline_enabled(data):return data.get('category')=='project' and len(parents(data))>=2
def stage_id(parent):return parent+':stage'
def stages(data):
 saved={v['parent_id']:copy.deepcopy(v) for v in data.get('project_stages') or []}
 return [saved.get(p,{'id':stage_id(p),'parent_id':p,'start_date':'','end_date':''}) for p in parents(data)]
def default_scope(data):
 values=stages(data)
 return {'kind':'unassigned','stage_ids':[]} if len(values)>1 else {'kind':'stages','stage_ids':[values[0]['id']]} if values else {'kind':'project','stage_ids':[]}
def lines(text):
 # Keep legacy paragraphs and explicit continuation lines together; never split sentences.
 from .resume_data import profile_bullets
 return profile_bullets(text)
def statements(data):
 if data.get('project_statements') is not None:return copy.deepcopy(data['project_statements'])
 return [{'id':'legacy-'+field+'-'+str(i),'field':field,'text':text,'scope':default_scope(data)} for field in FIELDS for i,text in enumerate(lines(data.get(field,'')))]
def scope_for_detail(data,project_id,project):
 scope=copy.deepcopy(data.get('project_scopes',{}).get(project_id) or default_scope(project))
 if data.get('status')=='archived' and set(scope.get('stage_ids',[]))-{s['id'] for s in stages(project)}:return {'kind':'unassigned','stage_ids':[]}
 return scope
def destinations(scope,data):
 if scope.get('kind')=='project':return parents(data)
 if scope.get('kind')=='stages':return [s['parent_id'] for s in stages(data) if s['id'] in scope.get('stage_ids',[])]
 return []
def permits(scope,data,parent):return parent in destinations(scope,data)
def validate_scope(scope,data):
 value=ProjectStatementScope.model_validate(scope).model_dump()
 ids=value['stage_ids'];known={s['id'] for s in stages(data)}
 if len(ids)!=len(set(ids)) or set(ids)-known or (value['kind']=='stages')!=bool(ids):raise HTTPException(422,'Choose current project stages, Whole project, or Awaiting assignment.')
 return value

def prepare(c,user,data,previous=None,restoring=False,reviewed_scope_ids=()):
 if data.get('category')!='project':
  if data.get('project_stages') or data.get('project_statements'):raise HTTPException(422,'Only projects have project timelines.')
  return {k:v for k,v in data.items() if k!='_record_id'}
 old=previous or {};data=copy.deepcopy(data)
 if old.get('project_statements') is not None and data.get('project_statements')==old['project_statements'] and any(data.get(f,'')!=old.get(f,'') for f in FIELDS):data['project_statements']=None
 if old and data.get('project_stages') in (old.get('project_stages'),stages(old)) and parents(data)!=parents(old):data['project_stages']=stages({**data,'project_stages':stages(old)})
 # Compatibility editors retain identities for exact and one-to-one edits.
 # Ambiguous edits need attribution review only for shared projects.
 if data.get('project_statements') is None and (old.get('project_statements') is not None or len(parents(old))==1 and timeline_enabled(data)):
  before=statements(old);items=[]
  for field in FIELDS:
   texts=lines(data.get(field,''));previous=[v for v in before if v['field']==field];used=set();matched=[]
   for text in texts:
    match=next((v for v in previous if v['text']==text and v['id'] not in used),None)
    matched.append(copy.deepcopy(match) if match else None)
    if match:used.add(match['id'])
   remaining=[v for v in previous if v['id'] not in used];missing=[i for i,v in enumerate(matched) if v is None]
   if len(remaining)==len(missing)==1:matched[missing[0]]={**copy.deepcopy(remaining[0]),'text':texts[missing[0]],**({'scope':default_scope(data)} if not timeline_enabled(data) and remaining[0]['scope']['kind']=='unassigned' else {})}
   else:
    for i in missing:matched[i]={'id':'statement-'+digest([field,texts[i],i])[:24],'field':field,'text':texts[i],'scope':{'kind':'unassigned','stage_ids':[]} if remaining and timeline_enabled(data) else default_scope(data)}
   items.extend(matched)
  data['project_statements']=items
 if data.get('project_stages') is None and old.get('project_stages') is not None:
  data['project_stages']=stages({**data,'project_stages':old['project_stages']})
 if data.get('project_stages') is not None:
  values=[ProjectStage.model_validate(v).model_dump() for v in data['project_stages']]
  if len({s['id'] for s in values})!=len(values) or len({s['parent_id'] for s in values})!=len(values) or {s['parent_id'] for s in values}!=set(parents(data)):raise HTTPException(422,'Each related job or education entry needs one project stage.')
  for s in values:
   for field in ('start_date','end_date'):
    if s[field] and s[field]!='Present' and not re.fullmatch(r'\d{4}(?:-\d{2})?(?:-\d{2})?',s[field]):raise HTTPException(422,'Use a year, year-month, or full date for project stages.')
   from datetime import date
   for value in (s['start_date'],s['end_date']):
    if value and value!='Present':
     try:date.fromisoformat(value+('-01-01' if len(value)==4 else '-01' if len(value)==7 else ''))
     except ValueError:raise HTTPException(422,'Enter a valid project-stage date.') from None
   if s['start_date'] and s['end_date'] and s['end_date']!='Present' and s['start_date']>s['end_date']:raise HTTPException(422,'Project-stage end date must follow its start date.')
  data['project_stages']=values
 if data.get('project_statements') is not None:
  values=[ProjectStatement.model_validate(v).model_dump() for v in data['project_statements']]
  if len({v['id'] for v in values})!=len(values) or any(not v['text'].strip() for v in values):raise HTTPException(422,'Each project statement needs text and a unique identity.')
  if set(reviewed_scope_ids)-{v['id'] for v in values}:raise HTTPException(422,'Review only current project bullets.')
  for v in values:v['scope']=validate_scope(v['scope'],data)
  # A legacy single-parent Whole project statement must not acquire a second
  # destination just because a connection was added. Explicitly changed scopes
  # remain the user's choice. Stored IDs and dates are never discarded.
  if len(parents(old))==1 and timeline_enabled(data) and not restoring:
   prior={v['id']:v for v in statements(old)}
   for v in values:
    before=prior.get(v['id'])
    if before and v['id'] not in reviewed_scope_ids and before['scope']['kind']=='project' and v['scope']==before['scope']:v['scope']=default_scope(old)
  # Preserve raw legacy strings byte-for-byte when only assignments/dates change.
  for field in FIELDS:
   texts=[v['text'] for v in values if v['field']==field]
   if texts!=lines(data.get(field,'')):data[field]='\n'.join(texts)
   if len(data.get(field,''))>(12000 if field=='description' else 6000):raise HTTPException(422,'The project overview is too long. Move deeper statements to Supporting Details.')
  data['project_statements']=values
 # Freeze legacy implicit scope before changing its parent set. Adding a second
 # parent must not turn a formerly single-stage detail into shared evidence.
 if old and parents(data)!=parents(old) and not restoring:
  pid=data.get('_record_id','')
  from .resume_conversation import write
  from . import db
  for raw in c.execute("SELECT * FROM entities WHERE user_id=? AND kind='profile_answer'",(user,)).fetchall():
   row=db.decode(raw);a=copy.deepcopy(row['data'])
   links=a.get('experience_ids',[a.get('experience_id')])
   if pid not in links or a.get('status')=='archived':continue
   scope=a.get('project_scopes',{}).get(pid)
   if scope and not (len(parents(old))==1 and timeline_enabled(data) and scope['kind']=='project'):continue
   a.setdefault('history',[]).append({**copy.deepcopy(a),'history':[]})
   a.setdefault('project_scopes',{})[pid]=default_scope(old);a['version']=a.get('version',0)+1
   write(c,user,'profile_answer',a,row['id'])
 # A relationship edit must resolve affected Supporting Details too.
 removed={s['id'] for s in stages(old)}-{s['id'] for s in stages(data)}
 if removed and not restoring:
  for row in c.execute("SELECT payload FROM entities WHERE user_id=? AND kind='profile_answer'",(user,)):
   a=json.loads(row[0]);scope=a.get('project_scopes',{}).get(data.get('_record_id',''))
   if scope and set(scope.get('stage_ids',[]))&removed and a.get('status')!='archived':raise HTTPException(409,'Reassign this stage’s Supporting Details before detaching it.')
 data.pop('_record_id',None)
 return data

def enrich_snapshot(entry):
 if entry.get('category')!='project':return entry
 items=[];used=set()
 for item in entry.get('content_items',[]):
  field='accomplishments' if item['field']=='accomplishment' else item['field']
  match=next((v for v in statements(entry) if v['field']==field and v['text']==item['original'] and v['id'] not in used),None)
  if match:
   used.add(match['id']);item={**item,'item_id':match['id'],'project_scope':match['scope'],'allowed_parent_ids':destinations(match['scope'],entry)}
  elif item['field'] in ('description','contribution','accomplishment'):
   answer=next((a for a in entry.get('reviewed_answer_sources',entry.get('answer_sources',[])) if a.get('text')==item['original']),None)
   scope=(answer or {}).get('project_scope') or default_scope(entry)
   item={**item,'project_scope':scope,'allowed_parent_ids':destinations(scope,entry)}
  items.append(item)
 return {**entry,'content_items':items}

def validate_backup(record,kinds,records):
 d=record['data']
 if record['kind']=='experience' and d.get('category')=='project':
  if d.get('project_stages') is not None:
   if {s['parent_id'] for s in d['project_stages']}!=set(parents(d)) or len({s['id'] for s in d['project_stages']})!=len(d['project_stages']):raise ValueError('Invalid project stages')
  if d.get('project_statements') is not None:
   if len({v['id'] for v in d['project_statements']})!=len(d['project_statements']):raise ValueError('Duplicate statement')
   for v in d['project_statements']:
    try:validate_scope(v['scope'],d)
    except HTTPException:raise ValueError('Invalid project scope') from None
 if record['kind']=='profile_answer':
  for pid,scope in d.get('project_scopes',{}).items():
   if pid not in d.get('experience_ids',[d.get('experience_id')]):raise ValueError('Unlinked detail project')
   if pid not in records:
    if pid in d.get('unavailable_experience_ids',[]):continue
    raise ValueError('Missing detail project')
   if kinds.get(pid)!='experience' or records[pid]['data'].get('category')!='project':raise ValueError('Invalid detail project')
   if d.get('status')=='archived':continue
   try:validate_scope(scope,records[pid]['data'])
   except HTTPException:raise ValueError('Invalid detail stage') from None
