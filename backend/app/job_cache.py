"""Disposable posting retention, public-source observations and protected evidence.

Public observations are ingested only by provider adapters. Account imports and
merged result records can bind to an observation, but never publish one.
"""
import asyncio,hashlib,json,re,time,math
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from fastapi import APIRouter,Depends,HTTPException
from pydantic import Field
from . import db,auth,config,storage
from .models import StrictModel
DAY=86400
FRESH=6*3600
STALE=48*3600
router=APIRouter(prefix='/api/settings/job-cache')

def init(c):
 c.execute('''CREATE TABLE IF NOT EXISTS cc_job_observations(scope TEXT,source TEXT,posting_key TEXT,verified_at REAL,deadline_at REAL,closed_at REAL,authoritative INTEGER,PRIMARY KEY(scope,source,posting_key))''')
 c.execute('CREATE INDEX IF NOT EXISTS cc_job_observation_key ON cc_job_observations(scope,posting_key)')
 c.execute('''CREATE TABLE IF NOT EXISTS cc_job_lifecycle(user_id TEXT REFERENCES users(id) ON DELETE CASCADE,job_id TEXT REFERENCES entities(id) ON DELETE CASCADE,posting_key TEXT,scope TEXT,source TEXT,verified_at REAL,deadline_at REAL,closed_at REAL,purged INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(user_id,job_id))''')
 c.execute('CREATE INDEX IF NOT EXISTS cc_job_lifecycle_key ON cc_job_lifecycle(scope,posting_key)')
 c.execute('CREATE TABLE IF NOT EXISTS cc_job_source_checks(source TEXT PRIMARY KEY,checked_at REAL,complete INTEGER)')

def hosted():return config.capabilities()['deployment']=='hosted'
def days():
 if hosted():return 30
 try:
  value=json.loads((config.DATA_DIR/'job-cache-policy.json').read_text())['retention_days']
  return value if type(value) is int and 1<=value<=365 else 30
 except (OSError,ValueError,KeyError,TypeError):return 30

def epoch(value):
 if isinstance(value,(int,float)):return float(value) if math.isfinite(value) else None
 if not value:return None
 try:
  d=datetime.fromisoformat(str(value).replace('Z','+00:00'))
  return d.replace(tzinfo=timezone.utc).timestamp() if d.tzinfo is None else d.timestamp()
 except (ValueError,TypeError,OverflowError):return None

def deadline(data):
 values=[]
 for name in ('deadline','valid_through','validThrough','expiration_date'):
  value=data.get(name)
  if not value:continue
  if re.fullmatch(r'\d{4}-\d{2}-\d{2}',str(value)):
   try:
    zone=ZoneInfo(data.get('deadline_timezone') or 'UTC')
    value=(datetime.fromisoformat(str(value))+timedelta(days=1)).replace(tzinfo=zone).timestamp()
   except (ValueError,TypeError,ZoneInfoNotFoundError):continue
  else:value=epoch(value)
  if value is not None:values.append(value)
 return min(values) if values else None

def iso(value):return datetime.fromtimestamp(value,timezone.utc).isoformat() if value is not None else None

def observe(source,rows,verified_at,*,scope='public',complete=False,authoritative=False):
 """Only source adapters call this, on successful verification, never on a cache hit."""
 from .integrations import posting_key
 if scope=='public' and not source.startswith(('greenhouse:','ashby:','lever:','usajobs:','github:','official:amazon:','official:apple:','official:capitalone:','official:intuit:')):raise ValueError('Only validated public source adapters may publish observations.')
 verified=min(float(verified_at),time.time());seen=set()
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE')
  for data in rows:
   if not data.get('url'):continue
   key=posting_key(data['url'])
   if not key:continue
   seen.add(key);closing=deadline(data)
   c.execute('''INSERT INTO cc_job_observations VALUES(?,?,?,?,?,?,?) ON CONFLICT(scope,source,posting_key) DO UPDATE SET verified_at=max(verified_at,excluded.verified_at),deadline_at=excluded.deadline_at,closed_at=CASE WHEN excluded.authoritative THEN NULL ELSE closed_at END,authoritative=max(authoritative,excluded.authoritative) WHERE excluded.verified_at>=verified_at''',(scope,source,key,verified,closing,None,int(authoritative)))
   # A community mirror cannot reopen an employer-confirmed closed position.
   c.execute('''UPDATE cc_job_lifecycle SET verified_at=max(verified_at,?),deadline_at=CASE WHEN ? THEN ? ELSE coalesce(?,deadline_at) END,closed_at=CASE WHEN ? THEN NULL ELSE closed_at END WHERE scope=? AND posting_key=? AND verified_at<=?''',(verified,int(authoritative),closing,closing,int(authoritative),scope,key,verified))
  if complete and authoritative:
   previous=c.execute('SELECT posting_key FROM cc_job_observations WHERE scope=? AND source=? AND closed_at IS NULL AND verified_at<=?',(scope,source,verified)).fetchall()
   for row in previous:
    if row['posting_key'] in seen:continue
    c.execute('UPDATE cc_job_observations SET closed_at=? WHERE scope=? AND source=? AND posting_key=?',(verified,scope,source,row['posting_key']))
    c.execute('UPDATE cc_job_lifecycle SET closed_at=? WHERE scope=? AND posting_key=? AND verified_at<=?',(verified,scope,row['posting_key'],verified))
  if scope=='public':c.execute('INSERT INTO cc_job_source_checks VALUES(?,?,?) ON CONFLICT(source) DO UPDATE SET checked_at=excluded.checked_at,complete=excluded.complete',(source,verified,int(complete)))

def bind(c,user,record):
 from .integrations import posting_key
 d=record['data'];key=posting_key(d.get('url','')) or record['id'];scope=user if d.get('_cache_scope')=='account' or any(s.get('provider') in ('adzuna','openai_web') for s in d.get('sources',[])) else 'public'
 old=c.execute('SELECT * FROM cc_job_lifecycle WHERE user_id=? AND job_id=?',(user,record['id'])).fetchone()
 observation=c.execute('SELECT * FROM cc_job_observations WHERE scope=? AND posting_key=? ORDER BY authoritative DESC,verified_at DESC LIMIT 1',(scope,key)).fetchone()
 verified=epoch(d.get('_last_verified_epoch') or d.get('last_verified_at'))
 if observation:verified=max(verified or 0,observation['verified_at'])
 if verified is None:
  created=c.execute('SELECT created_at FROM entities WHERE user_id=? AND id=?',(user,record['id'])).fetchone()
  verified=old['verified_at'] if old else epoch(d.get('snapshot_at') or d.get('first_discovered_at') or record.get('created_at') or (created['created_at'] if created else None)) or 0
 verified=min(verified,time.time());closing=deadline(d)
 if closing is None:closing=epoch(d.get('source_deadline_at')) or (old['deadline_at'] if old else None)
 if observation and observation['deadline_at'] is not None:closing=observation['deadline_at']
 closed=observation['closed_at'] if observation else old['closed_at'] if old else epoch(d.get('source_closed_at'))
 if old and verified<old['verified_at']:closing=old['deadline_at'];closed=old['closed_at']
 source=d.get('_cache_source') or d.get('origin_key','')
 c.execute('''INSERT INTO cc_job_lifecycle VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,job_id) DO UPDATE SET posting_key=excluded.posting_key,scope=excluded.scope,source=excluded.source,verified_at=max(verified_at,excluded.verified_at),deadline_at=excluded.deadline_at,closed_at=excluded.closed_at,purged=CASE WHEN ? THEN purged ELSE 0 END''',(user,record['id'],key,scope,source,verified,closing,closed,int(bool(d.get('cache_tombstone') or d.get('cache_payload_purged'))),int(bool(d.get('cache_tombstone') or d.get('cache_payload_purged')))))

def active_sql(alias='l'):
 return f"({alias}.job_id IS NULL OR ({alias}.purged=0 AND {alias}.closed_at IS NULL AND ({alias}.deadline_at IS NULL OR {alias}.deadline_at>?) AND {alias}.verified_at>?))"
def active_args(now=None):
 now=time.time() if now is None else now
 return [now,now-days()*DAY]
def lifecycle(row,now=None):
 now=time.time() if now is None else now
 verified=row['verified_at'];closing=row['deadline_at'];closed=row['closed_at'];expires=min(verified+days()*DAY,closing if closing is not None else float('inf'))
 purged=bool(row['purged']) if 'purged' in row.keys() else False
 state='closed' if closed is not None else 'expired' if purged or expires<=now else 'active'
 return {'source_deadline_at':iso(closing),'source_closed_at':iso(closed),'cache_payload_purged':purged,'last_verified_at':iso(verified) if verified else None,'expires_at':iso(min(expires,closed) if closed else expires),'lifecycle_status':state,'lifecycle_reason':'source_closed' if closed is not None else 'closing_date' if closing is not None and closing<=now else 'retention' if purged or expires<=now else '', 'cache_status':'unverified' if not verified else 'stale' if now-verified>FRESH else 'fresh','snapshot_stale':now-verified>STALE}
def decorate_records(user,records):
 with db.connect() as c:rows={r['job_id']:r for r in c.execute('SELECT * FROM cc_job_lifecycle WHERE user_id=?',(user,))}
 return [{**r,'data':{**r['data'],**lifecycle(rows[r['id']])}} if r['id'] in rows else r for r in records]
def decorate(user,record):return decorate_records(user,[record])[0]

def is_active(user,id):
 with db.connect() as c:row=c.execute('SELECT * FROM cc_job_lifecycle WHERE user_id=? AND job_id=?',(user,id)).fetchone()
 return not row or lifecycle(row)['lifecycle_status']=='active'

class Policy(StrictModel):retention_days:int=Field(ge=1,le=365,strict=True)
@router.get('')
def policy(user=Depends(auth.current)):
 return {'retention_days':days(),'freshness_hours':6,'stale_alert_cutoff_hours':48,'editable':not hosted(),'scope':'installation','shared_sources':['Greenhouse','Ashby','Lever','GitHub community listings','USAJOBS'],'private_sources':['Adzuna','AI discoveries and reviews']}
@router.put('')
def set_policy(body:Policy,user=Depends(auth.current)):
 if hosted():raise HTTPException(403,'Hosted job retention is fixed at 30 days.')
 storage.write_bytes(config.DATA_DIR/'job-cache-policy.json',json.dumps(body.model_dump()).encode())
 return policy(user)

def migrate():
 """Read only existing public source snapshots for public backfill. No imports or network."""
 with db.connect() as c:rows=c.execute('SELECT * FROM cc_public_job_snapshots').fetchall()
 for row in rows:
  if not row['source'].startswith(('greenhouse:','ashby:','lever:','usajobs:')):continue
  with db.connect() as c:existing=c.execute('SELECT 1 FROM cc_job_source_checks WHERE source=?',(row['source'],)).fetchone()
  if existing:continue
  try:payload=json.loads(row['payload'])
  except ValueError:continue
  if isinstance(payload,list):
   groups={}
   for value in payload:groups.setdefault(value.get('_last_verified_epoch',row['success_at']),[]).append(value)
   for stamp,values in groups.items():observe(row['source'],values,stamp,authoritative=not row['source'].startswith('usajobs:'))
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE')
  for row in c.execute("SELECT * FROM entities WHERE kind='job'").fetchall():
   record=db.decode(row)
   if record['data'].get('source_identity') and not c.execute('SELECT 1 FROM cc_job_lifecycle WHERE user_id=? AND job_id=?',(record['user_id'],record['id'])).fetchone():bind(c,record['user_id'],record)

def cleanup(now=None):
 """Reclaim disposable bodies, keeping reference IDs and all protected professional evidence."""
 now=time.time() if now is None else now;cutoff=now-days()*DAY;changed=0
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');protected=set()
  for row in c.execute("SELECT id,user_id,kind,payload FROM entities WHERE kind NOT IN ('job_snapshot','document','experience','usage_event')"):
   d=json.loads(row['payload']);u=row['user_id']
   if row['kind']=='job':
    if d.get('interest_state')=='saved':protected.add((u,row['id']))
    continue
   if row['kind']=='search':continue
   if d.get('job_id'):protected.add((u,d['job_id']))
   if row['kind']=='ai_job_match':
    protected.update((u,id) for id in d.get('assessments',{}));protected.update((u,id) for id in d.get('posting_versions',{}))
    if d.get('state')!='completed':
     protected.update((u,r['job_id']) for r in c.execute('SELECT job_id FROM cc_search_rows WHERE user_id=? AND search_id=?',(u,d.get('search_id',''))))
  dead=c.execute('SELECT * FROM cc_job_lifecycle WHERE purged=0 AND (closed_at IS NOT NULL OR deadline_at<=? OR verified_at<=?)',(now,cutoff)).fetchall()
  purged=set()
  for row in dead:
   identity=(row['user_id'],row['job_id'])
   if identity in protected:continue
   r=c.execute("SELECT payload FROM entities WHERE user_id=? AND id=? AND kind='job'",identity).fetchone()
   if not r:continue
   d=json.loads(r['payload']);minimal={k:d[k] for k in ('title','company','url','location','source_identity','origin_key','first_discovered_at','interest_state','interest_updated_at','deadline','valid_through') if k in d}
   minimal.update(cache_tombstone=True,last_verified_at=iso(row['verified_at']))
   c.execute('UPDATE entities SET payload=? WHERE user_id=? AND id=?',(json.dumps(minimal),*identity));c.execute('UPDATE cc_search_rows SET search_text=? WHERE user_id=? AND job_id=?',(' '.join(str(minimal.get(k,'')) for k in ('title','company','location')).casefold(),*identity))
   for ref in c.execute('SELECT DISTINCT snapshot_id FROM cc_search_rows WHERE user_id=? AND job_id=?',identity).fetchall():
    # Snapshot hashes include bodies, so a protected live job cannot share this tombstone's body accidentally.
    used=c.execute('SELECT job_id FROM cc_search_rows WHERE user_id=? AND snapshot_id=?',(identity[0],ref['snapshot_id'])).fetchall()
    if not any((identity[0],v['job_id']) in protected for v in used):c.execute('UPDATE entities SET payload=? WHERE user_id=? AND id=?',(json.dumps(minimal),identity[0],ref['snapshot_id']))
   c.execute('UPDATE cc_job_lifecycle SET purged=1 WHERE user_id=? AND job_id=?',identity);purged.add(identity);changed+=1
  if purged:
   for row in c.execute("SELECT id,user_id,payload FROM entities WHERE kind='search'").fetchall():
    d=json.loads(row['payload']);dirty=False
    for ref in d.get('jobs',[]):
     if (row['user_id'],ref['id']) in purged and ref.get('data',{}).get('description'):
      ref['data']={k:ref['data'].get(k,'') for k in ('title','company')};dirty=True
    if dirty:c.execute('UPDATE entities SET payload=? WHERE id=? AND user_id=?',(json.dumps(d),row['id'],row['user_id']))
   for task in c.execute("SELECT id,user_id,result FROM tasks WHERE result IS NOT NULL").fetchall():
    value=json.loads(task['result']);dirty=False
    def strip(value):
     nonlocal dirty
     if isinstance(value,dict):
      if (task['user_id'],value.get('id')) in purged and isinstance(value.get('data'),dict):
       value['data']={k:value['data'].get(k,'') for k in ('title','company')};dirty=True
      else:
       for child in value.values():strip(child)
     elif isinstance(value,list):
      for child in value:strip(child)
    strip(value)
    if dirty:c.execute('UPDATE tasks SET result=? WHERE id=? AND user_id=?',(json.dumps(value),task['id'],task['user_id']))
  # Truly unreferenced immutable cache versions have no remaining evidence consumer.
  c.execute("DELETE FROM entities WHERE kind='job_snapshot' AND NOT EXISTS(SELECT 1 FROM cc_search_rows r WHERE r.snapshot_id=entities.id) AND NOT EXISTS(SELECT 1 FROM entities s,json_each(s.payload,'$.jobs') ref WHERE s.kind='search' AND s.user_id=entities.user_id AND json_extract(ref.value,'$.snapshot_id')=entities.id)")
  for row in c.execute('SELECT * FROM cc_public_job_snapshots').fetchall():
   if row['success_at']<=cutoff:
    c.execute('DELETE FROM cc_public_job_snapshots WHERE source=?',(row['source'],));continue
   payload=json.loads(row['payload'])
   values=payload if isinstance(payload,list) else payload.get('jobs',[]) if isinstance(payload,dict) else []
   remaining=[v for v in values if deadline(v) is None or deadline(v)>now]
   if len(values)!=len(remaining):
    payload=remaining if isinstance(payload,list) else {**payload,'jobs':remaining}
    raw=json.dumps(payload,separators=(',',':'));c.execute('UPDATE cc_public_job_snapshots SET payload=?,revision=? WHERE source=?',(raw,hashlib.sha256(raw.encode()).hexdigest()[:20],row['source']))
 return {'purged_posting_bodies':changed}

async def maintain():
 while True:
  await asyncio.sleep(3600)
  try:await asyncio.to_thread(cleanup)
  except asyncio.CancelledError:raise
  except Exception:pass # Read paths always enforce expiry even when cleanup is delayed.
