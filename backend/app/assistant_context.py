"""Rebuilt, versioned account-only SQLite FTS retrieval. No stale private index."""
import json,re,sqlite3,hashlib
from . import db,career_coach,career_goals,work_preferences,job_ai
VERSION='account-context-v4'
PRIVATE=re.compile(r'citizenship|visa|sponsor|work authori|vaccin|disabil|veteran|religio|politic|sexual|marital|date of birth|social security|api.?key|password',re.I)
def clean(value):
 # Keep valid ISO tracking dates; the generic phone scrubber also matches them.
 from datetime import date
 dates={}
 def keep(match):
  try:date.fromisoformat(match[0])
  except ValueError:return match[0]
  marker='KEEPSAVEDDATE'+chr(65+len(dates)//26)+chr(65+len(dates)%26)+'END'
  dates[marker]=match[0];return marker
 text=job_ai.clean(re.sub(r'\b\d{4}-\d{2}-\d{2}\b',keep,str(value)))
 text='\n'.join(line for line in text.splitlines() if not PRIVATE.search(line))
 for marker,value in dates.items():text=text.replace(marker,value)
 return text
def sources(user,excluded=()):
 from . import coach_access,coach_bls
 rows=[]
 def add(record,report=False):
  value=job_ai.clean(record['text']) if report else clean(record['text'])
  if not value.strip():return
  for at in range(0,min(len(value),96000 if report else 24000),1800):
   rows.append({**{k:record[k] for k in ('record_id','kind','label','revision','status')},'source_id':record['record_id']+':'+str(at),'label':clean(record['label']) or 'Saved professional source','text':value[at:at+1800],'index_version':VERSION})
 for record in coach_access.records(user,excluded):add(record)
 g=career_goals.context(user)
 if g['text']:add({'record_id':career_goals.identity(user),'kind':'aspiration','label':'Career Goals · aspirations, not qualifications','revision':str(g['revision']),'status':'shared','text':g['text']})
 w=work_preferences.context(user)
 if w['preferences']:add({'record_id':work_preferences.identity(user),'kind':'preference','label':'Approved Work Styles summary · not qualifications','revision':str(w['revision']),'status':'shared','text':'\n'.join(w['preferences'])})
 report=work_preferences.coach_context(user)
 if report:add({'record_id':report['record_id'],'kind':'work_style_report','label':'Work Styles report and scores · self-reflection, not qualifications','revision':report['revision'],'status':'shared','text':json.dumps(report['report'],ensure_ascii=False,indent=2)},True)
 for record in coach_bls.public_sources():add(record)
 return rows

def retrieve(user,question,pinned=(),excluded=()):
 rows=[s for s in sources(user,excluded) if s['record_id'] not in excluded]
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
