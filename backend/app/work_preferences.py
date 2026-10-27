"""Reviewed work conditions, separate from assessment answers and qualifications."""
import hashlib,json
from fastapi import APIRouter,Depends,HTTPException
from pydantic import Field
from . import auth,db,role_catalog
from .models import StrictModel
router=APIRouter(prefix='/api/profile/work-preferences')
class Change(StrictModel):
 expected_revision:int=Field(ge=0)
 preferences:list[str]=Field(default_factory=list,max_length=12)
 use_for_ai:bool=False
 reviewed:bool=False
 assessment_id:str=Field(default='',max_length=64)
def identity(user):return hashlib.sha256((user+':work-preferences').encode()).hexdigest()[:32]
def read(user):
 row=db.get(user,identity(user),'work_preferences')
 return (row or {}).get('data',{'revision':0,'preferences':[],'use_for_ai':False,'reviewed':False,'assessment_id':''})
def context(user):
 d=read(user)
 return {'revision':d['revision'],'preferences':d['preferences'],'kind':'self-reported working preferences; not qualifications'} if d.get('use_for_ai') and d.get('reviewed') else {'revision':d['revision'],'preferences':[],'kind':'not enabled'}
def assessment(user):
 rows=db.list_entities(user,'work_style');complete=next((v for v in rows if v['data'].get('status')=='completed'),None)
 # Only explicit paired work choices are eligible, never personality scores/facets.
 choices=[p['selected'] for p in (complete or {}).get('data',{}).get('report',{}).get('preferences',[])]
 summary=[{'name':d['name'],'pattern':d['pattern']} for d in (complete or {}).get('data',{}).get('report',{}).get('domains',[]) if isinstance(d,dict) and isinstance(d.get('name'),str) and isinstance(d.get('pattern'),str)]
 suggestions=role_catalog.suggestions(user)
 groups=[name for name,roles in role_catalog.GROUPS.items() if any(v in roles for v in suggestions)]
 return {'completed':bool(complete),'assessment_id':complete['id'] if complete else '', 'completed_at':(complete or {}).get('data',{}).get('completed_at'),'summary':summary[:5],'suggested_preferences':choices[:12],'roles':suggestions[:4],'fields':groups[:3]}
@router.get('')
def get(user=Depends(auth.current)):return {**read(user['id']),'assessment':assessment(user['id'])}
@router.put('')
def put(body:Change,user=Depends(auth.current)):
 from .resume_conversation import write
 values=list(dict.fromkeys(v.strip() for v in body.preferences if v.strip()))
 if any(len(v)>240 for v in values):raise HTTPException(422,'Keep each preference within 240 characters.')
 if body.use_for_ai and (not body.reviewed or not values):raise HTTPException(422,'Review at least one work preference before enabling AI guidance.')
 if body.assessment_id and not db.get(user['id'],body.assessment_id,'work_style'):raise HTTPException(404,'Assessment not found.')
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');row=c.execute("SELECT payload FROM entities WHERE id=? AND user_id=?",(identity(user['id']),user['id'])).fetchone();old=json.loads(row[0]) if row else {'revision':0}
  if old['revision']!=body.expected_revision:raise HTTPException(409,'Work preferences changed in another window. Your draft is preserved; reload the saved revision.')
  write(c,user['id'],'work_preferences',{**body.model_dump(exclude={'expected_revision'}),'preferences':values,'revision':old['revision']+1},identity(user['id']))
 return get(user)
