"""Local, versioned career RAG. Only bundled public guidance is shared.

Fetched/imported source snapshots are indexed for their owning account and chat.
All summaries in the bundled catalog are original editorial guidance, not quotations.
"""
import hashlib,json,re,ipaddress
from datetime import datetime,timezone,timedelta
from pathlib import Path
from urllib.parse import urlparse
from . import db,role_catalog
CATALOG=Path(__file__).with_name('coach_resources.json')
STOP={'the','and','for','with','that','this','want','would','like','career','your','have','from','about','into','what','should','help','plan','learn','more','skills','goal','how','can'}

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def catalog():return json.loads(CATALOG.read_text())
def version():return 'coach-knowledge-'+digest(catalog())[:16]
def safe_url(url):
 try:
  p=urlparse(url)
  if p.hostname:
   try:
    if not ipaddress.ip_address(p.hostname).is_global:return False
   except ValueError:pass
   if p.hostname.endswith(('.local','.internal','.localhost')):return False
  return p.scheme=='https' and bool(p.hostname) and not p.username and not p.password and p.port in (None,443) and p.hostname not in ('localhost','localhost.localdomain') and '.' in p.hostname
 except (ValueError,TypeError):return False

def init(c):
 c.execute('CREATE VIRTUAL TABLE IF NOT EXISTS cc_coach_knowledge USING fts5(id UNINDEXED,scope UNINDEXED,chat_id UNINDEXED,title,topics,text,source_json UNINDEXED)')
 expected=version()
 old=c.execute("SELECT source_json FROM cc_coach_knowledge WHERE scope='public' LIMIT 1").fetchone()
 if old and json.loads(old[0]).get('catalog_version')==expected:return
 c.execute("DELETE FROM cc_coach_knowledge WHERE scope='public'")
 for r in catalog():
  source={**r,'chunk_id':'guide:'+r['id'],'kind':'curated','checked_at':None,'catalog_version':expected,'text':r['text']}
  c.execute('INSERT INTO cc_coach_knowledge VALUES(?,?,?,?,?,?,?)',(source['chunk_id'],'public','',r['title'],' '.join(r['topics']),r['text'],json.dumps(source)))

def index_chat(user,chat,chunks):
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');c.execute('DELETE FROM cc_coach_knowledge WHERE scope=? AND chat_id=?',(user,chat))
  for source in chunks[:36]:
   if not safe_url(source.get('url','')) or not source.get('text'):continue
   c.execute('INSERT INTO cc_coach_knowledge VALUES(?,?,?,?,?,?,?)',(source['chunk_id'],user,chat,source['title'],' '.join(source.get('topics',[])),source['text'][:1800],json.dumps(source)))

def topics(goal,profile):
 """Public search vocabulary is a curated allowlist; never raw Profile/goals."""
 text=' '.join([goal,*[s['text'] for s in profile['sources']]])
 ranked=[]
 for row in role_catalog.CATALOG['roles']:
  score=sum(role_catalog.phrase(term,text) for term in [row['label'],*row['aliases']])
  if score:ranked.append((-score,row['label']))
 known=[]
 for r in catalog():
  for topic in r['topics']:
   if role_catalog.phrase(topic,text) and topic not in known:known.append(topic)
 return list(dict.fromkeys([v for _,v in sorted(ranked)[:4]]+known))[:6] or ['career exploration']

def retrieve(user,chat,query,limit=12):
 terms=list(dict.fromkeys(re.findall(r'[\w][\w+#.-]{1,35}',query.casefold(),re.UNICODE)))
 words=[v for v in terms if v not in STOP][:55]
 expanded=[]
 for label,aliases in role_catalog.ALIASES.items():
  if role_catalog.phrase(label,query) or any(role_catalog.phrase(v,query) for v in aliases):expanded.extend(re.findall(r'\w{2,}',label))
 match=' OR '.join('"'+v.replace('"','')+'"' for v in list(dict.fromkeys(words+expanded)))
 with db.connect() as c:
  rows=c.execute('''SELECT source_json,bm25(cc_coach_knowledge) AS score FROM cc_coach_knowledge WHERE cc_coach_knowledge MATCH ? AND (scope='public' OR (scope=? AND chat_id=?)) ORDER BY score LIMIT ?''',(match,user,chat,48)).fetchall() if match else []
  ranked=[{**json.loads(r['source_json']),'retrieval_score':round(-r['score'],5)} for r in rows]
  result=[r for r in ranked if r.get('kind')=='fetched'][:6]+[r for r in ranked if r.get('kind')=='curated'][:6]
  for r in ranked:
   if len(result)<limit and r['chunk_id'] not in {v['chunk_id'] for v in result}:result.append(r)
  # Sparse/unmatched Profiles still get explicitly general, original guidance.
  if len(result)<3:
   for r in c.execute("SELECT source_json FROM cc_coach_knowledge WHERE scope='public' AND id IN ('guide:explore','guide:practice','guide:cert-choice')"):
    source=json.loads(r[0])
    if source['chunk_id'] not in {v['chunk_id'] for v in result}:result.append({**source,'retrieval_score':0})
 for source in result:
  if source.get('kind')=='fetched':
   try:
    checked=datetime.fromisoformat(str(source.get('checked_at','')).replace('Z','+00:00'))
    if checked.tzinfo is None:checked=checked.replace(tzinfo=timezone.utc)
    source['stale']=checked<datetime.now(timezone.utc)-timedelta(days=30)
   except ValueError:source['stale']=True
 return result[:limit]

def validate_chunks(chunks):
 if not isinstance(chunks,list) or len(chunks)>36:raise ValueError()
 seen=set()
 for s in chunks:
  if not isinstance(s,dict) or not isinstance(s.get('chunk_id'),str) or s['chunk_id'] in seen or not safe_url(s.get('url','')):raise ValueError()
  if not isinstance(s.get('text'),str) or len(s['text'])>1800 or not isinstance(s.get('title'),str):raise ValueError()
  if s.get('kind') not in ('curated','fetched'):raise ValueError()
  seen.add(s['chunk_id'])
 return chunks
