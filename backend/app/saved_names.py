"""Account-local saved conversation names. Call allocators under a write lock."""
import json,re,unicodedata
from fastapi import HTTPException
CHAT_KINDS={'coach_chat','assistant_chat'}
INTERVIEW_LABELS={'behavioral':'Behavioral','star':'STAR','coding':'Coding','case':'Case / business','domain':'Domain / scenario','presentation':'Presentation / portfolio','other':'Other'}

def clean(value):return ' '.join(unicodedata.normalize('NFKC',value or '').split())
def key(value):return clean(value).casefold()
def available(c,user,kind,title,exclude=''):
 return not any(key(json.loads(r['payload']).get('title',''))==key(title) for r in c.execute('SELECT payload FROM entities WHERE user_id=? AND kind=? AND id!=?',(user,kind,exclude)))
def require_available(c,user,kind,title,exclude=''):
 if not clean(title):raise HTTPException(422,'Enter a conversation name.')
 if not available(c,user,kind,title,exclude):raise HTTPException(409,'A saved conversation already uses this name. Choose a different name.')
def preflight(user,kind,title,task_kind,token):
 from . import db
 with db.connect() as c:
  # A lost start response must recover its original task, even after its chat
  # has committed. start_task still validates all original inputs.
  for row in c.execute('SELECT result FROM tasks WHERE user_id=? AND kind=?',(user,task_kind)):
   payload=json.loads(row['result'] or '{}');inputs=payload.get('_task_inputs',payload.get('inputs',{}))
   if inputs.get('request_token')==token:return
  require_available(c,user,kind,title)
def imported_title(c,user,kind,title):
 title=clean(title) or 'Career conversation';candidate=title;number=2
 while not available(c,user,kind,candidate):
  suffix=f' (imported {number})';candidate=title[:100-len(suffix)]+suffix;number+=1
 return candidate

def next_interview(c,user,kind):
 label=INTERVIEW_LABELS[kind]
 row=c.execute('SELECT settings FROM users WHERE id=?',(user,)).fetchone()
 settings=json.loads(row['settings']);counters=settings.get('_interview_sequences',{})
 highest=int(counters.get(kind,0));pattern=re.compile(re.escape(label)+r' (\d+)',re.I)
 for r in c.execute("SELECT payload FROM entities WHERE user_id=? AND kind='interview_session'",(user,)):
  match=pattern.fullmatch(clean(json.loads(r['payload']).get('title','')))
  if match:highest=max(highest,int(match[1]))
 number=highest+1
 while not available(c,user,'interview_session',f'{label} {number}'):number+=1
 settings['_interview_sequences']={**counters,kind:number}
 c.execute('UPDATE users SET settings=? WHERE id=?',(json.dumps(settings),user))
 return f'{label} {number}'


def next_practice(c,user):
 row=c.execute('SELECT settings FROM users WHERE id=?',(user,)).fetchone()
 settings=json.loads(row['settings']);highest=int(settings.get('_skills_practice_sequence',0))
 for row in c.execute("SELECT payload FROM entities WHERE user_id=? AND kind='prep'",(user,)):
  match=re.fullmatch(r'Skills practice (\d+)',json.loads(row['payload']).get('title',''))
  if match:highest=max(highest,int(match[1]))
 number=highest+1;settings['_skills_practice_sequence']=number
 c.execute('UPDATE users SET settings=? WHERE id=?',(json.dumps(settings),user))
 return f'Skills practice {number}'
