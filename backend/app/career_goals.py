"""Aspirations, never professional qualification evidence."""
import hashlib,re
from fastapi import APIRouter,Depends,HTTPException
from pydantic import Field
from . import auth,db
from .models import StrictModel
router=APIRouter(prefix='/api/profile/career-goals')
EXPLANATION='Describe your career ambitions, dream jobs, skills you want to learn or certifications you’re considering. Career Goals mainly helps Career Coach personalize its advice. You can also choose to use relevant goals when drafting open-ended application answers, such as “Why do you want this job?” Goals are not qualifications and are not automatically added to resumes, cover letters or application fields.'
class Change(StrictModel):
 text:str=Field(default='',max_length=6000)
 expected_revision:int=Field(ge=0)
def identity(user):return hashlib.sha256((user+':career-goals').encode()).hexdigest()[:32]
def read(user):
 row=db.get(user,identity(user),'career_goals')
 return {**(row['data'] if row else {'text':'','revision':0}),'updated_at':row['updated_at'] if row else None,'explanation':EXPLANATION}
def save(user,body):
 from .resume_conversation import write
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');row=c.execute("SELECT payload FROM entities WHERE id=? AND user_id=? AND kind='career_goals'",(identity(user),user)).fetchone()
  import json
  old=json.loads(row[0]) if row else {'revision':0}
  if old['revision']!=body.expected_revision:raise HTTPException(409,'Career Goals changed in another tab. Reload them before saving; your text is preserved.')
  write(c,user,'career_goals',{'text':body.text.strip(),'revision':old['revision']+1},identity(user))
 return read(user)
@router.get('')
def get(user=Depends(auth.current)):return read(user['id'])
@router.put('')
def put(body:Change,user=Depends(auth.current)):return save(user['id'],body)
def explicit_save(text):
 return bool(re.search(r'\b(save|update|replace|set|change)\b.{0,100}\b(my\s+)?(profile\s+)?(career\s+goals?|goals?\s+(in|to)\s+(my\s+)?profile)\b',text,re.I)) and not re.search(r"\b(don.t|do not|not yet|maybe|should I|can you explain|how (do|can|would))\b",text,re.I)
def eligible(question):
 from .application_agent import PRIVATE,BOUNDARY
 text=str(question.get('label',''))+' '+str(question.get('description',''))
 return question.get('control') in ('text','textarea') and not question.get('options') and not question.get('private') and not PRIVATE.search(text) and not BOUNDARY.search(text) and not re.search(r'\b(eligib|authoriz|sponsor|years? of|certified|license|credential|salary|criminal|disabil|veteran|citizen)',text,re.I) and bool(re.search(r'why.{0,50}(want|interest|join|fit)|what.{0,30}(attract|interest)|career (goal|aspiration)|motivation|good fit',text,re.I))
