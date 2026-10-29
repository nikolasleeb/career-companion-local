"""Account-owned per-version checklists. Reads never migrate or mutate legacy plans."""
import copy,hashlib,json
from fastapi import APIRouter,Depends,HTTPException
from pydantic import Field
from . import db,auth
from .models import StrictModel
KIND='coach_plan_progress'
router=APIRouter(prefix='/api/career-coach/plans')
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True).encode()).hexdigest()[:24]
def identity(user,plan):return hashlib.sha256((user+':plan-progress:'+plan).encode()).hexdigest()[:32]
def owned(user,id,kind):
 r=db.get(user,id,kind)
 if not r:raise HTTPException(404,'Saved plan not found.')
 return r
def step_ids(plan):
 result={};parents={}
 for action in plan['data']['actions']:
  parent=(action['kind'],' '.join(action['title'].split()));occurrence=parents.get(parent,0);parents[parent]=occurrence+1
  seen={};ids=[]
  for text in action['steps']:
   normalized=' '.join(text.split());n=seen.get(normalized,0);seen[normalized]=n+1
   ids.append('task:'+digest([action['kind'],' '.join(action['title'].split()),normalized,n,occurrence]))
  result[action['id']]=ids
 return result

def snapshot(user,plan):
 chat=owned(user,plan['data']['chat_id'],'coach_chat');ids=step_ids(plan);row=db.get(user,identity(user,plan['id']),KIND)
 if not row:row=next((r for r in db.list_entities(user,KIND) if r['data'].get('plan_id')==plan['id']),None)
 if row:value=copy.deepcopy(row['data'])
 else:
  steps={};started={}
  for action in plan['data']['actions']:
   old=chat['data'].get('progress',{}).get(action['id'],{})
   started[action['id']]=old.get('state')=='in_progress'
   for sid in ids[action['id']]:steps[sid]={'completed':old.get('state')=='completed','completed_at':old.get('updated_at','') if old.get('state')=='completed' else ''}
  value={'plan_id':plan['id'],'chat_id':chat['id'],'revision':0,'steps':steps,'started':started}
 milestones={};completed=0;total=0
 for action in plan['data']['actions']:
  keys=ids[action['id']];done=sum(bool(value['steps'].get(s,{}).get('completed')) for s in keys);completed+=done;total+=len(keys)
  milestones[action['id']]={'completed':done,'total':len(keys),'state':'completed' if done==len(keys) else 'in_progress' if done or value.get('started',{}).get(action['id']) else 'planned','completed_at':max((value['steps'].get(s,{}).get('completed_at','') for s in keys),default='') if done==len(keys) else ''}
 return {**value,'step_ids':ids,'milestones':milestones,'completed':completed,'total':total,'percent':round(100*completed/total) if total else 0}

def source_snapshot(user,plan):
 # Legacy readable plan projections may predate linked conversations/checklists.
 if not db.get(user,plan['data'].get('chat_id',''),'coach_chat'):return None
 return snapshot(user,plan)

def initialize(c,user,plan,previous=None):
 from .resume_conversation import write
 # A saved new version inherits only exact, stable step identities.
 old=snapshot(user,previous) if previous else None
 value=snapshot(user,plan);value={k:value[k] for k in ('plan_id','chat_id','revision','steps','started')}
 if old:
  value['steps']={sid:{'completed':False,'completed_at':''} for sid in value['steps']}
  value['started']={}
  for sid in value['steps']:
   if sid in old['steps']:value['steps'][sid]=copy.deepcopy(old['steps'][sid])
 write(c,user,KIND,value,identity(user,plan['id']))

class Change(StrictModel):
 expected_revision:int=Field(ge=0)
 milestone_id:str=Field(min_length=1,max_length=100)
 step_id:str=Field(default='',max_length=100)
 completed:bool
@router.get('/{id}/progress')
def read(id:str,user=Depends(auth.current)):return snapshot(user['id'],owned(user['id'],id,'coach_plan'))
@router.patch('/{id}/progress')
def update(id:str,body:Change,user=Depends(auth.current)):
 from .resume_conversation import write
 uid=user['id'];plan=owned(uid,id,'coach_plan')
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');value=snapshot(uid,plan)
  if value['revision']!=body.expected_revision:raise HTTPException(409,'Plan progress changed in another window. Reload its saved progress; your checklist choice is retained.')
  keys=value['step_ids'].get(body.milestone_id)
  if keys is None or body.step_id and body.step_id not in keys:raise HTTPException(404,'Plan step not found.')
  for sid in [body.step_id] if body.step_id else keys:value['steps'][sid]={'completed':body.completed,'completed_at':db.now() if body.completed else ''}
  value.setdefault('started',{})[body.milestone_id]=False
  value={k:value[k] for k in ('plan_id','chat_id','steps','started','revision')};value['revision']+=1
  # Imported identities may differ; update the existing record rather than duplicate it.
  row=next((r for r in db.list_entities(uid,KIND) if r['data'].get('plan_id')==id),None)
  write(c,uid,KIND,value,row['id'] if row else identity(uid,id))
 return snapshot(uid,plan)

class Reference(StrictModel):
 plan_id:str=Field(min_length=1,max_length=64)
 milestone_id:str=Field(default='',max_length=100)
 step_id:str=Field(default='',max_length=100)
def context(user,ref,chat_id):
 if not ref:
  chat=db.get(user,chat_id,'coach_chat')
  if not chat or not chat['data'].get('plan_id'):return None
  ref=Reference(plan_id=chat['data']['plan_id'])
 plan=owned(user,ref.plan_id,'coach_plan')
 if plan['data']['chat_id']!=chat_id:raise HTTPException(404,'This plan belongs to another conversation.')
 from . import coach_access
 provenance=copy.deepcopy(plan['data'])
 # Goals explicitly selected for this plan are conversation context, not automatic sharing.
 provenance.pop('planning_inputs_snapshot',None)
 if not coach_access.source_allowed(user,provenance):raise HTTPException(409,'Sharing or source permissions for this saved plan changed. Review its context before sending; no AI request was started.')
 actions=plan['data']['actions'];ids=step_ids(plan)
 if ref.milestone_id:
  actions=[a for a in actions if a['id']==ref.milestone_id]
  if not actions:raise HTTPException(404,'Plan milestone not found.')
 if ref.step_id and (not ref.milestone_id or ref.step_id not in ids[ref.milestone_id]):raise HTTPException(404,'Plan step not found.')
 return {'plan_id':plan['id'],'version':plan['data']['version'],'direction':plan['data']['direction'],'actions':copy.deepcopy(actions),'selected_milestone_id':ref.milestone_id,'selected_step_id':ref.step_id,'progress':snapshot(user,plan)}

def validate_backup(record,kinds,by_id):
 if record['kind']!=KIND:return
 d=record['data'];plan=by_id.get(d.get('plan_id'))
 if not plan or plan['kind']!='coach_plan' or kinds.get(d.get('chat_id'))!='coach_chat' or plan['data']['chat_id']!=d['chat_id']:raise ValueError('Invalid plan progress ownership')
 if type(d.get('revision')) is not int or d['revision']<0 or not isinstance(d.get('steps'),dict) or not isinstance(d.get('started',{}),dict):raise ValueError('Invalid checklist')
 ids=step_ids(plan);allowed={s for v in ids.values() for s in v}
 if set(d['steps'])-allowed or set(d.get('started',{}))-set(ids) or any(type(v) is not bool for v in d.get('started',{}).values()):raise ValueError('Invalid checklist references')
 from datetime import datetime
 for value in d['steps'].values():
  if type(value.get('completed')) is not bool:raise ValueError('Invalid completion')
  if value.get('completed_at'):datetime.fromisoformat(value['completed_at'])


def apply_legacy(c,user,chat,action_id,state):
 from .resume_conversation import write
 candidates=[p for p in db.list_entities(user,'coach_plan') if p['data']['chat_id']==chat['id'] and any(a['id']==action_id for a in p['data']['actions'])]
 if not candidates:return
 plan=next((p for p in candidates if p['id']==chat['data'].get('plan_id')),candidates[0]);value=snapshot(user,plan)
 for sid in value['step_ids'][action_id]:value['steps'][sid]={'completed':state=='completed','completed_at':db.now() if state=='completed' else ''}
 value['started'][action_id]=state=='in_progress';value['revision']+=1
 row=next((r for r in db.list_entities(user,KIND) if r['data'].get('plan_id')==plan['id']),None)
 write(c,user,KIND,{k:value[k] for k in ('plan_id','chat_id','revision','steps','started')},row['id'] if row else identity(user,plan['id']))
