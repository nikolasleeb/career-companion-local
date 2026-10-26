"""Task-local SQLite overlays: publish business changes once, or discard them.

No database lock is held across awaits. Context propagates to asyncio.to_thread;
late threads cannot write after the task has stopped. Usage has a separate lane.
"""
import asyncio,contextvars,functools,json,re,sqlite3
from contextlib import contextmanager
from fastapi import HTTPException
_context=contextvars.ContextVar('atomic_task',default=None)
TABLES={'entities':('id',),'users':('id',),'cc_search_rows':('search_id','job_id'),'cc_job_lifecycle':('user_id','job_id')}
class Stopped(BaseException):pass
class Connection(sqlite3.Connection):
 def execute(self,sql,parameters=(),/):
  # SQLite does not support UPSERT syntax on a view. These tables use complete
  # rows on INSERT; the overlay trigger preserves the original created_at.
  if getattr(self,'overlay',False) and re.match(r'\s*INSERT\s+INTO\s+(entities|cc_job_lifecycle)\b',sql,re.I):
   sql=re.split(r'\s+ON\s+CONFLICT\s*\(',sql,flags=re.I)[0]
   parameters=parameters[:sql.count('?')]
  return super().execute(sql,parameters)

def current():return _context.get()
@contextmanager
def outside():
 token=_context.set(None)
 try:yield
 finally:_context.reset(token)
def independent(fn):
 @functools.wraps(fn)
 def wrapped(*a,**k):
  with outside():return fn(*a,**k)
 return wrapped

def init(c):
 c.execute('CREATE TABLE IF NOT EXISTS cc_task_stage(task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,table_name TEXT NOT NULL,row_key TEXT NOT NULL,before_row TEXT NOT NULL,after_row TEXT,PRIMARY KEY(task_id,table_name,row_key))')
 c.execute("DELETE FROM cc_task_stage WHERE task_id IN (SELECT id FROM tasks WHERE status NOT IN ('queued','running'))")

def columns(c,table):return [r['name'] for r in c.execute('PRAGMA main.table_info('+table+')')]
def obj(cols,prefix=''):return 'json_object('+','.join("'"+v+"',"+prefix+'"'+v+'"' for v in cols)+')'
def key_expr(keys,prefix=''):return 'json_array('+','.join(prefix+'"'+v+'"' for v in keys)+')'

def attach(c):
 context=current()
 if not context:return
 user,task=context
 row=c.execute('SELECT status,created_at FROM main.tasks WHERE id=? AND user_id=?',(task,user)).fetchone()
 if not row or row['status'] not in ('queued','running'):raise Stopped()
 c.create_function('atomic_task',0,lambda:task);c.create_function('atomic_user',0,lambda:user)
 for table,keys in TABLES.items():
  cols=columns(c,table)
  if not cols:continue
  scope='id' if table=='users' else 'user_id'
  scope_where='m."'+scope+'"=atomic_user()'
  main_key=key_expr(keys,'m.');new_key=key_expr(keys,'NEW.');old_key=key_expr(keys,'OLD.')
  projected=','.join("json_extract(s.after_row,'$."+v+"') AS \""+v+'"' for v in cols)
  # Task sees its own overlay plus committed rows. Other accounts never receive it.
  c.execute('CREATE TEMP VIEW "'+table+'" AS SELECT m.* FROM main."'+table+'" m WHERE NOT EXISTS (SELECT 1 FROM cc_task_stage s WHERE s.task_id=atomic_task() AND s.table_name=\''+table+'\' AND s.row_key='+main_key+') UNION ALL SELECT '+projected+' FROM cc_task_stage s WHERE s.task_id=atomic_task() AND s.table_name=\''+table+'\' AND s.after_row IS NOT NULL')
  for action,prefix,k in [('INSERT','NEW',new_key),('UPDATE','NEW',old_key),('DELETE','OLD',old_key)]:
   after='NULL' if action=='DELETE' else obj(cols,'NEW.')
   if table=='entities' and action=='INSERT':after=after.replace('NEW."created_at"',"coalesce((SELECT created_at FROM main.entities m WHERE "+main_key+'='+new_key+'),NEW."created_at")')
   if table=='cc_job_lifecycle' and action=='INSERT':after=after.replace('NEW."verified_at"','max(coalesce((SELECT verified_at FROM main.cc_job_lifecycle m WHERE '+main_key+'='+new_key+'),0),coalesce(NEW."verified_at",0))')
   before='coalesce((SELECT before_row FROM cc_task_stage WHERE task_id=atomic_task() AND table_name=\''+table+'\' AND row_key='+k+'),(SELECT '+obj(cols,'m.')+' FROM main."'+table+'" m WHERE '+main_key+'='+k+'),\'null\')'
   guard='SELECT CASE WHEN '+prefix+'."'+scope+'"!=atomic_user() THEN RAISE(ABORT,\'Task ownership mismatch\') END;'
   # Usage events are always written through the independent cost ledger.
   c.execute('CREATE TEMP TRIGGER atomic_'+table+'_'+action+' INSTEAD OF '+action+' ON "'+table+'" BEGIN '+guard+' INSERT INTO cc_task_stage VALUES(atomic_task(),atomic_user(),\''+table+'\','+k+','+before+','+after+') ON CONFLICT(task_id,table_name,row_key) DO UPDATE SET after_row=excluded.after_row; END')
 # Search-only indexes are derived, never published independently of records.
 for table,scope in [('evidence_fts','user_id'),('cc_coach_knowledge','scope')]:
  cols=columns(c,table)
  if not cols:continue
  c.execute('CREATE VIRTUAL TABLE temp.'+table+' USING fts5('+','.join('"'+v+'"' for v in cols)+')')
  c.execute('INSERT INTO temp.'+table+' SELECT * FROM main.'+table+' WHERE '+scope+" IN (?, 'public')",(user,))
 if columns(c,'cc_coach_knowledge'):
  for r in c.execute("SELECT payload FROM entities WHERE user_id=? AND kind='coach_research'",(user,)).fetchall():
   d=json.loads(r[0]);c.execute('DELETE FROM temp.cc_coach_knowledge WHERE scope=? AND chat_id=?',(user,d.get('chat_id','')))
   for s in d.get('chunks',[]):c.execute('INSERT INTO temp.cc_coach_knowledge VALUES(?,?,?,?,?,?,?)',(s['chunk_id'],user,d['chat_id'],s['title'],' '.join(s.get('topics',[])),s['text'],json.dumps(s)))
 c.commit()
 c.overlay=True

def bind(user,task):return _context.set((user,task))
def reset(token):_context.reset(token)
def discard(c,task):c.execute('DELETE FROM cc_task_stage WHERE task_id=?',(task,))
def publish(c,user,task):
 row=c.execute('SELECT status,created_at FROM tasks WHERE id=? AND user_id=?',(task,user)).fetchone()
 if not row or row['status']!='running':raise Stopped()
 changes=c.execute('SELECT * FROM cc_task_stage WHERE task_id=? AND user_id=? ORDER BY CASE table_name WHEN \'users\' THEN 0 WHEN \'entities\' THEN 1 ELSE 2 END',(task,user)).fetchall()
 for change in changes:
  table=change['table_name'];keys=TABLES[table];ids=json.loads(change['row_key']);where=' AND '.join('"'+v+'"=?' for v in keys)
  old=c.execute('SELECT * FROM "'+table+'" WHERE '+where,ids).fetchone();before=json.loads(change['before_row'])
  if (dict(old) if old else None)!=before:raise HTTPException(409,'The saved record changed during this action. Nothing from the AI run was applied; your newer edits are preserved.')
  if table=='entities' and before and before['updated_at']>row['created_at']:raise HTTPException(409,'This record changed after the action started. No AI changes were applied.')
 for change in changes:
  table=change['table_name'];keys=TABLES[table];ids=json.loads(change['row_key']);after=json.loads(change['after_row']) if change['after_row'] else None
  if after:
   cols=list(after);updates=[v for v in cols if v not in keys]
   c.execute('INSERT INTO "'+table+'"('+','.join('"'+v+'"' for v in cols)+') VALUES('+','.join('?' for _ in cols)+') ON CONFLICT('+','.join(keys)+') DO UPDATE SET '+','.join('"'+v+'"=excluded."'+v+'"' for v in updates),[after[v] for v in cols])
  else:c.execute('DELETE FROM "'+table+'" WHERE '+' AND '.join('"'+v+'"=?' for v in keys),ids)
  if table=='entities':
   c.execute('DELETE FROM evidence_fts WHERE id=? AND user_id=?',(ids[0],user))
   if after and after['kind']=='experience' and json.loads(after['payload']).get('confirmed'):c.execute('INSERT INTO evidence_fts VALUES(?,?,?,?)',(after['id'],user,'experience',after['payload']))
 discard(c,task)
