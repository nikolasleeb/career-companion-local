"""Aspirations, never professional qualification evidence."""
import hashlib,re,json
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException
from pydantic import Field,model_validator
from . import auth,db
from .models import StrictModel
router=APIRouter(prefix='/api/profile/career-goals')
EXPLANATION='Describe your career ambitions, dream jobs, skills you want to learn or certifications you’re considering. Career Goals mainly helps Career Coach personalize its advice. You can also choose to use relevant goals when drafting open-ended application answers, such as “Why do you want this job?” Goals are not qualifications and are not automatically added to resumes, cover letters or application fields.'
class OccupationLink(StrictModel):
 code:str=Field(pattern=r'^\d{2}-\d{4}\.\d{2}$')
 title:str=Field(min_length=1,max_length=300)
 dataset_version:str=Field(max_length=100)
 revision:str=Field(pattern=r'^[a-f0-9]{64}$')

def normalize_omissions(text):
 if '[blank]' not in text:return text
 return re.sub(r'[ \t]+',' ',text.replace('[blank]','')).strip()

class StatementFields(StrictModel):
 graduation:str=Field(default='',max_length=1000)
 degree:str=Field(default='',max_length=1000)
 completed_degree:str=Field(default='',max_length=1000)
 future_education:str=Field(default='',max_length=1000)
 field:str=Field(default='',max_length=1000)
 focus:str=Field(default='',max_length=1000)
 skills:str=Field(default='',max_length=1000)
 certifications:str=Field(default='',max_length=1000)
 timing:str=Field(default='',max_length=1000)
 commitments:str=Field(default='',max_length=1000)
 priorities:str=Field(default='',max_length=1000)
 reason:str=Field(default='',max_length=1000)
 other:str=Field(default='',max_length=3000)
 @model_validator(mode='after')
 def omissions(self):
  for key in type(self).model_fields:
   value=getattr(self,key).strip()
   setattr(self,key,'' if value=='[blank]' else value)
  return self

class StatementEditor(StrictModel):
 version:Literal[1]=1
 mode:Literal['guided','direct']='guided'
 education:Literal['yes','no','skip']='skip'
 fields:StatementFields=Field(default_factory=StatementFields)

class Goal(StrictModel):
 id:str=Field(min_length=1,max_length=64,pattern=r'^[A-Za-z0-9_-]+$')
 category:Literal['general_statement','dream_role','skill','certification','promotion','leadership','education','career_change','impact','networking','custom']='custom'
 text:str=Field(min_length=1,max_length=36000)
 target:str=Field(default='',max_length=100)
 priority:Literal['low','medium','high']='medium'
 progress:Literal['planned','in_progress','completed']='planned'
 occupation:OccupationLink|None=None
 guided_editor:StatementEditor|None=None
 @model_validator(mode='after')
 def valid_text(self):
  self.text=normalize_omissions(self.text)
  if not re.search(r'[^\W_]',self.text) or self.category!='general_statement' and len(self.text)>1000:raise ValueError('Enter a meaningful goal within its text limit.')
  if self.guided_editor and self.category!='general_statement':raise ValueError('Guided fields belong only to Overall career direction.')
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
   links=[v.occupation.code for v in self.items if v.occupation]
   if len(links)!=len(set(links)):raise ValueError('Each occupation can link to only one goal.')
   if len({v.id for v in self.items})!=len(self.items):raise ValueError('Each goal needs a unique identifier.')
   if sum(v.category=='general_statement' for v in self.items)>1:raise ValueError('Only one Overall career direction statement is allowed.')
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
  items.insert(0,Goal(id=id,category='general_statement',text=note).model_dump(exclude_none=True))
 return items

def read(user):
 row=db.get(user,identity(user),'career_goals')
 d=row['data'] if row else {'text':'','revision':0}
 items=canonical_items(d)
 return {**d,'use_for_ai':bool(d.get('use_for_ai',False)),'note':next((v['text'] for v in items if v['category']=='general_statement'),''),'items':items,'updated_at':row['updated_at'] if row else None,'explanation':EXPLANATION}
def context(user,snapshot=None):
 """Opt-in automatic context; historical snapshots remain unchanged in storage."""
 current=read(user)
 if not __import__('app.personalization',fromlist=['allowed']).allowed(user,'goals'):return {'text':'','note':'','items':[],'revision':current['revision'],'use_for_ai':False}
 value=snapshot if snapshot is not None else current
 return {**value,'items':[for_guidance_goal(g) for g in canonical_items(value)],'use_for_ai':True}

GUIDANCE='Overall career direction describes broad aspirations; specific goals are independent milestones. Connect relevant milestones to the direction without repeating equivalent ambitions. Ask about conflicting dates or priorities instead of silently resolving them. Skills to learn and certifications to earn are not existing qualifications or accomplishments.'

def for_guidance_goal(goal):
 return {key:value for key,value in goal.items() if key!='guided_editor'}

def guidance_text(value):
 """One text representation, with editing aids excluded from provider context."""
 items=canonical_items(value)
 direction=next((normalize_omissions(g['text']) for g in items if g['category']=='general_statement'),'')
 milestones=[g for g in items if g['category']!='general_statement']
 parts=['Overall career direction (aspiration):\n'+direction] if direction else []
 if milestones:
  parts.append('Specific goals (milestones, not qualifications):\n'+'\n'.join(g['category'].replace('_',' ')+': '+normalize_omissions(g['text'])+(' — target '+g['target'] if g.get('target') else '')+' ('+g.get('progress','planned').replace('_',' ')+')' for g in milestones))
 return '\n\n'.join(parts)

def model_context(value):
 return {'text':guidance_text(value),'revision':value.get('revision',0),'use_for_ai':value.get('use_for_ai',False),'guidance':GUIDANCE}

def guidance_context(user,snapshot=None,query=''):
 value=context(user,snapshot);items=canonical_items(value)
 terms=set(re.findall(r'\w{3,}',query.casefold()))
 if terms:
  ranked=sorted(items,key=lambda g:-len(terms&set(re.findall(r'\w{3,}',g['text'].casefold()))))
  matched=[g for g in ranked if terms&set(re.findall(r'\w{3,}',g['text'].casefold()))]
  items=matched or ranked[:3]
 selected=[];size=0
 for goal in items:
  if size+len(goal['text'])>6000:continue
  selected.append(goal);size+=len(goal['text'])
 result=model_context({**value,'text':'','note':'','items':selected})
 return {**result,'context_limited':len(selected)<len(canonical_items(value))}


def save(user,body,*,restoring=False):
 from .resume_conversation import write
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');row=c.execute("SELECT payload FROM entities WHERE id=? AND user_id=? AND kind='career_goals'",(identity(user),user)).fetchone()
  old=json.loads(row[0]) if row else {'revision':0}
  if old['revision']!=body.expected_revision:raise HTTPException(409,'Career Goals changed in another tab. Reload them before saving; your text is preserved.')
  items=[v.model_dump(exclude_none=True) for v in body.items] if body.items is not None else canonical_items(old)
  if body.text is not None:
   general=next((v for v in items if v['category']=='general_statement'),None)
   # Old clients and explicit chat saves use text as the general statement.
   if body.items is None or not general:
    items=[v for v in items if v['category']!='general_statement']
    if body.text.strip():items.insert(0,Goal(id=(general or {}).get('id') or general_id(items),category='general_statement',text=body.text.strip()).model_dump(exclude_none=True))
  if len({v['id'] for v in items})!=len(items):raise HTTPException(422,'Each goal needs a unique identifier.')
  if sum(v['category']=='general_statement' for v in items)>1:raise HTTPException(422,'Only one Overall career direction statement is allowed. Edit the existing statement.')
  if sum(v['category']!='general_statement' for v in items)>30:raise HTTPException(422,'Keep at most 30 specific goals.')
  linked=[v['occupation']['code'] for v in items if v.get('occupation')]
  if len(set(linked))!=len(linked):raise HTTPException(409,'This occupation already has a Career Goal. Edit the existing goal.')
  old_links={v['id']:v.get('occupation') for v in canonical_items(old)}
  from . import explicit_context
  for value in items:
   link=value.get('occupation')
   if link and link!=old_links.get(value['id']) and not restoring:
    canonical=explicit_context.occupation_link(link['code'])
    if link!=canonical:raise HTTPException(409,'The occupation information changed. Reload its details and review this goal again. Your draft is preserved.')
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
