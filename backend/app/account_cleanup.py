"""Previewed account-owned cleanup. Business deletion is transactional; file unlink is durable."""
import asyncio,hashlib,json,re,time
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException
from pydantic import Field,field_validator
from . import auth,db,config
from .models import StrictModel
router=APIRouter(prefix='/api/account/cleanup')
mutations=defaultdict(int)
SEARCH_HISTORY=('cc_job_alert_runs','cc_job_deliveries','cc_job_seen','cc_job_baselines')
def search_counts(c,user):return {table:c.execute('SELECT count(*) FROM '+table+' WHERE user_id=?',(user,)).fetchone()[0] for table in SEARCH_HISTORY}
PERSONAL=('name','contact','contact_reviewed','headline','use_professional_headline','email','phone','city','state','country','county','website','linkedin','github')
CATEGORIES={'personal':'Personal details',**{'profile:'+k:v for k,v in [('education','Education'),('employment','Employment'),('project','Projects'),('volunteering','Volunteering'),('skills','Skills'),('coursework','Coursework'),('certifications','Certifications')]},'supporting':'Supporting Details','goals':'Career Goals','work_assessments':'Work Styles assessments & reports','work_summary':'Work Styles summary & AI guidance','private':'Private application answers','uploads':'Uploads & project materials','documents':'Generated resumes & cover letters','document_conversations':'Resume & letter conversations','careers':'Saved Career Explorer careers','plans':'Career Plans conversations & plans','coach':'Career Coach conversations','interviews':'Interview practice & transcripts','skills':'Saved skills plans','jobs':'Job Search history & saved postings','applications':'Applications'}
GROUPS={'supporting':{'profile_answer','answer_draft','story_prompts'},'goals':{'career_goals'},'work_assessments':{'work_style','assessment','assessment_progress'},'work_summary':{'work_preferences'},'uploads':{'project_source','project_snapshot','project_analysis'},'documents':{'resume','resume_draft','resume_revision','cover_letter','cover_revision'},'document_conversations':{'resume_conversation','cover_workspace'},'careers':{'saved_career','career_explorer_saved'},'plans':{'coach_chat','coach_message','coach_plan','coach_research'},'coach':{'assistant_chat','assistant_message','assistant_research'},'interviews':{'interview','interview_session','interview_question','interview_attempt','interview_research','interview_message','interview_voice','interview_material'},'skills':{'prep'},'jobs':{'job','job_snapshot','search','job_search_run','job_ai_discovery','ai_job_match','personalized_search','personalized_match','analysis','ai_search'},'applications':{'application'}}
def init(c):
 c.execute('CREATE TABLE IF NOT EXISTS cc_cleanup_state(user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,revision INTEGER NOT NULL DEFAULT 0)')
 c.execute('CREATE TABLE IF NOT EXISTS cc_cleanup_operations(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,created_at REAL NOT NULL,expires_at REAL NOT NULL,fingerprint TEXT NOT NULL,request TEXT NOT NULL,manifest TEXT NOT NULL,state TEXT NOT NULL,receipt TEXT NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS cc_cleanup_files(operation_id TEXT NOT NULL REFERENCES cc_cleanup_operations(id) ON DELETE CASCADE,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,filename TEXT NOT NULL,state TEXT NOT NULL,error TEXT NOT NULL,PRIMARY KEY(operation_id,filename))')
def revision(user,c=None):
 if c is not None:
  row=c.execute('SELECT revision FROM cc_cleanup_state WHERE user_id=?',(user,)).fetchone();return row[0] if row else 0
 with db.connect() as conn:return revision(user,conn)
def blocked(c,user):
 if mutations[user]>1:return ['Another account change is in progress. Wait for it to finish.']
 if c.execute("SELECT 1 FROM tasks WHERE user_id=? AND status IN ('queued','running','cancelling')",(user,)).fetchone():return ['Stop or finish your running tasks before changing saved information.']
 if c.execute("SELECT 1 FROM cc_job_alert_runs WHERE user_id=? AND state='running' AND lease_until>?",(user,time.time())).fetchone():return ['Wait for the active daily job check to finish.']
 if c.execute("SELECT 1 FROM cc_ai_requests WHERE user_id=? AND state IN ('dispatching','cancelling')",(user,)).fetchone():return ['Stop or finish application-assistant AI help first.']
 if c.execute("SELECT 1 FROM cc_runs WHERE user_id=? AND json_extract(payload,'$.state') NOT IN ('stopped','failed','ready_for_final_review','paused') AND json_extract(payload,'$.expires')>?",(user,time.time())).fetchone():return ['Stop the active application assistant run first.']
 return []
class Preview(StrictModel):
 action:Literal['delete','archive','restore']='delete'
 categories:list[str]=Field(default_factory=list,max_length=30)
 application_scope:Literal['current','archived','all']='current'
 start:str=''
 end:str=''
 @field_validator('start','end')
 @classmethod
 def valid_date(cls,v):
  if v:date.fromisoformat(v)
  return v
class Apply(StrictModel):
 preview_id:str=Field(min_length=1,max_length=64)
 confirmation:str=Field(default='',max_length=100)
 password:str=Field(default='',max_length=200)

def category(r):
 k=r['kind'];d=r['data']
 if k=='career_goals' and not (d.get('items') or d.get('text') or d.get('note') or d.get('use_for_ai')):return ''
 if k=='work_preferences' and not (d.get('summary') or d.get('preferences') or d.get('use_for_ai') or d.get('assessment_id')):return ''
 if k=='experience':return 'profile:certifications' if d.get('certification_items') else 'profile:'+d.get('category','project')
 if k=='document':return 'uploads'
 for key,kinds in GROUPS.items():
  if k in kinds:return key
 return ''
def records(c,user):return [db.decode(r) for r in c.execute('SELECT * FROM entities WHERE user_id=? ORDER BY id',(user,))]
def private_count(c,user):return c.execute('SELECT count(*) FROM cc_private_profile WHERE user_id=?',(user,)).fetchone()[0]+c.execute('SELECT count(*) FROM cc_vault WHERE user_id=?',(user,)).fetchone()[0]
def fingerprint(c,user):
 parts=[revision(user,c)]+[tuple(r) for r in c.execute("SELECT id,kind,payload,updated_at FROM entities WHERE user_id=? AND kind!='usage_event' ORDER BY id",(user,))]
 parts += [tuple(r) for r in c.execute('SELECT settings FROM users WHERE id=?',(user,))]
 for table,order in [('cc_private_profile','section'),('cc_vault','id'),('cc_preferences','user_id')]:parts += [tuple(r) for r in c.execute('SELECT * FROM '+table+' WHERE user_id=? ORDER BY '+order,(user,))]
 for table in SEARCH_HISTORY:parts += [tuple(r) for r in c.execute('SELECT * FROM '+table+' WHERE user_id=? ORDER BY 1,2',(user,))]
 parts += [tuple(r) for r in c.execute('SELECT id,status,updated_at FROM tasks WHERE user_id=? ORDER BY id',(user,))]
 return hashlib.sha256(repr(parts).encode()).hexdigest()
def in_app_range(r,body):
 d=r['data'];when=(d.get('applied_date') or r['created_at'][:10])[:10]
 return (body.application_scope=='all' or bool(d.get('archived'))==(body.application_scope=='archived')) and (not body.start or when>=body.start) and (not body.end or when<=body.end)
def refs(value,ids):
 if isinstance(value,str):return value in ids
 if isinstance(value,list):return any(refs(v,ids) for v in value)
 if isinstance(value,dict):return any(refs(v,ids) for v in value.values())
 return False

def manifest(c,user,body):
 if not body.categories:raise HTTPException(422,'Choose at least one saved-information category.')
 if set(body.categories)-set(CATEGORIES):raise HTTPException(422,'Choose saved-information categories from the list.')
 if body.action!='delete' and set(body.categories)!={'applications'}:raise HTTPException(422,'Archiving and restoration apply only to applications.')
 if body.start and body.end and body.start>body.end:raise HTTPException(422,'Choose an end date on or after the start date.')
 rows=records(c,user);chosen=set(body.categories);targets={r['id'] for r in rows if category(r) in chosen and (r['kind']!='application' or in_app_range(r,body))};files=set();preserved=set()
 if body.action=='delete':
  apps={r['id'] for r in rows if r['id'] in targets and r['kind']=='application'}
  # Offers are inseparable from their application. Dedicated attachments are
  # removed only when no retained application or generated version shares them.
  for r in rows:
   d=r['data']
   if r['kind']=='application_offer' and d.get('application_id') in apps:targets.add(r['id'])
   if r['kind']=='document' and d.get('purpose')=='application' and d.get('application_id') in apps:
    related={r['id'],d.get('resume_id','')}-{''};shared=any(v['id'] not in targets and v['id'] not in related and refs(v['data'],related) for v in rows)
    if shared:targets.discard(r['id']);preserved.add(r['id'])
    else:
     targets.add(r['id'])
     if d.get('resume_id'):targets.add(d['resume_id'])
  # Keep shared source files/versions referenced by unselected applications.
  for r in rows:
   if r['id'] in targets and r['kind'] in ('document','resume','cover_letter','job','job_snapshot','analysis'):
    if any(v['kind']=='application' and v['id'] not in targets and refs(v['data'],{r['id']}) for v in rows):targets.discard(r['id']);preserved.add(r['id'])
  # Remove dependent conversation images only with their selected family.
  for r in rows:
   if r['kind']=='chat_image' and r['data'].get('conversation_id') in targets:targets.add(r['id'])
  files={r['id'] for r in rows if r['id'] in targets and r['kind']=='document'}
 private=private_count(c,user) if 'private' in chosen else 0
 settings=json.loads(c.execute('SELECT settings FROM users WHERE id=?',(user,)).fetchone()[0]);personal=sum(bool(settings.get(k)) for k in PERSONAL) if 'personal' in chosen else 0
 private_records=([{'id':r['section'],'kind':'private_section','title':r['section'].replace('_',' ').title()} for r in c.execute('SELECT section FROM cc_private_profile WHERE user_id=?',(user,))]+[{'id':r['id'],'kind':'private_answer','title':'Saved private application answer'} for r in c.execute('SELECT id FROM cc_vault WHERE user_id=?',(user,))]) if 'private' in chosen else []
 selected=[{'id':r['id'],'kind':r['kind'],'title':str(r['data'].get('title') or r['data'].get('filename') or r['data'].get('company') or r['kind'].replace('_',' '))[:200]} for r in rows if r['id'] in targets]
 return {'search_history_counts':search_counts(c,user) if 'jobs' in chosen else {},'record_ids':sorted(targets),'records':selected,'private_records':private_records,'files':sorted(files),'preserved_shared_records':sorted(preserved),'preserved_records':[{'id':r['id'],'kind':r['kind'],'title':str(r['data'].get('title') or r['data'].get('filename') or r['kind'])[:200]} for r in rows if r['id'] in preserved],'private_sections':private,'personal_fields':personal,'personal_field_names':[k for k in PERSONAL if settings.get(k)] if 'personal' in chosen else [],'blockers':blocked(c,user),'retained_copies_notice':'Unselected uploads, saved documents and conversations may still contain historical copies. Downloaded and operator-held backups are outside this cleanup.','preserved_documents_notice':'Independently saved resumes and cover letters remain unless their own category is selected.','backup_notice':'Ordinary account backups exclude API credentials and the private-answer vault.'}
@router.get('')
def inventory(user=Depends(auth.current)):
 with db.connect() as c:
  rows=records(c,user['id']);settings=json.loads(c.execute('SELECT settings FROM users WHERE id=?',(user['id'],)).fetchone()[0]);counts={k:sum(category(r)==k for r in rows) for k in CATEGORIES};counts['personal']=sum(bool(settings.get(k)) for k in PERSONAL);counts['private']=private_count(c,user['id']);counts['jobs']+=sum(search_counts(c,user['id']).values())
  last=c.execute("SELECT id FROM cc_cleanup_operations WHERE user_id=? AND state='applied' ORDER BY created_at DESC LIMIT 1",(user['id'],)).fetchone()
  return {'categories':[{'id':k,'label':v,'count':counts[k]} for k,v in CATEGORIES.items()],'cleanup_revision':revision(user['id'],c),'last_operation_id':last[0] if last else None,'blockers':blocked(c,user['id'])}
@router.post('/preview')
def preview(body:Preview,user=Depends(auth.current)):
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');m=manifest(c,user['id'],body);identity=db.uid();now=time.time();c.execute('INSERT INTO cc_cleanup_operations VALUES(?,?,?,?,?,?,?,?,?)',(identity,user['id'],now,now+600,fingerprint(c,user['id']),body.model_dump_json(),json.dumps(m),'preview','{}'))
  return {'preview_id':identity,'expires_at':now+600,'action':body.action,**m}
def write(c,user,row,data):c.execute('UPDATE entities SET payload=?,updated_at=? WHERE id=? AND user_id=?',(json.dumps(data),db.now(),row['id'],user))
@router.post('/apply')
def apply(body:Apply,user=Depends(auth.current)):
 u=user['id']
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');op=c.execute('SELECT * FROM cc_cleanup_operations WHERE id=? AND user_id=?',(body.preview_id,u)).fetchone()
  if not op:raise HTTPException(404,'Cleanup preview not found.')
  if op['state']=='applied':return json.loads(op['receipt'])
  if op['expires_at']<time.time():raise HTTPException(409,'This preview expired. Preview the current information again.')
  if blocked(c,u):raise HTTPException(409,blocked(c,u)[0])
  if fingerprint(c,u)!=op['fingerprint']:raise HTTPException(409,'Saved information changed. Review a fresh preview before applying cleanup.')
  request=Preview.model_validate_json(op['request']);m=json.loads(op['manifest']);ids=set(m['record_ids']);chosen=set(request.categories);rows=records(c,u)
  if body.confirmation!=('DELETE' if request.action=='delete' else 'CONFIRM'):raise HTTPException(422,'Enter the displayed confirmation to continue.')
  if not (m['record_ids'] or m['personal_fields'] or m['private_sections'] or any(m['search_history_counts'].values())):raise HTTPException(422,'No saved information matches this selection. Nothing changed.')
  if request.action=='delete':
   auth.throttle('cleanup:'+u);password=c.execute('SELECT password FROM users WHERE id=?',(u,)).fetchone()[0]
   if not auth.verify(password,body.password):raise HTTPException(403,'Your account password did not match. No information was removed.')
   settings=json.loads(c.execute('SELECT settings FROM users WHERE id=?',(u,)).fetchone()[0])
   if 'personal' in chosen:
    for k in PERSONAL:settings.pop(k,None)
   if 'private' in chosen:
    for table in ('cc_private_profile','cc_vault','cc_preferences'):c.execute('DELETE FROM '+table+' WHERE user_id=?',(u,))
    for k in ('us_citizen','authorized_us','sponsorship_now','sponsorship_future','citizenship_countries'):settings.pop(k,None)
   if 'applications' in chosen:settings['applications_migrated']=True
   c.execute('UPDATE users SET settings=? WHERE id=?',(json.dumps(settings),u))
   deleted_experience={r['id'] for r in rows if r['id'] in ids and r['kind']=='experience'}
   for r in rows:
    d=r['data']
    if r['id'] in ids:
     if r['kind']=='career_goals':write(c,u,r,{'schema_version':3,'revision':d.get('revision',0)+1,'items':[],'text':'','use_for_ai':False});ids.remove(r['id'])
     elif r['kind']=='work_preferences':write(c,u,r,{'revision':d.get('revision',0)+1,'preferences':[],'summary':'','reviewed':False,'use_for_ai':False,'assessment_id':'','coach_report_access':False});ids.remove(r['id'])
    elif r['kind']=='work_preferences' and 'work_assessments' in chosen:
     d.update(use_for_ai=False,reviewed=False,coach_report_access=False,assessment_id='',revision=d.get('revision',0)+1);write(c,u,r,d)
    elif r['kind'] in ('resume_conversation','cover_workspace') and ('supporting' in chosen or deleted_experience):
     for field in ('proposals','context_proposals'):
      for proposal in d.get(field,[]):
       if 'supporting' in chosen or refs(proposal,deleted_experience):proposal['cleanup_unavailable']=True
     for field in ('questions','asked_questions','context_questions'):
      for question in d.get(field,[]):
       if 'supporting' in chosen or refs(question,deleted_experience):question['cleanup_answer_version']=question.get('answer_version',1)
     write(c,u,r,d)
    elif r['kind']=='profile_answer' and refs(d,deleted_experience):
     d['unavailable_source_ids']=sorted(deleted_experience);d['status']='archived';d['backed_fields']={};d['experience_id']='';d['experience_ids']=[];write(c,u,r,d)
    elif r['kind']=='application' and r['id'] not in ids:
     changed=refs(d,ids)
     d['attachments']=[a for a in d.get('attachments',[]) if a.get('record_id') not in ids];d['resume_ids']=[v for v in d.get('resume_ids',[]) if v not in ids]
     if d.get('submitted_resume_id') in ids:d['submitted_resume_id']=''
     write(c,u,r,d) if changed else None
   for identity in ids:
    c.execute('DELETE FROM entities WHERE id=? AND user_id=?',(identity,u));c.execute('DELETE FROM evidence_fts WHERE id=? AND user_id=?',(identity,u))
   for r in rows:
    if r['id'] not in ids and r['kind'] not in ('usage_event','onboarding','work_preferences','career_goals') and refs(r['data'],ids):
     current=c.execute('SELECT payload FROM entities WHERE id=? AND user_id=?',(r['id'],u)).fetchone()
     if current:
      d=json.loads(current[0]);d['unavailable_source_ids']=sorted(set(d.get('unavailable_source_ids',[]))|{identity for identity in ids if refs(d,{identity})});write(c,u,r,d)
   c.execute('DELETE FROM cc_run_answers WHERE user_id=?',(u,))
   c.execute('DELETE FROM cc_task_stage WHERE user_id=?',(u,))
   c.execute("UPDATE cc_ai_requests SET payload=? WHERE user_id=?",(json.dumps({'error':'Saved context was cleared. This historical result is unavailable.'}),u))
   # Paused runs must not restore removed context or one-time private answers.
   for run in c.execute('SELECT id,payload FROM cc_runs WHERE user_id=?',(u,)).fetchall():
    d=json.loads(run['payload']);d.update(state='stopped',expires=0,cleanup_revision=revision(u,c)+1);d.pop('unresolved',None);c.execute('UPDATE cc_runs SET payload=?,updated_at=? WHERE id=? AND user_id=?',(json.dumps(d),db.now(),run['id'],u))
   # Retrieval caches and completed recovery payloads can hold historical copies
   # or regenerate a deleted result. Drop derived indexes; keep usage ledger.
   c.execute('DELETE FROM cc_coach_knowledge WHERE scope=?',(u,))
   c.execute("UPDATE tasks SET result=?,error='' WHERE user_id=? AND status NOT IN ('queued','running','cancelling')",(json.dumps({'deleted_by_cleanup':body.preview_id}),u))
   for table,col in [('cc_search_rows','job_id'),('cc_job_lifecycle','job_id')]:
    for identity in ids:c.execute('DELETE FROM '+table+' WHERE user_id=? AND '+col+'=?',(u,identity))
   for identity in ids:c.execute('DELETE FROM cc_search_rows WHERE user_id=? AND search_id=?',(u,identity))
   if 'jobs' in chosen:
    c.execute('DELETE FROM cc_job_observations WHERE scope=?',(u,))
    for table in SEARCH_HISTORY:c.execute('DELETE FROM '+table+' WHERE user_id=?',(u,))
   for filename in m['files']:c.execute('INSERT OR IGNORE INTO cc_cleanup_files VALUES(?,?,?,?,?)',(body.preview_id,u,filename,'pending',''))
   # A previously reviewed empty-section acknowledgement is not a new review.
   for r in rows:
    if r['kind']=='onboarding':
     d=r['data'];d['empty_sections']=[k for k in d.get('empty_sections',[]) if 'profile:'+k not in chosen];d['version']=d.get('version',1)+1;write(c,u,r,d)
  else:
   for r in rows:
    if r['id'] in ids:
     d=r['data'];d['archived']=request.action=='archive';write(c,u,r,d)
  rev=revision(u,c)+1;c.execute('INSERT INTO cc_cleanup_state VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET revision=excluded.revision',(u,rev))
  receipt={'operation_id':body.preview_id,'action':request.action,'records_affected':len(m['record_ids']),'private_sections':m['private_sections'],'personal_fields':m['personal_fields'],'cleanup_revision':rev,'files_pending':len(m['files']) if request.action=='delete' else 0,'preserved_shared_records':len(m['preserved_shared_records'])}
  c.execute("UPDATE cc_cleanup_operations SET state='applied',receipt=? WHERE id=? AND user_id=?",(json.dumps(receipt),body.preview_id,u))
 return receipt
@router.get('/{identity}')
def status(identity:str,user=Depends(auth.current)):
 with db.connect() as c:
  op=c.execute("SELECT receipt,state FROM cc_cleanup_operations WHERE id=? AND user_id=? AND state='applied'",(identity,user['id'])).fetchone()
  if not op:raise HTTPException(404,'Cleanup result not found.')
  rows=[dict(r) for r in c.execute('SELECT filename,state,error FROM cc_cleanup_files WHERE operation_id=? AND user_id=?',(identity,user['id']))]
  return {**json.loads(op['receipt']),'file_removal':rows,'files_pending':sum(r['state']!='removed' for r in rows)}
def remove_files():
 with db.connect() as c:rows=[dict(r) for r in c.execute("SELECT * FROM cc_cleanup_files WHERE state!='removed'")]
 for row in rows:
  try:
   if not re.fullmatch(r'[a-f0-9]{32}',row['filename']):raise ValueError()
   folder=(config.DATA_DIR/'uploads'/row['user_id']).resolve();target=folder/row['filename']
   if target.is_symlink():raise ValueError()
   target.unlink(missing_ok=True);state,error='removed',''
  except Exception:state,error='pending','File removal is pending. The server will retry; its saved record is already unavailable.'
  with db.connect() as c:c.execute('UPDATE cc_cleanup_files SET state=?,error=? WHERE operation_id=? AND filename=? AND user_id=?',(state,error,row['operation_id'],row['filename'],row['user_id']))
async def maintain():
 while True:
  try:await asyncio.to_thread(remove_files)
  except asyncio.CancelledError:raise
  except Exception:pass # Preserve queued work and retry after temporary database/storage failures.
  await asyncio.sleep(5)
