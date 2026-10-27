"""Aspirations, never professional qualification evidence."""
import hashlib,re,json
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException
from pydantic import Field,model_validator
from . import auth,db
from .models import StrictModel
router=APIRouter(prefix='/api/profile/career-goals')
EXPLANATION='Describe your career ambitions, dream jobs, skills you want to learn or certifications you’re considering. Career Goals mainly helps Career Coach personalize its advice. You can also choose to use relevant goals when drafting open-ended application answers, such as “Why do you want this job?” Goals are not qualifications and are not automatically added to resumes, cover letters or application fields.'
class Goal(StrictModel):
 id:str=Field(min_length=1,max_length=64,pattern=r'^[A-Za-z0-9_-]+$')
 category:Literal['general_statement','dream_role','skill','certification','promotion','leadership','education','career_change','impact','networking','custom']='custom'
 text:str=Field(min_length=1,max_length=36000)
 target:str=Field(default='',max_length=100)
 priority:Literal['low','medium','high']='medium'
 progress:Literal['planned','in_progress','completed']='planned'
 @model_validator(mode='after')
 def valid_text(self):
  if not self.text.strip() or self.category!='general_statement' and len(self.text)>1000:raise ValueError('Enter a goal within its text limit.')
  if self.category=='general_statement':self.target='';self.priority='medium';self.progress='planned'
  return self
class Change(StrictModel):
 text:str|None=Field(default=None,max_length=36000)
 expected_revision:int=Field(ge=0)
 items:list[Goal]|None=Field(default=None,max_length=31)
 use_for_ai:bool|None=None
 @model_validator(mode='after')
 def valid_items(self):
  if self.items is not None:
   if len({v.id for v in self.items})!=len(self.items):raise ValueError('Each goal needs a unique identifier.')
   if sum(v.category=='general_statement' for v in self.items)>1:raise ValueError('Only one General statement is allowed.')
   if sum(v.category!='general_statement' for v in self.items)>30:raise ValueError('Keep at most 30 specific goals.')
  return self
def identity(user):return hashlib.sha256((user+':career-goals').encode()).hexdigest()[:32]
def general_id(items):
 id='legacy-general-statement';n=0
 while any(v['id']==id for v in items):n+=1;id='legacy-general-statement-'+str(n)
 return id

def canonical_items(d):
 items=[dict(v) for v in d.get('items',[])]
 note=d.get('note',d.get('text','') if not items else '')
 if note and not any(v['category']=='general_statement' for v in items):
  id=general_id(items)
  items.insert(0,Goal(id=id,category='general_statement',text=note).model_dump())
 return items

def read(user):
 row=db.get(user,identity(user),'career_goals')
 d=row['data'] if row else {'text':'','revision':0}
 items=canonical_items(d)
 return {**d,'use_for_ai':bool(d.get('use_for_ai',False)),'note':next((v['text'] for v in items if v['category']=='general_statement'),''),'items':items,'updated_at':row['updated_at'] if row else None,'explanation':EXPLANATION}
def context(user,snapshot=None):
 """Opt-in automatic context; historical snapshots remain unchanged in storage."""
 current=read(user)
 if not current['use_for_ai']:return {'text':'','note':'','items':[],'revision':current['revision'],'use_for_ai':False}
 value=snapshot if snapshot is not None else current
 return {**value,'use_for_ai':True}

def save(user,body):
 from .resume_conversation import write
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');row=c.execute("SELECT payload FROM entities WHERE id=? AND user_id=? AND kind='career_goals'",(identity(user),user)).fetchone()
  old=json.loads(row[0]) if row else {'revision':0}
  if old['revision']!=body.expected_revision:raise HTTPException(409,'Career Goals changed in another tab. Reload them before saving; your text is preserved.')
  items=[v.model_dump() for v in body.items] if body.items is not None else canonical_items(old)
  if body.text is not None:
   general=next((v for v in items if v['category']=='general_statement'),None)
   # Old clients and explicit chat saves use text as the general statement.
   if body.items is None or not general:
    items=[v for v in items if v['category']!='general_statement']
    if body.text.strip():items.insert(0,Goal(id=(general or {}).get('id') or general_id(items),category='general_statement',text=body.text.strip()).model_dump())
  if len({v['id'] for v in items})!=len(items):raise HTTPException(422,'Each goal needs a unique identifier.')
  if sum(v['category']=='general_statement' for v in items)>1:raise HTTPException(422,'Only one General statement is allowed. Edit the existing statement.')
  if sum(v['category']!='general_statement' for v in items)>30:raise HTTPException(422,'Keep at most 30 specific goals.')
  note=next((v['text'] for v in items if v['category']=='general_statement'),'')
  rendered='\n'.join(v['text'] if v['category']=='general_statement' else v['category'].replace('_',' ')+': '+v['text']+(' — target '+v['target'] if v['target'] else '')+' ('+v['progress'].replace('_',' ')+')' for v in items).strip()
  write(c,user,'career_goals',{'text':rendered,'note':note,'items':items,'format_version':2,'use_for_ai':body.use_for_ai if body.use_for_ai is not None else bool(old.get('use_for_ai',False)),'revision':old['revision']+1},identity(user))
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
