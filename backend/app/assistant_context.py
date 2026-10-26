"""Rebuilt, versioned account-only SQLite FTS retrieval. No stale private index."""
import json,re,sqlite3,hashlib
from . import db,career_coach,career_goals,work_preferences,job_ai
VERSION='account-context-v1'
PRIVATE=re.compile(r'citizenship|visa|sponsor|work authori|vaccin|disabil|veteran|religio|politic|sexual|marital|date of birth|social security|api.?key|password',re.I)
def clean(value):
 text=job_ai.clean(str(value))
 return '\n'.join(line for line in text.splitlines() if not PRIVATE.search(line))
def sources(user):
 rows=[]
 def add(id,record,kind,label,text,revision):
  text=clean(text)
  if not text.strip():return
  for at in range(0,min(len(text),24000),1800):
   chunk=text[at:at+1800];rows.append({'source_id':id+':'+str(at),'record_id':record,'kind':kind,'label':label[:180],'text':chunk,'revision':revision,'index_version':VERSION})
 for s in career_coach.profile(user)['sources']:add('profile:'+s['id'],s['record_id'],'reviewed_profile','Reviewed Profile · '+s['field'],s['text'],hashlib.sha256(s['text'].encode()).hexdigest())
 g=career_goals.read(user);add('goals',career_goals.identity(user),'aspiration','Career Goals · aspirations, not qualifications',g['text'],str(g['revision']))
 w=work_preferences.context(user)
 if w['preferences']:add('preferences',work_preferences.identity(user),'preference','Approved work preferences · not qualifications','\n'.join(w['preferences']),str(w['revision']))
 def resume_text(d):
  if not isinstance(d,dict):return ''
  if isinstance(d.get('snapshot'),dict):d=d['snapshot']
  if isinstance(d.get('resume'),dict):d=d['resume']
  return '\n'.join([str(d.get('headline') or ''),*[str(e.get('title',''))+'\n'+'\n'.join(str(x) for x in e.get('bullets',[])) for s in d.get('sections',[]) if isinstance(s,dict) for e in s.get('entries',[]) if isinstance(e,dict)]])
 allowed={'resume','resume_revision','application','job','analysis','prep','coach_plan'}
 # Fetch only supported account-owned records. Raw documents, vaults, settings,
 # questionnaire answers and private reusable answers never enter this catalog.
 with db.connect() as c:
  records=[db.decode(r) for r in c.execute("SELECT * FROM entities WHERE user_id=? AND kind IN ('resume','resume_revision','application','job','analysis','prep','coach_plan') ORDER BY updated_at DESC LIMIT 1200",(user,))]
 for r in records:
  d=r['data'];kind=r['kind'];label=str(d.get('title') or d.get('company') or d.get('direction') or kind.replace('_',' '))[:150];text=''
  if kind in ('resume','resume_revision'):text=resume_text(d);label='Saved generated resume · '+label
  elif kind=='application':text='\n'.join(str(d.get(k) or '') for k in ('title','company','status'));label='Application · '+label
  elif kind=='job':
   if d.get('cache_tombstone'):continue
   text='\n'.join(str(d.get(k) or '') for k in ('title','company','location','description'));label='Employer posting · '+label
  elif kind=='analysis':text=str(d.get('summary',''))+'\n'+'\n'.join(str(v.get(k,'')) for v in d.get('suggestions',[]) if isinstance(v,dict) for k in ('original','proposed','reason'));label='Saved analysis / recorded edits · '+label
  elif kind=='prep':text='\n'.join(str(v) for v in d.get('priorities',[]));label='Saved learning plan'
  elif kind=='coach_plan':text=str(d.get('direction',''))+'\n'+'\n'.join(str(a.get('title',''))+' '+str(a.get('why',''))+' '+' '.join(a.get('steps',[])) for a in d.get('actions',[]));label='Saved generated career plan'
  add(r['id'],r['id'],kind,label,text,r['updated_at'])
 return rows

def retrieve(user,question,pinned=(),excluded=()):
 rows=[s for s in sources(user) if s['record_id'] not in excluded]
 existing={s['record_id'] for s in rows}
 if any(id not in existing for id in pinned):
  from fastapi import HTTPException
  raise HTTPException(404,'A pinned source is unavailable or excluded. Update the context selection.')
 terms=list(dict.fromkeys(re.findall(r'[\w+#.-]{2,40}',question.casefold())))[:50]
 match=' OR '.join('"'+v.replace('"','')+'"' for v in terms)
 with sqlite3.connect(':memory:') as c:
  c.execute('CREATE VIRTUAL TABLE context USING fts5(id UNINDEXED,label,text)')
  c.executemany('INSERT INTO context VALUES(?,?,?)',[(s['source_id'],s['label'],s['text']) for s in rows])
  ids=[v[0] for v in c.execute('SELECT id FROM context WHERE context MATCH ? ORDER BY bm25(context) LIMIT 18',(match,))] if match else []
 catalog={s['source_id']:s for s in rows};selected=[s for s in rows if s['record_id'] in pinned][:8]
 selected += [catalog[id] for id in ids if id not in {s['source_id'] for s in selected}]
 selected += [s for s in rows if s['kind'] in ('reviewed_profile','aspiration','preference') and s['source_id'] not in {v['source_id'] for v in selected}][:6]
 out=[];used=0
 for s in selected:
  if len(out)>=18 or used+len(s['text'])>26000:break
  out.append(s);used+=len(s['text'])
 return out
