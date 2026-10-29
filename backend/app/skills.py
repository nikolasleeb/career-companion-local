"""Discipline-wide learning resources and conservative practice topics."""
import json,re
from fastapi import APIRouter,Depends,HTTPException
from . import auth,db,config,career_goals,coach_knowledge,role_catalog,learning_topics,career_evidence,job_ai
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
 return rows
@router.get('/options')
def options(job_id:str='',field:str='All',user=Depends(auth.current)):
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
 suggestions=sorted(found.values(),key=lambda v:v['rank'])[:10]
 for value in suggestions:value.pop('rank')
 return {'resources':rows,'fields':list(FIELDS),'suggested_topics':suggestions,'suggestions':[v['label'] for v in suggestions],'basis':'Choose skills to practice or explore. Sources explain why a topic is shown; none is a confirmed weakness.','topic_catalog':[{'id':k,'label':v['label'],'aliases':sorted(v['aliases'])} for k,v in learning_topics.vocabulary().items()]}

@router.get('/plan-link')
def plan_link(plan_id:str,milestone_id:str,user=Depends(auth.current)):
 from . import plan_progress
 plan=plan_progress.owned(user['id'],plan_id,'coach_plan')
 action=next((a for a in plan['data']['actions'] if a['id']==milestone_id),None)
 if not action:raise HTTPException(404,'Milestone not found in this plan.')
 return {'plan_id':plan_id,'chat_id':plan['data']['chat_id'],'milestone_id':milestone_id,'title':action['title'],'learning_topics':learning_topics.milestone(action)}
