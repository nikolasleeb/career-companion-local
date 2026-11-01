"""Atomic owner-scoped statement lists over the existing reviewed-detail store."""
import copy,json
from fastapi import APIRouter,Depends,HTTPException
from pydantic import Field
from . import auth,db,profile_answers,project_structure as structure,course_evidence,skill_details
from .models import StrictModel,ProjectStatementScope,ExperienceItem
router=APIRouter()

class DetailStatement(StrictModel):
 id:str=Field(min_length=1,max_length=100)
 text:str=Field(min_length=1,max_length=12000)
 scope:ProjectStatementScope|None=None
class DetailListSave(StrictModel):
 revision:str=Field(min_length=64,max_length=64)
 statements:list[DetailStatement]=Field(max_length=400)
 course_id:str=Field(default='',max_length=64)
 skill_id:str=Field(default='',max_length=100)
 confirmed:bool=False
class StructureSave(StrictModel):
 expected_updated_at:str
 details_revision:str=''
 detached_stage_scopes:dict[str,ProjectStatementScope]=Field(default_factory=dict,max_length=10)
 data:ExperienceItem
 removed_skill_scopes:dict[str,str]=Field(default_factory=dict,max_length=100)
 reviewed_project_scope_ids:list[str]=Field(default_factory=list,max_length=400)

class SkillAssignment(StrictModel):
 id:str=Field(min_length=1,max_length=100)
 skill_id:str=Field(default='',max_length=100)
 archived:bool=False
class SkillAssignments(StrictModel):
 revision:str=Field(min_length=64,max_length=64)
 statements:list[SkillAssignment]=Field(max_length=400)

def owned(c,user,id):
 row=db.decode(c.execute("SELECT * FROM entities WHERE id=? AND user_id=? AND kind='experience'",(id,user)).fetchone())
 if not row:raise HTTPException(404,'Profile entry not found.')
 return row

def context_rows(c,user,id,course='',skill=''):
 rows=[]
 for raw in c.execute("SELECT * FROM entities WHERE user_id=? AND kind='profile_answer' ORDER BY created_at,id",(user,)):
  row=db.decode(raw);d=row['data']
  if d.get('answer_kind')!='experience' or id not in profile_answers.experience_ids(d):continue
  ref=d.get('skill_ref') or {}
  if skill:
   if ref!={'experience_id':id,'skill_id':skill}:continue
  elif ref:continue
  refs=d.get('course_refs',[])
  if course:
   if not any(r['education_id']==id and r['course_id']==course for r in refs):continue
  elif refs:continue
  rows.append(row)
 return rows

def listing(c,user,id,course='',skill=''):
 owner=owned(c,user,id)
 if course and skill:raise HTTPException(422,'Choose a class or a skill, not both.')
 if skill:skill_details.require(c,user,id,skill)
 if course:course_evidence.require_class(user,id,course,False)
 rows=context_rows(c,user,id,course,skill);context=skill or id+(':'+course if course else '')
 rows.sort(key=lambda r:(r['data'].get('detail_order',{}).get(context,100000),r['created_at'],r['id']))
 active=[r for r in rows if r['data'].get('status')!='archived']
 revision_rows=[db.decode(r) for r in c.execute("SELECT * FROM entities WHERE user_id=? AND kind='profile_answer' ORDER BY id",(user,)) if id in profile_answers.experience_ids(json.loads(r['payload']))] if skill_details.is_group(owner['data']) else rows
 revision=structure.digest({'owner':owner['updated_at'],'course':course,'skill':skill,'rows':[(r['id'],r['updated_at'],r['data']) for r in revision_rows]})
 return {'revision':revision,'owner':skill_details.decorate(owner),'timeline_enabled':structure.timeline_enabled(owner['data']),'course_id':course,'skill_id':skill,'statements':[{'id':r['id'],'text':r['data']['text'],'status':r['data']['status'],'scope':structure.scope_for_detail(r['data'],id,owner['data']) if owner['data']['category']=='project' else None,'backed_fields':bool(r['data'].get('backed_fields'))} for r in active],'archived_statements':[{'id':r['id'],'text':r['data']['text'],'scope':structure.scope_for_detail(r['data'],id,owner['data']) if owner['data']['category']=='project' else None,'backed_fields':bool(r['data'].get('backed_fields'))} for r in rows if r['data']['status']=='archived'],'archived_count':len(rows)-len(active),'stages':structure.stages(owner['data']) if owner['data']['category']=='project' else []}

@router.get('/api/experience/{id}/supporting-details')
def get_details(id:str,course_id:str='',skill_id:str='',user=Depends(auth.current)):
 with db.connect() as c:return listing(c,user['id'],id,course_id,skill_id)

@router.put('/api/experience/{id}/supporting-details')
def put_details(id:str,body:DetailListSave,user=Depends(auth.current)):
 from .resume_conversation import write
 u=user['id']
 if not body.confirmed:raise HTTPException(422,'Review the statements and confirm their accuracy before saving.')
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');current=listing(c,u,id,body.course_id,body.skill_id);owner=current['owner']
  if skill_details.is_group(owner['data']) and not body.skill_id:raise HTTPException(422,'Choose an individual skill or review existing skill assignments.')
  if body.revision!=current['revision']:raise HTTPException(409,'These details or their entry changed. Your draft is retained. Reopen the current details in another window to compare before saving again.')
  profile_answers.validate_links(c,u,[id])
  if len({s.id for s in body.statements})!=len(body.statements):raise HTTPException(422,'Each statement needs a unique identity.')
  context=body.skill_id or id+(':'+body.course_id if body.course_id else '')
  rows={r['id']:r for r in context_rows(c,u,id,body.course_id,body.skill_id)}
  keep=set()
  for rank,s in enumerate(body.statements):
   text=s.text.strip()
   if not text or __import__('re').search(profile_answers.PRIVATE,text,__import__('re').I):raise HTTPException(422,'Enter professional statements; keep private disclosures in private settings.')
   existing=rows.get(s.id)
   if not existing and c.execute('SELECT 1 FROM entities WHERE id=?',(s.id,)).fetchone():raise HTTPException(404,'Supporting Detail not found in this entry.')
   scope=structure.validate_scope(s.scope.model_dump() if s.scope else structure.scope_for_detail(existing['data'],id,owner['data']) if existing else structure.default_scope(owner['data']),owner['data']) if owner['data']['category']=='project' else None
   if existing:
    d=copy.deepcopy(existing['data']);old=copy.deepcopy(d)
    if d.get('backed_fields') and text!=d['text']:raise HTTPException(409,'This statement also supplies an overview field. Edit its original entry field first; the saved source history is preserved.')
    d.setdefault('history',[]).append({**old,'history':[]});d.update(text=text,status='confirmed',version=d['version']+1)
   else:
    rid=profile_answers.key(u,'statement:'+context+':'+s.id)
    if c.execute('SELECT 1 FROM entities WHERE id=?',(rid,)).fetchone():raise HTTPException(409,'This statement was already saved. Reload the saved list before editing it.')
    # A retried request is caught by the revision check, never duplicated.
    d={'version':1,'status':'confirmed','answer_kind':'experience','title':text[:150],'text':text,'experience_id':id,'experience_ids':[id],'course_refs':[{'education_id':id,'course_id':body.course_id}] if body.course_id else [],'category':owner['data']['category'],'record_context':{},'backed_fields':{},'scope':{},'sources':[{'builder':'manual_profile','reviewed_at':db.now(),'manual_review':True}],'history':[]}
    existing={'id':rid}
   if body.skill_id:d['skill_ref']={'experience_id':id,'skill_id':body.skill_id}
   d.setdefault('detail_order',{})[context]=rank
   if scope is not None:d.setdefault('project_scopes',{})[id]=scope
   profile_answers.write(c,u,d,existing['id']);keep.add(existing['id'])
  for rid,row in rows.items():
   if rid not in keep and row['data']['status']!='archived':
    d=copy.deepcopy(row['data']);d.setdefault('history',[]).append({**copy.deepcopy(d),'history':[]});d.update(status='archived',version=d['version']+1);write(c,u,'profile_answer',d,rid)
  profile_answers.touch_resumes(c,u,None,id)
  return listing(c,u,id,body.course_id,body.skill_id)

@router.get('/api/experience/{id}/structure')
def get_structure(id:str,user=Depends(auth.current)):
 with db.connect() as c:row=owned(c,user['id'],id)
 with db.connect() as c:row['details_revision']=listing(c,user['id'],id)['revision']
 row['timeline_enabled']=structure.timeline_enabled(row['data'])
 if row['data']['category']=='project':row['data'].update(project_stages=structure.stages(row['data']),project_statements=structure.statements(row['data']))
 return skill_details.decorate(row)

@router.put('/api/experience/{id}/structure')
def save_structure(id:str,body:StructureSave,user=Depends(auth.current)):
 from . import certifications
 certifications.validate_documents(user['id'],body.data.model_dump())
 from .resume_conversation import write
 from . import project_relations,combined_import
 u=user['id']
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');old=owned(c,u,id)
  if old['updated_at']!=body.expected_updated_at:raise HTTPException(409,'This entry changed. Your draft is retained; reopen the current entry to compare.')
  data=body.data.model_dump()
  removed_skills={v['id'] for v in skill_details.items(old['data'],id)}-{v['id'] for v in skill_details.items(data,id)}
  if removed_skills and body.details_revision!=listing(c,u,id)['revision']:raise HTTPException(409,'Skill details changed. Your edits are kept; reopen the current group to compare.')
  data=skill_details.prepare(c,u,id,data,old['data'],resolutions=body.removed_skill_scopes)
  removed={s['id'] for s in structure.stages(old['data'])}-{s['id'] for s in structure.stages(data)}
  if removed:
   if body.details_revision!=listing(c,u,id)['revision']:raise HTTPException(409,'Supporting Details changed while detaching. Your draft is retained; review the current details first.')
   for row in context_rows(c,u,id):
    if row['data'].get('status')=='archived':continue
    scope=structure.scope_for_detail(row['data'],id,old['data']);affected=set(scope.get('stage_ids',[]))&removed
    if not affected:continue
    if any(stage not in body.detached_stage_scopes for stage in affected):raise HTTPException(422,'Choose how to retain the detached stage’s statements.')
    choices=[structure.validate_scope(body.detached_stage_scopes[stage].model_dump(),data) for stage in affected]
    if any(choice!=choices[0] for choice in choices):raise HTTPException(422,'Choose the same reassignment for this shared statement’s detached stages.')
    d=copy.deepcopy(row['data']);d.setdefault('history',[]).append({**copy.deepcopy(d),'history':[]});d.setdefault('project_scopes',{})[id]=choices[0];d['version']+=1;write(c,u,'profile_answer',d,row['id'])
  project_relations.validate(c,u,data,old['data'])
  data=structure.prepare(c,u,{**data,'_record_id':id},old['data'],reviewed_scope_ids=body.reviewed_project_scope_ids)
  data['source_references']=combined_import.edited_references(old['data'],data)
  data['unavailable_source_ids']=old['data'].get('unavailable_source_ids',[])
  write(c,u,'experience',data,id);profile_answers.touch_resumes(c,u,None,id)
 return get_structure(id,user)

@router.put('/api/experience/{id}/skill-detail-assignments')
def assign_skill_details(id:str,body:SkillAssignments,user=Depends(auth.current)):
 from .resume_conversation import write
 u=user['id']
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');current=listing(c,u,id)
  if not skill_details.is_group(current['owner']['data']):raise HTTPException(422,'Choose a skill group.')
  if current['revision']!=body.revision:raise HTTPException(409,'Skill details changed. Your assignment choices are kept; reopen the current list to compare.')
  if len({v.id for v in body.statements})!=len(body.statements):raise HTTPException(422,'Choose each statement once.')
  rows={v['id']:v for v in context_rows(c,u,id)}
  for choice in body.statements:
   row=rows.get(choice.id)
   if not row:raise HTTPException(404,'Pending skill detail not found in this group.')
   if not choice.archived:skill_details.require(c,u,id,choice.skill_id)
   d=copy.deepcopy(row['data']);d.setdefault('history',[]).append({**copy.deepcopy(d),'history':[]});d['version']=d.get('version',0)+1
   if choice.archived:d['status']='archived'
   else:
    d['skill_ref']={'experience_id':id,'skill_id':choice.skill_id}
    d.setdefault('detail_order',{})[choice.skill_id]=100000
   write(c,u,'profile_answer',d,row['id'])
  profile_answers.touch_resumes(c,u,None,id)
  return listing(c,u,id)
