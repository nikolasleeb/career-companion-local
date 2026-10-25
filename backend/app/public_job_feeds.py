"""Keyless public snapshots only. Never pass account credentials to this cache.

Employer catalog: CC BY 4.0 candidate directory attributed in JSON.
Community metadata: open-jobs-data; employer postings retain employer rights.
"""
import asyncio,copy,hashlib,json,time
from collections import defaultdict,deque
from pathlib import Path
from . import db
from .network import ServiceError

CATALOG=json.loads(Path(__file__).with_name('employer_catalog.json').read_text())
REVISION=CATALOG['revision']
GITHUB_BASE='https://raw.githubusercontent.com/ConorsCode/open-jobs-data/main/'
GITHUB_REPOSITORY='https://github.com/ConorsCode/open-jobs-data'
TTL=6*3600
STALE=48*3600
_locks={}

def init(c):
    c.execute('''CREATE TABLE IF NOT EXISTS cc_public_job_snapshots(
      source TEXT PRIMARY KEY,payload TEXT NOT NULL,revision TEXT NOT NULL,
      success_at REAL NOT NULL,attempted_at REAL NOT NULL,error TEXT NOT NULL)''')

def board_key(b):return b['provider']+':'+b['board']+(':'+b['region'] if b.get('region')=='eu' else '')
def catalog_boards(user):
    # Account additions override the label but do not duplicate a public board.
    boards={board_key(b):b for b in CATALOG['employers']}
    for row in db.list_entities(user,'board'):boards[board_key(row['data'])]=row['data']
    return list(boards.values())

def identity():
    with db.connect() as c:rows=c.execute('SELECT source,revision,success_at FROM cc_public_job_snapshots ORDER BY source').fetchall()
    return {'catalog':REVISION,'snapshots':hashlib.sha256(json.dumps([tuple(r) for r in rows]).encode()).hexdigest()[:20]}

def listing(user):
    return [{'key':board_key(b),'company':b['company'],'provider':b['provider'],'career_url':b.get('career_url',''),'curated':any(board_key(b)==board_key(v) for v in CATALOG['employers'])} for b in catalog_boards(user)]

async def cached(source,load,*,refresh=False):
    # Locks are loop-scoped: test clients and reloads can create different loops.
    lock=_locks.setdefault((id(asyncio.get_running_loop()),str(db.config.DB_PATH),source),asyncio.Lock())
    async with lock:
        with db.connect() as c:row=c.execute('SELECT * FROM cc_public_job_snapshots WHERE source=?',(source,)).fetchone()
        now=time.time()
        if row and not refresh and now-row['success_at']<TTL:
            data=json.loads(row['payload']);return data,metadata(row,now,cached=True)
        # Coalesce refresh clicks/concurrent accounts and failed-source retry storms.
        if row and now-row['attempted_at']<60:
            return json.loads(row['payload']),metadata(row,now,cached=True)
        try:
            value=await load()
            raw=json.dumps(value,separators=(',',':'));revision=hashlib.sha256(raw.encode()).hexdigest()[:20]
            with db.connect() as c:c.execute('INSERT INTO cc_public_job_snapshots VALUES(?,?,?,?,?,?) ON CONFLICT(source) DO UPDATE SET payload=excluded.payload,revision=excluded.revision,success_at=excluded.success_at,attempted_at=excluded.attempted_at,error=excluded.error',(source,raw,revision,now,now,''))
            return value,{'cached':False,'last_success':now,'stale':False,'revision':revision,'error':''}
        except (ServiceError,asyncio.TimeoutError,ValueError,TypeError,KeyError):
            if not row:raise ServiceError('Public feed unavailable. Other sources are retained.') from None
            with db.connect() as c:c.execute('UPDATE cc_public_job_snapshots SET attempted_at=?,error=? WHERE source=?',(now,'Refresh failed; showing the last successful snapshot.',source))
            return json.loads(row['payload']),{**metadata(row,now,cached=True),'error':'Refresh failed; showing the last successful snapshot.'}

def metadata(row,now,*,cached):
    return {'cached':cached,'last_success':row['success_at'],'stale':now-row['success_at']>STALE,'revision':row['revision'],'error':row['error']}

async def employer(board,*,refresh=False):
    from . import integrations as x
    key=board_key(board)
    async def load():return await x.board_jobs(board,None)
    rows,meta=await cached(key,load,refresh=refresh)
    return [{**copy.deepcopy(v),'company':board['company'],'snapshot_at':meta['last_success'],'snapshot_revision':meta['revision'],'snapshot_stale':meta['stale']} for v in rows],meta

async def community(*,refresh=False,queries=None):
    from . import integrations as x
    async def load():
        summary=await x.fetch_json(GITHUB_BASE+'data/summary.json')
        items=await x.fetch_json(GITHUB_BASE+'data/jobs.json',max_bytes=64*1024*1024)
        if not isinstance(items,list) or len(items)>150000:raise ServiceError('Community snapshot format is unsupported.')
        stamp=summary.get('generatedAt')
        if not x.parse_date(stamp):raise ServiceError('Community snapshot timestamp is missing.')
        return {'generated_at':stamp,'jobs':items}
    payload,meta=await cached('github:open-jobs-data',load,refresh=refresh)
    snapshot=x.parse_date(payload['generated_at'])
    stale=meta['stale'] or time.time()-snapshot.timestamp()>STALE
    result=[]
    for v in payload['jobs']:
        if queries is not None and not x.matches_title(v.get('title',''),queries):continue
        url=x.canonical_url(v.get('applyUrl',''))
        if not url or not v.get('title') or not v.get('company'):continue
        locations=v.get('locations') or []
        if not isinstance(locations,list):continue
        result.append(x.normalize_job('github',v['title'],v['company'],'; '.join(str(l) for l in locations),'',url,
          source_identity='github:'+str(v.get('platform',''))+':'+str(v['company'])+':'+str(v.get('jobId') or url),origin_key='github:open-jobs-data',
          employment_type=v.get('employmentType') or '',published_at=v.get('postedAt'),publication_source='Community metadata postedAt (verify employer)',
          description_incomplete=True,metadata_only=True,community_repository=GITHUB_REPOSITORY,community_scraped_at=v.get('scrapedAt'),
          snapshot_at=payload['generated_at'],snapshot_revision=meta['revision'],snapshot_stale=stale,
          observations=['Public community metadata, not employer-verified requirements. Remote labels may be inferred. Employer retains rights to its posting.']))
    return result,{**meta,'stale':stale,'snapshot_at':payload['generated_at']}

def balanced(jobs,limit=500):
    """Round-robin source then employer, so a large board cannot consume the cap."""
    sources=defaultdict(lambda:defaultdict(deque))
    for job in jobs:sources[(job.get('sources') or [{}])[0].get('provider','unknown')][job.get('company','')].append(job)
    queues={s:deque(deque(v) for _,v in sorted(employers.items())) for s,employers in sorted(sources.items())}
    result=[]
    while queues and len(result)<limit:
        for source in list(queues):
            group=queues[source];employer=group.popleft();result.append(employer.popleft())
            if employer:group.append(employer)
            if not group:del queues[source]
            if len(result)==limit:break
    return result
