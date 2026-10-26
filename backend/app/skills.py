"""Discipline-wide learning resources and conservative practice topics."""
import json,re
from fastapi import APIRouter,Depends,HTTPException
from . import auth,db,config,career_goals,coach_knowledge,role_catalog
router=APIRouter(prefix='/api/skills')
BLOCK=re.compile(r'\b(?:bachelor|master.?s|doctorate|ph\.?d|degree|gpa|academic success|professional success|eligible|citizen|sponsor|visa|vaccin|disabil|veteran|authori[sz]|background check|criminal|drug test|years? of|\d+\+? years|licen[sc]ed|required license)\b',re.I)
FIELDS={'Tech & Data':['python','sql','stats','cloud','microsoft','it','software','data-engineering'],'Business & Consulting':['consulting','marketing','accounting','finance','operations','cfa','cpa','marketing-cert','hr-cert','google-cert'],'Engineering':['engineering','engineering-license','cad','quality-cert'],'Health & Medical':['nursing','public-health','clinical','health-admin','nursing-cert','lab-cert'],'Education & Public Service':['teaching','public-service'],'Arts & Communication':['writing','design','journalism'],'Science & Research':['science','research-methods','environment']}
def learnable(value):return bool(str(value).strip()) and not BLOCK.search(str(value))
def library():
 rows=json.loads((config.CONTENT_DIR/'resources.json').read_text());urls={r['url'] for r in rows}
 for r in rows:r.setdefault('field','Tech & Data');r.setdefault('topics',[r['skill']])
 for r in coach_knowledge.catalog():
  if r['url'] in urls or not coach_knowledge.safe_url(r['url']):continue
  field=next((k for k,v in FIELDS.items() if r['id'] in v),'All fields')
  rows.append({'id':r['id'],'title':r['title'],'skill':r['topics'][0],'topics':r['topics'],'field':field,'description':r['text'],'activity':'Choose one relevant topic, practice it on a fictional or permitted example, and describe what you learned.','url':r['url'],'access':'Official/public guidance; verify provider access, costs and prerequisites.'});urls.add(r['url'])
 return rows
@router.get('/options')
def options(job_id:str='',user=Depends(auth.current)):
 job=db.get(user['id'],job_id,'job') if job_id else None
 if job_id and not job:raise HTTPException(404,'Job not found.')
 text=career_goals.read(user['id'])['text']+' '+' '.join(role_catalog.suggestions(user['id']))
 if job:text+=' '+str(job['data'].get('title',''))+' '+str(job['data'].get('description',''))
 rows=library();suggested=[]
 for row in rows:
  matches=[t for t in row.get('topics',[row['skill']]) if len(t)>2 and learnable(t) and role_catalog.phrase(t,text)]
  if matches:
   for topic in matches:
    if topic not in suggested:suggested.append(topic)
 # Existing analyses can contribute only concrete learnable competency labels.
 if job:
  analysis=next((r for r in db.list_entities(user['id'],'analysis') if r['data'].get('job_id')==job_id),None)
  for r in (analysis or {}).get('data',{}).get('requirements',[]):
   topic=r.get('keyword','')
   if learnable(topic) and len(topic)<100 and any(role_catalog.phrase(t,topic) for row in rows for t in row.get('topics',[])) and topic not in suggested:suggested.append(topic)
 return {'resources':rows,'fields':list(FIELDS),'suggestions':suggested[:10],'basis':'Reviewed Profile, Career Goals and an optional posting; these are learning topics, not confirmed deficiencies.'}
