"""Discipline-wide learning resources and conservative practice topics."""
import json,re,copy
from fastapi import APIRouter,Depends,HTTPException,Query
from . import auth,db,config,career_goals,coach_knowledge,role_catalog,learning_topics,career_evidence,job_ai,skill_catalog
router=APIRouter(prefix='/api/skills')
BLOCK=re.compile(r'\b(?:bachelor|master.?s|doctorate|ph\.?d|degree|gpa|academic success|professional success|eligible|citizen|sponsor|visa|vaccin|disabil|veteran|authori[sz]|background check|criminal|drug test|years? of|\d+\+? years|licen[sc]ed|required license)\b',re.I)
FIELDS={'Tech & Data':['python','sql','stats','cloud','microsoft','it','software','data-engineering'],'Business & Consulting':['consulting','marketing','accounting','finance','operations','cfa','cpa','marketing-cert','hr-cert','google-cert'],'Engineering':['engineering','engineering-license','cad','quality-cert'],'Health & Medical':['nursing','public-health','clinical','health-admin','nursing-cert','lab-cert'],'Education & Public Service':['teaching','public-service'],'Arts & Communication':['writing','design','journalism'],'Science & Research':['science','research-methods','environment']}
def learnable(value):return bool(learning_topics.clean([str(value)])) and not BLOCK.search(str(value))
def library():
 rows=json.loads((config.CONTENT_DIR/'resources.json').read_text());urls={r['url'] for r in rows}
 for r in rows:r.setdefault('field','Tech & Data');r.setdefault('topics',[r['skill']])
 for r in coach_knowledge.catalog():
  if r['url'] in urls or not coach_knowledge.safe_url(r['url']):continue
  field=next((k for k,v in FIELDS.items() if r['id'] in v),'All fields')
  rows.append({'id':r['id'],'title':r['title'],'skill':r['topics'][0],'topics':r['topics'],'field':field,'description':r.get('description',r['text']),'activity':'Choose one relevant topic, practice it on a fictional or permitted example, and describe what you learned.','url':r['url'],'access':'Official/public guidance; verify provider access, costs and prerequisites.'});urls.add(r['url'])
 for row in rows:
  row['learning_topics']=learning_topics.RESOURCE_TOPICS.get(row['id'],[])
  row['resource_type']='career_support' if row['id'] in ('practice','networking','public-service','research-methods') else 'credential_directory' if row['id'] in ('cert-choice','it','operations','engineering-license','cfa','cpa','marketing-cert','nursing-cert','lab-cert','quality-cert','hr-cert','google-cert') else 'occupation_reference' if row['id'] in ('explore','consulting','marketing','accounting','finance','engineering','nursing','health-admin','teaching','journalism','science','environment') else 'learning'
 # Preserve legacy IDs when a source page already exists, while using reviewed metadata.
 def urlkey(url):
  from urllib.parse import urlsplit
  p=urlsplit(url);return (p.hostname or '').removeprefix('www.')+p.path.rstrip('/')
 by_url={urlkey(r['url']):r for r in rows}
 for resource in skill_catalog.data()['resources']:
  old=by_url.get(urlkey(resource['url'])) or next((r for r in rows if r['id']==resource['id']),None)
  if old:
   identity=old['id'];topics=list(dict.fromkeys([*old.get('learning_topics',[]),*resource.get('learning_topics',[])]));old.update(copy.deepcopy(resource));old['id']=identity;old['learning_topics']=topics
  else:
   item=copy.deepcopy(resource);rows.append(item);by_url[urlkey(item['url'])]=item
 for row in rows:
  labels=list(row.get('learning_topics',[]))
  row['topic_ids']=selected_ids(labels)
  row['learning_topics']=learning_topics.labels(labels)
  row.setdefault('provider',__import__('urllib.parse',fromlist=['urlsplit']).urlsplit(row['url']).hostname)
  row.setdefault('format','catalog' if row['resource_type']!='learning' else 'documentation')
  row.setdefault('access_kind','unknown');row.setdefault('level','unspecified');row.setdefault('reviewed_at','')
  # Existing platform courses have explicit access descriptions, even when a bulk checker was blocked.
  if row['id'] in ('codecademy-python','codecademy-sql','datacamp-python','datacamp-sql'):
   row.update(provider='DataCamp' if row['id'].startswith('datacamp') else 'Codecademy',format='course',access_kind='freemium')
  if row['id']=='sql_lemur':row.update(provider='DataLemur',format='practice',access_kind='freemium')
 return rows
@router.get('/options')
def options(job_id:str='',field:str='All',include_resources:bool=True,include_related:bool=False,user=Depends(auth.current)):
 return _options(job_id,field,include_resources,user,include_related=include_related)

def _options(job_id,field,include_resources,user,all_suggestions=False,include_related=False):
 from . import career_explorer
 if field!='All' and field not in FIELDS:raise HTTPException(422,'Choose a field from the list.')
 job=db.get(user['id'],job_id,'job') if job_id else None
 if job_id and not job:raise HTTPException(404,'Job not found.')
 rows=library();available={learning_topics.key(t) for row in rows if field=='All' or row['field'] in (field,'All fields') for t in row['learning_topics']};found={}
 def add(label,source,priority,importance=0):
  if not learnable(label):return
  k=learning_topics.key(label)
  if field!='All' and k not in available:return
  if k not in found:found[k]={'id':k,'label':learning_topics.labels([label])[0],'sources':[],'rank':(priority,0 if k in available else 1,-importance,k)}
  if source not in found[k]['sources']:found[k]['sources'].append(source)
  found[k]['rank']=min(found[k]['rank'],(priority,0 if k in available else 1,-importance,k))
 if job:
  text=job_ai.clean(re.sub(r'(?<=[.!?])\s+', '\n', ' '.join(str(job['data'].get(k) or '') for k in ('title','description'))))
  for label in learning_topics.mentions(text):add(label,{'kind':'posting','label':'Listed in this posting','record_id':job['id']},0)
  analysis=next((r for r in db.list_entities(user['id'],'analysis') if r['data'].get('job_id')==job_id),None)
  for requirement in (analysis or {}).get('data',{}).get('requirements',[]):
   keyword=job_ai.clean(requirement.get('keyword',''))
   if role_catalog.phrase(keyword,text):
    for label in learning_topics.mentions(keyword):add(label,{'kind':'posting','label':'Listed in this posting','record_id':job['id']},0)
 goals=career_goals.read(user['id'])
 for goal in goals['items']:
  text=job_ai.clean(goal['text'])
  for label in learning_topics.mentions(text):add(label,{'kind':'goal','label':'From your Career Goals','record_id':goal['id']},1)
  code=(goal.get('occupation') or {}).get('code')
  if not code:
   # Resolve only an exact published title or established alternate title.
   matches=[c for c,o in career_explorer.OCCUPATIONS.items() if text.casefold() in {v.casefold() for v in [o['title'],*o['titles']]}]
   code=matches[0] if len(matches)==1 else None
  if code in career_explorer.OCCUPATIONS:
   occupation=career_explorer.OCCUPATIONS[code]
   for item in occupation['skills']+occupation['technologies']:
    add(item['name'],{'kind':'occupation','label':'Used in '+occupation['title'],'record_id':goal['id'],'occupation_code':code},1,item.get('importance',0))
 for record in db.list_entities(user['id'],'experience'):
  if not record['data'].get('confirmed'):continue
  for item in record['data'].get('skill_items',[]):
   label=job_ai.clean(item.get('name',''))
   if label:add(label,{'kind':'profile','label':'In your Profile','record_id':record['id']},2)
 direct=sorted(found.values(),key=lambda v:v['rank']);near=[]
 if include_related:
  learning={id for r in rows if r['resource_type']=='learning' for id in r['topic_ids']}
  direct=[v for v in direct if v['id'] in learning]
  related={}
  for item in direct:
   for id in skill_catalog.index().get(item['id'],{}).get('related',[]):
    topic=skill_catalog.index()[id]
    if id in found or id not in learning or field!='All' and topic['field']!=field:continue
    entry=related.setdefault(id,{'id':id,'label':topic['label'],'sources':[],'rank':(3,*item['rank'],topic['label'].casefold())})
    for source in item['sources']:
     reason={'kind':'related','origin_kind':source['kind'],'label':'Related to '+item['label'],'topic_id':item['id'],'record_id':source.get('record_id','')}
     if reason not in entry['sources']:entry['sources'].append(reason)
  near=sorted(related.values(),key=lambda v:v['rank'])
 suggestions=direct+near
 if not all_suggestions:
  chosen=direct[:7]+near[:3] if near else direct[:10]
  suggestions=chosen+direct[len(direct[:7]):len(direct[:7])+max(0,10-len(chosen))] if near else chosen
 for value in suggestions:value.pop('rank',None)
 return {'resources':rows if include_resources else [],'groups':skill_catalog.data()['groups'],'catalog_version':skill_catalog.data()['version'],'fields':list(FIELDS),'suggested_topics':suggestions,'suggestions':[v['label'] for v in suggestions],'basis':'Choose skills to practice or explore. Sources explain why a topic is shown; none is a confirmed weakness.','topic_catalog':[{'id':k,'label':v['label'],'aliases':sorted(v['aliases'])} for k,v in learning_topics.vocabulary().items()]}

@router.get('/plan-link')
def plan_link(plan_id:str,milestone_id:str,user=Depends(auth.current)):
 from . import plan_progress
 plan=plan_progress.owned(user['id'],plan_id,'coach_plan')
 action=next((a for a in plan['data']['actions'] if a['id']==milestone_id),None)
 if not action:raise HTTPException(404,'Milestone not found in this plan.')
 return {'plan_id':plan_id,'chat_id':plan['data']['chat_id'],'milestone_id':milestone_id,'title':action['title'],'learning_topics':learning_topics.milestone(action)}


def selected_ids(values):return list(dict.fromkeys(skill_catalog.resolve(v) or learning_topics.key(v) for v in values if v.strip()))
def topic_sources(user,job_id='',include_related=False):
 return {row['id']:row for row in _options(job_id,'All',False,user,True,include_related)['suggested_topics']}

def candidates(topics,limit=24):
 """Round-robin relevant metadata only; the full library never goes to the provider."""
 ids=selected_ids(topics);rows=[r for r in library() if r['resource_type']=='learning'];buckets=[]
 for id in ids:
  direct=[r for r in rows if id in r['topic_ids']]
  related=set(skill_catalog.index().get(id,{}).get('related',[]))
  bucket=direct or [r for r in rows if related.intersection(r['topic_ids'])]
  buckets.append(sorted(bucket,key=lambda r:(r['provider'].casefold(),r['title'].casefold(),r['id'])))
 result=[];seen=set()
 for position in range(max((len(b) for b in buckets),default=0)):
  for bucket in buckets:
   if position<len(bucket) and bucket[position]['id'] not in seen:
    item=bucket[position];seen.add(item['id'])
    result.append({k:item[k] for k in ('id','title','provider','url','description','learning_topics','access','level','format','field','resource_type','access_kind','reviewed_at')})
    if len(result)==limit:return result
 return result

@router.get('/topics')
def browse_topics(q:str=Query('',max_length=150),field:str='All',group:str='',source:str='all',sort:str='recommended',job_id:str='',offset:int=Query(0,ge=0,le=10000),limit:int=Query(24,ge=1,le=24),user=Depends(auth.current)):
 if field!='All' and field not in FIELDS or group and group not in {g['id'] for g in skill_catalog.data()['groups']} or source not in ('all','profile','goal','posting') or sort not in ('recommended','title','resources'):raise HTTPException(422,'Choose valid skill filters.')
 recommendations=topic_sources(user,job_id);rank={k:i for i,k in enumerate(recommendations)};counts={}
 for r in library():
  if r['resource_type']=='learning':
   for id in r['topic_ids']:counts[id]=counts.get(id,0)+1
 rows=[]
 for topic in skill_catalog.data()['skills']:
  if field!='All' and field not in [topic['field'],*topic.get('secondary_fields',[])]:continue
  if group and group not in [topic['group'],*topic.get('secondary_groups',[])]:continue
  if q and not all(term in ' '.join([topic['label'],*topic.get('aliases',[])]).casefold() for term in q.casefold().split()):continue
  sources=recommendations.get(topic['id'],{}).get('sources',[])
  if source!='all' and not any(s['kind']==source or source=='goal' and s['kind']=='occupation' for s in sources):continue
  rows.append({**topic,'resource_count':counts.get(topic['id'],0),'sources':sources})
 if sort=='resources':rows.sort(key=lambda t:(-t['resource_count'],t['label'].casefold(),t['id']))
 elif sort=='recommended':rows.sort(key=lambda t:(rank.get(t['id'],10000),t['label'].casefold(),t['id']))
 else:rows.sort(key=lambda t:(t['label'].casefold(),t['id']))
 groups=[{**g,'count':sum(g['id']==r['group'] for r in rows)} for g in skill_catalog.data()['groups']]
 return {'topics':rows[offset:offset+limit],'total':len(rows),'groups':groups,'offset':offset,'limit':limit,'version':skill_catalog.data()['version']}

def display_resource(row):
 """Presentation metadata only; published titles, IDs, URLs and snapshots stay intact."""
 row=dict(row);title=row['title'];provider=row['provider']
 for prefix in (provider+' — ',provider+' - '):
  if title.casefold().startswith(prefix.casefold()):title=title[len(prefix):]
 title=re.sub(r'^PostgreSQL:\s*Documentation:\s*[\d.]+:\s*(?:[\d.]+\.?\s*)?', '',title,flags=re.I)
 title=re.sub(r'\s*[—–-]\s*Python [\d.]+ documentation$', '',title,flags=re.I)
 title=re.sub(r'^(?:chapter|section|part)\s+(?:\d+(?:\.\d+)*|[IVXLCDM]+)\s*[.:—–-]?\s+', '',title,flags=re.I)
 title=re.sub(r'^\d+(?:\.\d+)*[.:]?\s+','',title).lstrip(' :')
 title=re.sub(r'(?:\s+[¶#§🔗]+|[¶🔗])+$','',title).strip()
 if title.casefold() in {'getting started','quick start','introduction','overview','tutorial','user guide','welcome'}:
  topic=next(iter(row.get('learning_topics',[])), '')
  if topic and topic.casefold() not in title.casefold():title=topic+' — '+title
 row['display_title']=title or row['title']
 return row

@router.get('/resources')
def browse_resources(topics:str=Query('',max_length=5000),q:str=Query('',max_length=150),field:str='All',provider:str='',format:str='',access:str='',level:str='',sort:str='relevance',kind:str='learning',offset:int=Query(0,ge=0,le=10000),limit:int=Query(12,ge=1,le=24),job_id:str='',group:str='',source:str='',
 fields:list[str]|None=Query(None),groups:list[str]|None=Query(None),providers:list[str]|None=Query(None),formats:list[str]|None=Query(None),accesses:list[str]|None=Query(None),levels:list[str]|None=Query(None),sources:list[str]|None=Query(None),topic_ids:list[str]|None=Query(None),user=Depends(auth.current)):
 def values(multiple,single=''):
  result=list(dict.fromkeys([*(multiple or []),*([single] if single and single!='All' else [])]))
  if len(result)>50 or any(len(v)>300 for v in result):raise HTTPException(422,'Too many filter selections.')
  return set(result)
 chosen={'fields':values(fields,field),'groups':values(groups,group),'providers':values(providers,provider),'formats':values(formats,format),'accesses':values(accesses,access),'levels':values(levels,level),'sources':values(sources,source)}
 provider_aliases={'www.datacamp.com':'DataCamp','datacamp.com':'DataCamp','www.codecademy.com':'Codecademy','codecademy.com':'Codecademy','datalemur.com':'DataLemur'}
 chosen['providers']={provider_aliases.get(v.casefold(),v) for v in chosen['providers']}
 allowed={'fields':set(FIELDS),'groups':{g['id'] for g in skill_catalog.data()['groups']},'formats':{'documentation','tutorial','course','practice','project','catalog'},'accesses':{'free','freemium','paid','unknown'},'levels':{'beginner','intermediate','advanced','all','unspecified'},'sources':{'profile','goal','posting'}}
 if any(chosen[k]-v for k,v in allowed.items()) or sort not in ('relevance','recommended','title','provider') or kind not in ('learning','support'):raise HTTPException(422,'Choose valid resource filters.')
 ids=set(selected_ids([*topics.split('|'),*(topic_ids or [])]));related={v for id in ids for v in skill_catalog.index().get(id,{}).get('related',[])}-ids
 personal=topic_sources(user,job_id,True);index=skill_catalog.index();rows=[]
 priority={'posting':0,'goal':1,'occupation':1,'profile':2,'related':3}
 for raw in library():
  if (raw['resource_type']=='learning')!=(kind=='learning'):continue
  direct=ids.intersection(raw['topic_ids']);near=related.intersection(raw['topic_ids'])
  if ids and not (direct or near):continue
  row=display_resource(raw);reasons=[]
  for id in row['topic_ids']:
   for reason in personal.get(id,{}).get('sources',[]):
    item={'skill_id':id,**reason}
    if item not in reasons:reasons.append(item)
  reasons.sort(key=lambda v:(priority.get(v['kind'],4),v['label'].casefold(),v['skill_id']))
  row.update(match_kind='direct' if not ids or direct else 'related',match_count=len(direct),recommendation_reasons=reasons)
  row['_groups']={g for id in row['topic_ids'] for g in [index.get(id,{}).get('group'),*index.get(id,{}).get('secondary_groups',[])] if g}
  row['_fields']={row['field'],*row.get('secondary_fields',[])}
  if row['field']=='All fields':row['_fields'].update(FIELDS)
  row['_sources']={('goal' if s.get('origin_kind',s['kind'])=='occupation' else s.get('origin_kind',s['kind'])) for s in reasons}
  aliases=[a for id in row['topic_ids'] for a in index.get(id,{}).get('aliases',[])]
  haystack=skill_catalog.normalize(' '.join([row['title'],row['display_title'],row['description'],row['provider'],*row['learning_topics'],*aliases]))
  if not all(t in haystack for t in skill_catalog.normalize(q).split()):continue
  rows.append(row)
 def members(row,name):
  return row['_'+name] if name in ('groups','fields','sources') else {row[{'providers':'provider','formats':'format','accesses':'access_kind','levels':'level'}[name]]}
 def matches(row,skip=''):
  return all(not selected or name==skip or selected.intersection(members(row,name)) for name,selected in chosen.items())
 facets={name:sorted(chosen[name]|{v for row in rows if matches(row,name) for v in members(row,name) if v in allowed.get(name,{v})}) for name in chosen}
 rows=[r for r in rows if matches(r)]
 if sort=='provider':rows.sort(key=lambda r:(r['provider'].casefold(),r['display_title'].casefold(),r['id']))
 elif sort=='title':rows.sort(key=lambda r:(r['display_title'].casefold(),r['id']))
 else:rows.sort(key=lambda r:(r['match_kind']!='direct',-r['match_count'],min((priority.get(s['kind'],4) for s in r['recommendation_reasons']),default=4),r['display_title'].casefold(),r['id']))
 total=len(rows);direct_count=sum(r['match_kind']=='direct' for r in rows)
 public=[{k:v for k,v in r.items() if not k.startswith('_')} for r in rows[offset:offset+limit]]
 return {'resources':public,'total':total,'offset':offset,'limit':limit,'providers':facets['providers'],'facets':facets,'direct_count':direct_count,'related_count':total-direct_count,'version':skill_catalog.data()['version']}


def practice_topics(record):return selected_ids(record['data'].get('selected_topics',record['data'].get('confirmed_gaps',[])))
def practice_public(user,record):
 job=db.get(user,record['data'].get('job_id',''),'job')
 label=record['data'].get('target_label') or ((job['data'].get('title') or 'Saved opportunity') if job else ('Removed opportunity' if record['data'].get('job_id') else 'My Profile and Career Goals'))
 return {**record,'topic_refs':skill_catalog.refs(record['data'].get('selected_topics',record['data'].get('confirmed_gaps',[]))),'target_label':label}

@router.get('/practice')
def practice_history(topics:str=Query('',max_length=5000),job_id:str='',q:str=Query('',max_length=150),target:str='all',offset:int=Query(0,ge=0,le=10000),limit:int=Query(12,ge=1,le=24),user=Depends(auth.current)):
 if target not in ('all','current'):raise HTTPException(422,'Choose a history target.')
 if job_id and not db.get(user['id'],job_id,'job'):raise HTTPException(404,'Job not found.')
 rows=db.list_entities(user['id'],'prep');ids=set(selected_ids(topics.split('|')))
 matching=next((r for r in rows if (r['data'].get('job_id') or '')==job_id and ids.issubset(practice_topics(r))),None)
 history=[practice_public(user['id'],r) for r in rows if not matching or r['id']!=matching['id']]
 if target=='current':history=[r for r in history if (r['data'].get('job_id') or '')==job_id]
 if q:history=[r for r in history if all(t in (r['data'].get('title','')+' '+' '.join(v['label'] for v in r['topic_refs'])+' '+r['target_label']+' '+r['created_at']).casefold() for t in q.casefold().split())]
 with db.connect() as c:active=c.execute("SELECT 1 FROM tasks WHERE user_id=? AND kind='preparation' AND status IN ('queued','running','cancelling')",(user['id'],)).fetchone() is not None
 return {'matching':practice_public(user['id'],matching) if matching else None,'history':history[offset:offset+limit],'total':len(history),'offset':offset,'limit':limit,'generation_active':active,'retention':'Saved until you delete them. No automatic expiry.'}

@router.delete('/practice/{id}')
def delete_practice(id:str,user=Depends(auth.current)):
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE')
  row=c.execute("SELECT id FROM entities WHERE user_id=? AND id=? AND kind='prep'",(user['id'],id)).fetchone()
  if not row:raise HTTPException(404,'Saved practice suggestions not found.')
  if c.execute("SELECT 1 FROM tasks WHERE user_id=? AND kind='preparation' AND status IN ('queued','running','cancelling')",(user['id'],)).fetchone():raise HTTPException(409,'Wait for the current practice request to finish or stop before deleting saved suggestions.')
  c.execute('DELETE FROM entities WHERE user_id=? AND id=?',(user['id'],id));c.execute('DELETE FROM evidence_fts WHERE user_id=? AND id=?',(user['id'],id))
  for task in c.execute("SELECT id,result FROM tasks WHERE user_id=? AND kind='preparation'",(user['id'],)).fetchall():
   value=json.loads(task['result'] or '{}');saved=value.get('_task_result',value)
   if saved.get('id')==id:c.execute('UPDATE tasks SET result=?,error=? WHERE user_id=? AND id=?',(json.dumps({'deleted_practice_id':id}),'',user['id'],task['id']))
 return {'deleted_id':id}

@router.get('/topics/{id}')
def get_topic(id:str,user=Depends(auth.current)):
 identity=skill_catalog.resolve(id)
 if not identity:raise HTTPException(404,'Skill not found in this catalog.')
 item=skill_catalog.index()[identity]
 return {**item,'related_skills':[skill_catalog.index()[r] for r in item['related']]}

@router.get('/taxonomy')
def taxonomy(user=Depends(auth.current)):
 catalog=skill_catalog.data()
 return {'version':catalog['version'],'reviewed_at':catalog['reviewed_at'],'fields':list(FIELDS),'groups':catalog['groups'],'skill_count':len(catalog['skills']),'resource_count':len(catalog['resources']),'skill_page_size':24,'resource_page_size':12,'formats':['documentation','tutorial','course','practice','project','catalog'],'access_categories':['free','freemium','paid','unknown'],'difficulty_levels':['beginner','intermediate','advanced','all','unspecified']}
