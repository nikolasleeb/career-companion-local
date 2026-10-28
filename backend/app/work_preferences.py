"""Reviewed work conditions, separate from assessment answers and qualifications."""
import hashlib,json
from fastapi import APIRouter,Depends,HTTPException
from pydantic import Field,model_validator
from . import auth,db,role_catalog,credentials,onboarding
from .models import StrictModel
router=APIRouter(prefix='/api/profile/work-preferences')
class Change(StrictModel):
 expected_revision:int=Field(ge=0)
 preferences:list[str]=Field(default_factory=list,max_length=12)
 use_for_ai:bool=False
 reviewed:bool=False
 assessment_id:str=Field(default='',max_length=64)
 summary:str|None=Field(default=None,max_length=6000)
 generation_task_id:str=Field(default='',max_length=64)
 coach_report_access:bool|None=None
 @model_validator(mode='after')
 def valid_summary(self):
  if self.summary is not None and len(self.summary.split())>250:raise ValueError('Keep the Work Styles summary within 250 words.')
  return self
def identity(user):return hashlib.sha256((user+':work-preferences').encode()).hexdigest()[:32]
def read(user):
 row=db.get(user,identity(user),'work_preferences')
 d=(row or {}).get('data',{'revision':0,'preferences':[],'use_for_ai':False,'reviewed':False,'assessment_id':''})
 return {**d,'summary':d.get('summary',''),'coach_report_access':d.get('coach_report_access') is True}
def context(user):
 from .work_style_summary import safe
 d=read(user);values=[d['summary']] if d.get('summary') else d['preferences']
 values=[v for v in values if safe(v)]
 return {'revision':d['revision'],'preferences':values,'kind':'approved self-described Work Styles summary; not qualifications'} if d.get('use_for_ai') and d.get('reviewed') else {'revision':d['revision'],'preferences':[],'kind':'not enabled'}

def resume_context(user):
 # New resume use requires the expanded scope to have been explicitly saved.
 d=read(user)
 return context(user) if d['coach_report_access'] else {'revision':d['revision'],'preferences':[],'kind':'not enabled'}

def coach_context(user):
 """Only an explicitly shared account-owned report, never questionnaire answers."""
 d=read(user)
 if not (d.get('use_for_ai') and d.get('reviewed') and d['coach_report_access']):return None
 row=db.get(user,d.get('assessment_id',''),'work_style')
 if not row or row['data'].get('status')!='completed':return None
 report=row['data'].get('report') or {'domains':row['data'].get('scores',[])}
 fields=('dimension_id','facet_id','name','total','minimum','maximum','mean','description','pattern','suggestion','lower_end','upper_end','potential','friction','environment')
 def scores(key,limit):return [{k:v[k] for k in fields if k in v and isinstance(v[k],(str,int,float))} for v in report.get(key,[])[:limit] if isinstance(v,dict)]
 choices=[{k:v[k] for k in ('theme','left','right','choice','selected') if isinstance(v.get(k),str)} for v in report.get('preferences',[])[:12] if isinstance(v,dict)]
 return {'record_id':row['id'],'revision':str(d['revision'])+':'+row['updated_at'],'report':{'version':str(report.get('version','legacy')),'explanation':str(report.get('explanation','Self-reflection, not qualifications or a hiring prediction.')),'domains':scores('domains',5),'facets':scores('facets',30),'work_choices':choices}}
def assessment(user):
 rows=db.list_entities(user,'work_style');complete=next((v for v in rows if v['data'].get('status')=='completed'),None)
 # Only explicit paired work choices are eligible, never personality scores/facets.
 choices=[p['selected'] for p in (complete or {}).get('data',{}).get('report',{}).get('preferences',[])]
 summary=[{'name':d['name'],'pattern':d['pattern']} for d in (complete or {}).get('data',{}).get('report',{}).get('domains',[]) if isinstance(d,dict) and isinstance(d.get('name'),str) and isinstance(d.get('pattern'),str)]
 suggestions=role_catalog.suggestions(user)
 groups=[name for name,roles in role_catalog.GROUPS.items() if any(v in roles for v in suggestions)]
 return {'completed':bool(complete),'assessment_id':complete['id'] if complete else '', 'completed_at':(complete or {}).get('data',{}).get('completed_at'),'summary':summary[:5],'suggested_preferences':choices[:12],'roles':suggestions[:4],'fields':groups[:3]}
@router.get('')
def get(user=Depends(auth.current)):return {**read(user['id']),'assessment':assessment(user['id']),'account_id':user['id'],'ai_available':bool(credentials.get(user['id'])) and onboarding.status(user['id'])['completed'],'setup_required':not onboarding.status(user['id'])['completed'],'mode':db.settings(user['id']).get('mode','economy')}
@router.put('')
def put(body:Change,user=Depends(auth.current)):
 from .resume_conversation import write
 from .work_style_summary import paragraph,safe
 summary=paragraph(body.summary) if body.summary and body.summary.strip() else '' if body.summary is not None else None
 values=list(dict.fromkeys(v.strip() for v in body.preferences if v.strip()))
 if any(len(v)>240 for v in values):raise HTTPException(422,'Keep each preference within 240 characters.')
 if body.use_for_ai and (not body.reviewed or not (summary if summary is not None else values)):raise HTTPException(422,'Review a Work Styles summary before enabling AI guidance.')
 if body.use_for_ai and any(not safe(v) for v in ([summary] if summary is not None else values)):raise HTTPException(422,'Keep AI guidance focused on working style; remove excluded private material.')
 if body.assessment_id and not db.get(user['id'],body.assessment_id,'work_style'):raise HTTPException(404,'Assessment not found.')
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');row=c.execute("SELECT payload FROM entities WHERE id=? AND user_id=?",(identity(user['id']),user['id'])).fetchone();old=json.loads(row[0]) if row else {'revision':0}
  if old['revision']!=body.expected_revision:raise HTTPException(409,'Work preferences changed in another window. Your draft is preserved; reload the saved revision.')
  coach_access=body.coach_report_access if body.coach_report_access is not None else old.get('coach_report_access') is True
  coach_access=bool(coach_access and body.use_for_ai and body.reviewed)
  if coach_access and body.coach_report_access is None and body.assessment_id!=old.get('assessment_id',''):coach_access=False
  generation=None
  if body.generation_task_id:
   task=c.execute("SELECT result FROM tasks WHERE id=? AND user_id=? AND kind='work_style_summary' AND status='completed'",(body.generation_task_id,user['id'])).fetchone()
   if not task:raise HTTPException(404,'The generated summary is unavailable. Save a manual summary or recover its completed request.')
   result=json.loads(task['result']);result=result.get('_task_result',result)
   if result.get('expected_revision')!=body.expected_revision:raise HTTPException(409,'This AI proposal belongs to an older summary revision. Your draft is preserved.')
   generation={'task_id':body.generation_task_id,'ai':result['ai'],'references':result['references'],'source_snapshot':result['source_snapshot'],'edited_after_generation':summary!=result['summary']}
  data={**old,**body.model_dump(exclude={'expected_revision','summary','generation_task_id'}),'preferences':values if summary is None else old.get('preferences',[]),'revision':old['revision']+1}
  data['coach_report_access']=coach_access
  if summary is not None:data.update(summary=summary,generation=generation)
  write(c,user['id'],'work_preferences',data,identity(user['id']))
 return get(user)
