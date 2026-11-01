"""Owner-scoped durable optimization checkpoints, separate from business overlays.

A checkpoint is never a resume revision. Each write rechecks the active task and
existing owner/parent/run; missing records are never recreated by late workers.
"""
import asyncio,base64,copy,hashlib,json,time
from contextvars import ContextVar
from fastapi import HTTPException
from . import db,task_atomic,ai_settings

VERSION=1
_active=ContextVar('resume_optimization_run',default=None)
class RunStop(Exception):
 def __init__(self,status,message):self.status=status;self.message=message;super().__init__(message)
def current():return _active.get()
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def read(user,id):
 with task_atomic.outside():return db.get(user,id,'resume_run')
def latest(user,conversation):
 with task_atomic.outside():
  return next((r for r in db.list_entities(user,'resume_run') if r['data'].get('conversation_id')==conversation),None)
def _guard(c,user,conversation,task):
 if not c.execute("SELECT 1 FROM entities WHERE id=? AND user_id=? AND kind='resume_conversation'",(conversation,user)).fetchone():raise task_atomic.Stopped()
 if not c.execute("SELECT 1 FROM tasks WHERE id=? AND user_id=? AND status='running'",(task,user)).fetchone():raise task_atomic.Stopped()
def write(ctx,change):
 with task_atomic.outside(),db.connect() as c:
  c.execute('BEGIN IMMEDIATE');_guard(c,ctx['user'],ctx['conversation'],ctx['task'])
  row=c.execute("SELECT * FROM entities WHERE id=? AND user_id=? AND kind='resume_run'",(ctx['id'],ctx['user'])).fetchone()
  if not row:raise task_atomic.Stopped()
  value=json.loads(row['payload'])
  if value.get('task_id')!=ctx['task']:raise task_atomic.Stopped()
  change(value);value['updated_at']=db.now()
  c.execute('UPDATE entities SET payload=?,updated_at=? WHERE id=? AND user_id=?',(json.dumps(value),db.now(),ctx['id'],ctx['user']))
 return value

def fingerprint(user,conversation,body):
 from . import resume_conversation,resume_strategy,job_parser,personalization
 # Read committed professional evidence, never uncommitted Profile approvals.
 with task_atomic.outside():
  row=resume_conversation.require(user,conversation,'resume_conversation');data=row['data'];settings=db.settings(user)
  source=resume_conversation.source(user,data)
  info={'posting':job_parser.posting_hash(source['posting_snapshot']),'evidence':resume_strategy.signature(source),'personalization':personalization.request_version(user),'constraints':data.get('user_constraints',{}),'pending_feedback':data.get('pending_feedback'),'workspace_request':data.get('workspace_request'),'prior_revision':data.get('current_revision_id'),'models':settings.get('document_models'),'output_cap':settings.get('ai_max_output_tokens',0),'mode':body.mode,'decisions':[v.model_dump() if hasattr(v,'model_dump') else v for v in body.decisions],'template':body.template,'preparation':body.preparation.model_dump() if body.preparation else None,'refresh_linked_evidence':body.refresh_linked_evidence,'optimization_mode':body.optimization_mode or settings.get('resume_review_mode','standard'),'pipeline_version':VERSION}
  return digest(info),info,row

def check_fresh(ctx):
 actual,_,_=fingerprint(ctx['user'],ctx['conversation'],ctx['body'])
 if actual!=ctx['fingerprint']:raise RunStop('stale','Posting, evidence, instructions or model choices changed. Start a new optimization with the current sources; the last final resume is preserved.')

def projection(user,conversation):
 record=latest(user,conversation)
 if not record:return None
 d=record['data'];task=None
 with task_atomic.outside(),db.connect() as c:task=c.execute('SELECT status FROM tasks WHERE id=? AND user_id=?',(d.get('task_id',''),user)).fetchone()
 state=d.get('status','paused')
 final=db.get(user,d.get('final_revision_id',''),'resume_revision') if d.get('final_revision_id') else None
 if state=='ready' and final and final['data'].get('review_run_id')==record['id']:state='completed'
 elif state=='ready':state='interrupted'
 elif state=='running' and (not task or task['status'] not in ('queued','running')):
  state='unknown' if any(s.get('status') in ('dispatching','unknown') for s in d.get('stages',[])) else 'cancelled' if task and task['status']=='cancelled' else 'interrupted'
 stages=[{k:s.get(k) for k in ('name','schema','role','status','started_at','finished_at','duration_seconds','usage','model','reasoning_effort','speed','estimated_token_cost_usd','error')} for s in d.get('stages',[])]
 preview=d.get('preview') or {};raw=(preview.get('artifacts') or {}).get('pdf')
 return {'id':record['id'],'status':state,'continue_inputs':{k:copy.deepcopy(d.get('inputs',{}).get(k)) for k in ('mode','decisions','template','preparation','refresh_linked_evidence','optimization_mode') if k in d.get('inputs',{})},'optimization_mode':d.get('optimization_mode','standard'),'requests_used':d.get('requests_used',0),'request_limit':d.get('request_limit',4),'stages':stages,'message':d.get('message',''),'deadline_at':d.get('deadline_at'),'preview_id':record['id'] if raw else '', 'preview_version':hashlib.sha256(raw.encode()).hexdigest()[:20] if raw else '', 'preview_pages':preview.get('layout',{}).get('pages',0),'can_continue':state in ('paused','unknown','interrupted','cancelled') and not d.get('restored'),'unknown_usage_acknowledgement_required':state=='unknown','factual_ready':bool(final and d.get('approved_pdf_sha256')),'final_revision_id':final['id'] if final else ''}

def preview_snapshot(user,id):
 record=read(user,id)
 if not record or not record['data'].get('preview') or record['data'].get('restored'):raise HTTPException(404,'Draft checkpoint not found.')
 return record['data']['preview']
def save_preview(snapshot):
 ctx=current()
 if not ctx:return
 from . import resume_quality
 resume_quality.check_document(snapshot)
 if snapshot.get('layout',{}).get('pages')!=1 or not snapshot['layout'].get('validated'):return
 check_fresh(ctx)
 value=copy.deepcopy(snapshot);value['optimization']={'source_checked':False,'review_pending':True};value.pop('draft_id',None)
 write(ctx,lambda d:d.update(preview=value))

def mark_final(revision,snapshot):
 ctx=current()
 if not ctx:return
 if not snapshot.get('optimization',{}).get('source_checked'):raise RunStop('failed','The document has not passed its factual check.')
 check_fresh(ctx)
 sha=hashlib.sha256(base64.b64decode(snapshot['artifacts']['pdf'],validate=True)).hexdigest()
 write(ctx,lambda d:d.update(status='ready',message='Review complete. Review the exact PDF before saving.',final_revision_id=revision,approved_pdf_sha256=sha))

def assert_final(user,revision):
 run_id=revision['data'].get('review_run_id')
 if not run_id:return
 record=read(user,run_id);d=(record or {}).get('data',{});snapshot=revision['data']['snapshot']
 sha=hashlib.sha256(base64.b64decode(snapshot['artifacts']['pdf'],validate=True)).hexdigest()
 if d.get('restored') or d.get('status')!='ready' or d.get('final_revision_id')!=revision['id'] or d.get('conversation_id')!=revision['data']['conversation_id'] or d.get('approved_pdf_sha256')!=sha or not snapshot.get('optimization',{}).get('source_checked'):raise HTTPException(409,'This draft has not passed the final factual review. Continue its optimization or start a new run before saving.')

class Policy:
 def __init__(self,ctx,index):self.ctx=ctx;self.index=index;self.started=time.monotonic()
 def reserve(self,body):
  check_fresh(self.ctx)
  def dispatch(d):
   if d.get('deadline_at') and time.time()>=d['deadline_at']:raise RunStop('paused','Five-minute budget reached. Your response and draft are saved. Continue explicitly to start the next request.')
   if d['requests_used']>=d['request_limit']:raise RunStop('exhausted','This optimization reached its total request limit. No further paid request was sent; the draft and usage remain available.')
   d['requests_used']+=1;s=d['stages'][self.index];s.update(status='dispatching',started_at=db.now(),model=body['model'],reasoning_effort=body['reasoning']['effort'],speed=body.get('service_tier','default'))
  write(self.ctx,dispatch);return self.index
 def finish(self,reservation,result,status_code=None):
  duration=round(time.monotonic()-self.started,3)
  def received(d):
   s=d['stages'][self.index];s.update(status='response_received' if isinstance(result,dict) and (status_code or 200)<400 and result.get('status') in ('completed',None) and not result.get('error') else 'known_error' if isinstance(result,dict) or status_code is not None and status_code>=400 else 'unknown',finished_at=db.now(),duration_seconds=duration,raw_response=copy.deepcopy(result))
   if isinstance(result,dict):s.update(usage=result.get('usage') or {},estimated_token_cost_usd=ai_settings.usage_cost(result.get('model',s.get('model','')),result.get('usage') or {},service_tier=result.get('service_tier') or s.get('speed','default')))
  try:write(self.ctx,received)
  except task_atomic.Stopped:return  # Usage accounting still finishes; late checkpoints cannot return.

async def structured(schema,payload,mode,instructions,files,retry_allowed,max_output_tokens,execute):
 from . import ai,document_models
 ctx=current();check_fresh(ctx);index=ctx['cursor'];ctx['cursor']+=1
 hashed=digest({'schema':schema.model_json_schema(),'payload':payload,'mode':mode,'instructions':instructions,'files':files,'options':ai.options(mode),'max_output_tokens':max_output_tokens})
 data=read(ctx['user'],ctx['id'])['data'];stages=data.get('stages',[])
 if index<len(stages):
  stage=stages[index]
  if stage['input_hash']!=hashed:raise RunStop('stale','The saved stage no longer matches the current request. Start a new optimization.')
  if stage.get('status')=='validated':return schema.model_validate(stage['output']).model_dump(),copy.deepcopy(stage['metadata'])
  if stage.get('status')=='response_received':
   try:
    result=schema.model_validate_json(ai.output_text(stage['raw_response'])).model_dump()
    metadata=ai.metadata(stage['raw_response'],mode)
   except Exception as exc:raise RunStop('failed','The saved provider response did not meet the output contract. It was retained and was not sent again.') from exc
   write(ctx,lambda d:d['stages'][index].update(status='validated',output=result,metadata=metadata))
   return result,metadata
  if stage.get('status') in ('unknown','dispatching'):
   if not ctx['body'].acknowledge_unknown_usage:raise RunStop('unknown','The previous provider outcome is unknown and may have incurred usage. Acknowledge that before explicitly retrying this stage.')
   ctx['body']=ctx['body'].model_copy(update={'acknowledge_unknown_usage':False})
  elif stage.get('status')!='prepared':raise RunStop('failed','This stage returned an invalid or rejected response. No automatic paid retry was made. Start a new optimization if you want to try again.')
 else:
  role=document_models._role.get()
  write(ctx,lambda d:d['stages'].append({'name':('Writer draft' if index==0 else 'Independent review' if role=='reviewer' else 'Targeted writer correction'),'schema':schema.__name__,'role':role,'input_hash':hashed,'status':'prepared'}))
 policy=Policy(ctx,index);token=ai._request_policy.set(policy)
 try:
  deadline=read(ctx['user'],ctx['id'])['data'].get('deadline_at')
  remaining=deadline-time.time() if deadline else None
  if remaining is not None and remaining<=0:raise RunStop('paused','Five-minute budget reached. Continue explicitly when ready.')
  try:result,metadata=await asyncio.wait_for(execute(),remaining) if remaining is not None else await execute()
  except asyncio.TimeoutError:raise RunStop('unknown','Five-minute budget reached while waiting for the provider. Its outcome is unknown and may have incurred usage. Your earlier draft and checkpoints are saved; acknowledge possible usage before retrying.') from None
  write(ctx,lambda d:d['stages'][index].update(status='validated',output=copy.deepcopy(result),metadata=copy.deepcopy(metadata),usage=metadata.get('usage',{}),estimated_token_cost_usd=metadata.get('estimated_token_cost_usd')))
  return result,metadata
 except RunStop:raise
 except (asyncio.CancelledError,task_atomic.Stopped):raise
 except Exception as exc:
  saved=read(ctx['user'],ctx['id'])['data']['stages'][index]
  state='unknown' if saved['status'] in ('dispatching','unknown') else 'failed'
  if state=='failed':write(ctx,lambda d:d['stages'][index].update(status='known_error',error=str(exc)[:1000]))
  raise RunStop(state,str(exc)) from exc
 finally:ai._request_policy.reset(token)

async def execute(user,conversation,body,work):
 from . import ai,resume_conversation
 task=(ai._context.get() or {}).get('task_id')
 if not task:raise HTTPException(409,'Start optimization through its authenticated background build action.')
 signature,info,parent=fingerprint(user,conversation,body);record=read(user,body.continue_run_id) if body.continue_run_id else None
 if body.continue_run_id:
  if not record or record['data'].get('conversation_id')!=conversation:raise HTTPException(404,'Optimization run not found.')
  if record['data'].get('restored') or record['data'].get('fingerprint')!=signature:raise HTTPException(409,'The saved run no longer matches posting, evidence, instructions or models. Start a new optimization.')
  if record['data'].get('status')=='unknown' and not body.acknowledge_unknown_usage:raise HTTPException(409,'Acknowledge possible provider usage before retrying the unknown stage.')
 else:
  previous=projection(user,conversation)
  if previous and previous['status']!='completed' and not body.start_new_run:return resume_conversation.state(user,conversation)
  if previous and previous['status']=='unknown' and not body.acknowledge_unknown_usage:raise HTTPException(409,'Acknowledge the previous unknown provider usage before starting another optimization.')
  mode=info['optimization_mode'];value={'schema_version':VERSION,'conversation_id':conversation,'job_id':parent['data']['job_id'],'fingerprint':signature,'inputs':info,'task_id':task,'optimization_mode':mode,'status':'running','requests_used':0,'request_limit':4 if mode=='standard' else 8,'stages':[],'created_at':db.now()}
  with task_atomic.outside(),db.connect() as c:
   c.execute('BEGIN IMMEDIATE');_guard(c,user,conversation,task);identity=db.uid();stamp=db.now();c.execute('INSERT INTO entities VALUES(?,?,?,?,?,?)',(identity,user,'resume_run',json.dumps(value),stamp,stamp))
  record=read(user,identity)
 ctx={'id':record['id'],'user':user,'conversation':conversation,'task':task,'cursor':0,'fingerprint':signature,'body':body}
 # Explicit continuation grants a new attempt window, never a fresh call budget.
 with task_atomic.outside(),db.connect() as c:
  c.execute('BEGIN IMMEDIATE');_guard(c,user,conversation,task)
  row=c.execute("SELECT payload FROM entities WHERE id=? AND user_id=? AND kind='resume_run'",(ctx['id'],user)).fetchone()
  if not row:raise HTTPException(404,'Optimization run not found.')
  value=json.loads(row['payload']);value.update(task_id=task,status='running',deadline_at=time.time()+300 if value['optimization_mode']=='standard' else None,message='')
  c.execute('UPDATE entities SET payload=?,updated_at=? WHERE id=? AND user_id=?',(json.dumps(value),db.now(),ctx['id'],user))
 token=_active.set(ctx)
 try:return await work()
 except RunStop as exc:
  write(ctx,lambda d:d.update(status=exc.status,message=exc.message))
  # Keep durable response/preview checkpoints, discard unfinished business changes.
  with task_atomic.outside(),db.connect() as c:task_atomic.discard(c,task)
  with task_atomic.outside():return resume_conversation.state(user,conversation)
 finally:_active.reset(token)


def restore_value(value):
 """Validate all imported history before writes; strip every active authority."""
 import math
 def text(v,limit):
  if not isinstance(v,str) or len(v)>limit:raise ValueError('Invalid optimization history text')
  return v
 def integer(v,limit):
  if type(v) is not int or not 0<=v<=limit:raise ValueError('Invalid optimization history count')
  return v
 def metric(v):
  if v is not None and (type(v) not in (float,int) or not math.isfinite(v) or not 0<=v<=10**9):raise ValueError('Invalid optimization history metric')
  return v
 conversation=text(value['conversation_id'],100);job=text(value['job_id'],100)
 mode=value.get('optimization_mode','standard')
 if mode not in ('standard','thorough'):raise ValueError('Invalid optimization mode')
 used=integer(value.get('requests_used',0),8);limit=integer(value.get('request_limit',4),8)
 if limit not in (4,8) or used>limit:raise ValueError('Invalid optimization request budget')
 stages=value.get('stages',[])
 if not isinstance(stages,list) or len(stages)>8 or any(not isinstance(stage,dict) for stage in stages):raise ValueError('Invalid optimization stages')
 history=[]
 for stage in stages:
  row={k:text(stage.get(k,''),limit) for k,limit in [('name',120),('role',40),('status',40),('model',150),('reasoning_effort',40),('speed',40)]}
  row['duration_seconds']=metric(stage.get('duration_seconds'));row['estimated_token_cost_usd']=metric(stage.get('estimated_token_cost_usd'))
  usage=stage.get('usage') or {}
  if not isinstance(usage,dict):raise ValueError('Invalid optimization usage')
  row['usage']={}
  for k in ('input_tokens','output_tokens','total_tokens','cached_input_tokens','reasoning_tokens'):
   if k in usage:row['usage'][k]=integer(usage[k],10**12)
  for detail,key in [('input_tokens_details','cached_tokens'),('output_tokens_details','reasoning_tokens')]:
   if detail in usage:
    if not isinstance(usage[detail],dict):raise ValueError('Invalid optimization usage details')
    if key in usage[detail]:row['usage'][detail]={key:integer(usage[detail][key],10**12)}
  history.append(row)
 return {'schema_version':VERSION,'conversation_id':conversation,'job_id':job,'optimization_mode':mode,'status':'imported','restored':True,'message':'Imported optimization history. Start a fresh optimization to use current verified sources.','requests_used':used,'request_limit':limit,'stages':history}
