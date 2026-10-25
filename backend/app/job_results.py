"""Account-owned immutable result versions and server-side paging. No provider calls."""
import hashlib,json,math,re
from fastapi import APIRouter,Depends,HTTPException,Query
from . import db,auth,onboarding,job_cache
router=APIRouter(prefix='/api/job-search')
def init(c):
 c.execute('''CREATE TABLE IF NOT EXISTS cc_search_rows(
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 search_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
 job_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
 snapshot_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
 ordinal INTEGER NOT NULL,status TEXT NOT NULL,matching_location TEXT NOT NULL,
 reasons TEXT NOT NULL,search_text TEXT NOT NULL,PRIMARY KEY(search_id,job_id))''')
 c.execute('CREATE INDEX IF NOT EXISTS cc_search_rows_scope ON cc_search_rows(user_id,search_id,status,ordinal)')
def owner(user=Depends(auth.current)):
 onboarding.require_complete(user['id']);return user['id']
def owned(user,id,kind):
 row=db.get(user,id,kind)
 if not row:raise HTTPException(404,'Search record not found.')
 return row

def save_search(user,result,entity_id=None):
 from .resume_conversation import write
 search_id=entity_id or db.uid();refs=[]
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE')
  entries=[]
  for ordinal,r in enumerate(result.get('jobs',[])):
   job_cache.bind(c,user,r)
   job=r['data'];payload={k:v for k,v in job.items() if k not in ('interest_state','interest_updated_at','matching_location','filter_reasons','hard_filter_status','review_reasons','text_overlap')}
   raw=json.dumps(payload,sort_keys=True,ensure_ascii=False)
   version=hashlib.sha256((user+':job-version:'+raw).encode()).hexdigest()[:32]
   if not c.execute("SELECT 1 FROM entities WHERE id=? AND user_id=? AND coalesce(json_extract(payload,'$.cache_tombstone'),0)=0",(version,user)).fetchone():write(c,user,'job_snapshot',payload,version)
   refs.append({'id':r['id'],'snapshot_id':version,'data':{'title':job['title'],'company':job.get('company','')}})
   entries.append((user,search_id,r['id'],version,ordinal,job.get('hard_filter_status','uncertain' if 'Requested location needs review' in job.get('review_reasons',[]) else 'matches'),job.get('matching_location') or job.get('location',''),json.dumps(job.get('filter_reasons',[])), ' '.join(str(job.get(k) or '') for k in ('title','company','location','matching_location','description')).casefold()))
  write(c,user,'search',{**result,'jobs':refs,'result_schema':2,'truncated':False,'retained_matches':len(refs),'total_matches':len(refs)},search_id)
  c.execute('DELETE FROM cc_search_rows WHERE user_id=? AND search_id=?',(user,search_id))
  c.executemany('INSERT INTO cc_search_rows VALUES(?,?,?,?,?,?,?,?,?)',entries)
 return db.get(user,search_id,'search')

def ensure(user,id):
 search=owned(user,id,'search')
 with db.connect() as c:count=c.execute('SELECT count(*) FROM cc_search_rows WHERE user_id=? AND search_id=?',(user,id)).fetchone()[0]
 if not count and search['data'].get('jobs'):
  records=[];seen=set()
  from .models import SearchRequest
  from . import job_search,integrations
  try:query=SearchRequest.model_validate(search['data'].get('query',{}))
  except ValueError:query=None
  for ref in search['data']['jobs']:
   current=db.get(user,ref['id'],'job')
   if current:
    snapshot=db.get(user,ref.get('snapshot_id',''),'job_snapshot')
    if snapshot:current={**current,'data':snapshot['data']}
    elif ref.get('data',{}).get('description'):current={**current,'data':ref['data']}
    current={**current,'data':dict(current['data'])}
    if query and not job_search.review({**current['data'],'deadline':None,'valid_through':None,'validThrough':None,'expiration_date':None,'cache_tombstone':False},query):continue
    key=integrations.posting_key(current['data'].get('url','')) or current['id']
    if key in seen:continue
    seen.add(key);records.append(current)
  # Recheck retained membership locally. Known conflicts are removed; no network refill.
  old=search['data'];saved=save_search(user,{**old,'jobs':records},id)
  if old.get('truncated'):
   db.save(user,'search',{**saved['data'],'truncated':True,'total_matches':old.get('total_matches',len(records))},id)
 return owned(user,id,'search')

def all_rows(user,id):
 ensure(user,id)
 with db.connect() as c:
  rows=c.execute('''SELECT r.*,e.payload,e.created_at,e.updated_at,j.payload AS current_payload,l.verified_at,l.deadline_at,l.closed_at,l.purged FROM cc_search_rows r
  JOIN entities e ON e.id=r.snapshot_id AND e.user_id=r.user_id
  JOIN entities j ON j.id=r.job_id AND j.user_id=r.user_id LEFT JOIN cc_job_lifecycle l ON l.job_id=r.job_id AND l.user_id=r.user_id WHERE r.user_id=? AND r.search_id=? ORDER BY r.ordinal''',(user,id)).fetchall()
 return [decode(row) for row in rows if row['verified_at'] is None or job_cache.lifecycle(row)['lifecycle_status']=='active']
def decode(row,details=True):
 d=json.loads(row['payload']);current=json.loads(row['current_payload'])
 d.update(matching_location=row['matching_location'],hard_filter_status=row['status'],filter_reasons=json.loads(row['reasons']))
 for field in ('interest_state','interest_updated_at'):
  if field in current:d[field]=current[field]
 if row['verified_at'] is not None:d.update(job_cache.lifecycle(row))
 if not details:d.pop('description',None)
 return {'id':row['job_id'],'kind':'job','created_at':row['created_at'],'updated_at':row['updated_at'],'snapshot_id':row['snapshot_id'],'data':d}

@router.get('/searches/{id}/results')
def page(id:str,q:str=Query(default='',max_length=200),view:str=Query(default='matches',pattern='^(matches|review|all|saved|dismissed|archived)$'),sort:str=Query(default='balanced',pattern='^(balanced|recent|best)$'),page:int=Query(default=1,ge=1),page_size:int=Query(default=25),match_id:str='',user=Depends(owner)):
 if page_size not in (25,50,100):raise HTTPException(422,'Choose 25, 50 or 100 jobs per page.')
 if id=='saved':
  for r in db.list_entities(user,'search'):ensure(user,r['id'])
 search=ensure(user,id) if id!='saved' else None
 args=[user];where=['r.user_id=?']
 if id!='saved':where.append('r.search_id=?');args.append(id)
 else:where.append("json_extract(j.payload,'$.interest_state')='saved'")
 for term in re.findall(r'\S+',q.casefold()):where.append("r.search_text LIKE ? ESCAPE '\\'");args.append('%'+term.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%')
 if view=='dismissed':where.append("json_extract(j.payload,'$.interest_state')='dismissed'")
 else:where.append("coalesce(json_extract(j.payload,'$.interest_state'),'none')!='dismissed'")
 base=' FROM cc_search_rows r JOIN entities e ON e.id=r.snapshot_id AND e.user_id=r.user_id JOIN entities j ON j.id=r.job_id AND j.user_id=r.user_id LEFT JOIN cc_job_lifecycle l ON l.job_id=r.job_id AND l.user_id=r.user_id WHERE '+' AND '.join(where)
 # A saved job can belong to many snapshots; choose its newest snapshot once.
 if id=='saved':base+=" AND r.rowid=(SELECT max(x.rowid) FROM cc_search_rows x WHERE x.user_id=r.user_id AND x.job_id=r.job_id)"
 with db.connect() as c:
  archived=c.execute('SELECT count(*)'+base+' AND NOT '+job_cache.active_sql(),args+job_cache.active_args()).fetchone()[0]
  counts={v['status']:v['n'] for v in c.execute('SELECT r.status,count(*) AS n'+base+' AND '+job_cache.active_sql()+' GROUP BY r.status',args+job_cache.active_args())}
  base+=' AND '+('NOT ' if view=='archived' else '')+job_cache.active_sql();args+=job_cache.active_args()
  extra=[]
  if view in ('matches','review'):extra.append("r.status='"+('matches' if view=='matches' else 'uncertain')+"'")
  if view=='saved':extra.append("json_extract(j.payload,'$.interest_state')='saved'")
  sql=base+(' AND '+' AND '.join(extra) if extra else '')
  total=c.execute('SELECT count(*)'+sql,args).fetchone()[0];pages=max(1,math.ceil(total/page_size));current=min(page,pages)
  order="coalesce(json_extract(e.payload,'$.published_at'),json_extract(e.payload,'$.source_added_at'),'') DESC,r.ordinal" if sort=='recent' else 'r.ordinal'
  assessments={};match=None
  if match_id:
   match=owned(user,match_id,'ai_job_match')
   if id!=match['data']['search_id']:raise HTTPException(409,'Choose a review for this search.')
   assessments=match['data'].get('assessments',{})
  if sort=='best' and assessments:
   # Ordered ID list only; large descriptions stay in SQLite until this page is selected.
   ids=[r['job_id'] for r in c.execute('SELECT r.job_id'+sql+' ORDER BY r.ordinal',args)]
   weights={'strong':0,'possible':1,'stretch':2,'insufficient_information':3}
   ids.sort(key=lambda k:(weights.get(assessments.get(k,{}).get('fit'),4),assessments.get(k,{}).get('scope')!='detailed'))
   selected=ids[(current-1)*page_size:current*page_size]
   rows=[c.execute('SELECT r.*,e.payload,e.created_at,e.updated_at,j.payload AS current_payload,l.verified_at,l.deadline_at,l.closed_at,l.purged'+sql+' AND r.job_id=?',args+[k]).fetchone() for k in selected]
  else:rows=c.execute('SELECT r.*,e.payload,e.created_at,e.updated_at,j.payload AS current_payload,l.verified_at,l.deadline_at,l.closed_at,l.purged'+sql+' ORDER BY '+order+' LIMIT ? OFFSET ?',args+[page_size,(current-1)*page_size]).fetchall()
 result=[decode(r,details=False) for r in rows]
 for r in result:
  if r['id'] in assessments:r['assessment']=assessments[r['id']]
 return {'jobs':result,'total':total,'counts':{'matches':counts.get('matches',0),'review':counts.get('uncertain',0),'archived':archived},'page':current,'pages':pages,'page_size':page_size,'legacy_truncated':bool(search and search['data'].get('truncated'))}

@router.get('/searches/{id}/jobs/{job_id}')
def detail(id:str,job_id:str,user=Depends(owner)):
 if id!='saved':ensure(user,id)
 with db.connect() as c:row=c.execute('''SELECT r.*,e.payload,e.created_at,e.updated_at,j.payload AS current_payload,l.verified_at,l.deadline_at,l.closed_at,l.purged FROM cc_search_rows r JOIN entities e ON e.id=r.snapshot_id AND e.user_id=r.user_id JOIN entities j ON j.id=r.job_id AND j.user_id=r.user_id LEFT JOIN cc_job_lifecycle l ON l.job_id=r.job_id AND l.user_id=r.user_id WHERE r.user_id=? AND (r.search_id=? OR ?='saved') AND r.job_id=? ORDER BY r.rowid DESC LIMIT 1''',(user,id,id,job_id)).fetchone()
 if not row:raise HTTPException(404,'Job not found in this search.')
 return decode(row)

@router.get('/alerts/{day}/jobs')
def alert_jobs(day:str,page:int=Query(default=1,ge=1),user=Depends(owner)):
 """Lazy notification-history summaries; never send full posting text with the workspace."""
 with db.connect() as c:row=c.execute('SELECT result FROM cc_job_alert_runs WHERE user_id=? AND day=?',(user,day)).fetchone()
 if not row:raise HTTPException(404,'Daily check not found.')
 ids=list(dict.fromkeys(json.loads(row['result'] or '{}').get('new_jobs',[])));pages=max(1,math.ceil(len(ids)/25));page=min(page,pages);jobs=[]
 for id in ids[(page-1)*25:page*25]:
  r=db.get(user,id,'job')
  if r:jobs.append({'id':id,'data':{k:r['data'].get(k,'') for k in ('title','company','url')}})
 return {'jobs':jobs,'page':page,'pages':pages,'total':len(ids)}


def public_search(user,record):
 """Preserve stored history while removing expired members from active API responses."""
 with db.connect() as c:
  inactive={r['job_id'] for r in c.execute('SELECT l.job_id FROM cc_job_lifecycle l WHERE l.user_id=? AND NOT '+job_cache.active_sql(),[user,*job_cache.active_args()])}
 data=record['data'];members=data.get('jobs',[]);active=[r for r in members if r['id'] not in inactive]
 return {**record,'data':{**data,'jobs':active,'active_count':len(active),'archived_count':len(members)-len(active)}}
