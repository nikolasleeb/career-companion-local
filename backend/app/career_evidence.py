"""Traceable local mentions in reviewed professional records. Never inferred proficiency."""
import hashlib,json,re,unicodedata
from . import db,profile_answers,job_ai,work_preferences
ALIASES={
 'aws':['aws','amazon web services','amazon web services aws software'],
 'ec2':['ec2','amazon elastic compute cloud ec2'],
 'dynamodb':['dynamodb','amazon dynamodb'],
 'cloudformation':['cloudformation','aws cloudformation','amazon web services aws cloudformation'],
 'sql':['sql','structured query language','structured query language sql'],
 'power bi':['power bi','powerbi','microsoft power bi'],
 'powerpoint':['ppt','pptx','powerpoint','microsoft powerpoint'],
 'excel':['excel','microsoft excel'], 'spark':['spark','apache spark','pyspark'],
 'snowflake':['snowflake'], 'tableau':['tableau'],
 'azure':['azure','microsoft azure','microsoft azure software'],
 'macos':['macos','mac os','apple macos'], 'javascript':['javascript'],
 'python':['python'], 'quality control analysis':['quality control analysis'],
}
CONTEXT={'operations monitoring':['monitor dashboards','monitoring dashboards','robot availability','floor availability','command-center operations'],
 'installation':['configured a distributed','cluster startup','installed','deployed infrastructure'],
 'programming':['python','sql','pyspark','javascript','scripts'],
 'troubleshooting':['clearing jams','resetting sensors','debugging','false positives','remediation'],
 'quality control analysis':['qa/qc','quality assurance','rule testing','tested qa/qc']}
def norm(v):return ' '.join(re.findall(r'[\w+#]+',unicodedata.normalize('NFKC',v).casefold()))
def phrase(needle,text):return (' '+norm(needle)+' ') in (' '+norm(text)+' ')
def canonical(label):
 for key,aliases in ALIASES.items():
  if norm(label) in {norm(v) for v in aliases}:return key
 return norm(label)
def sources(user):
 rows=[]
 for record in db.list_entities(user,'experience'):
  d=record['data']
  if not d.get('confirmed'):continue
  title=d.get('title') or d.get('organization') or 'Profile record'
  for field in ('title','tools','description','contribution','accomplishments','majors','minors','major','minor','concentration','relevant_courses','skill_items','certification_items'):
   raw=d.get(field)
   if not raw:continue
   if field=='skill_items':texts=[v.get('name','') for v in raw if isinstance(v,dict)]
   elif field=='certification_items':texts=[v.get('name','') for v in raw if isinstance(v,dict)]
   else:texts=[str(v) for v in raw] if isinstance(raw,list) else [str(raw)]
   for index,text in enumerate(texts):
    text=job_ai.clean(text)
    if not text:continue
    for n,part in enumerate(re.findall(r'[^\n.!?]+(?:[.!?]|$)',text)):
     part=part.strip()
     # Split long passages without clipping mentions at the end of a record.
     for offset in range(0,len(part),1200):
      chunk=part[offset:offset+1200]
      learning=d.get('category') in ('education','coursework') or field=='relevant_courses' or bool(re.search(r'\bfundamentals\b|\bcourse(?:work)?\b|\bstudied\b',chunk,re.I))
      rows.append({'id':f"{record['id']}:{field}:{index}:{n}:{offset}",'record_id':record['id'],'title':title,'field':field,'text':chunk,'learning':learning,'updated_at':record['updated_at']})
 for r in profile_answers.confirmed(user):
  d=r['data']
  if d.get('answer_kind')!='experience':continue
  text=job_ai.clean(d.get('text') or d.get('answer') or '')
  for i in range(0,len(text),1200):rows.append({'id':r['id']+':answer:'+str(i),'record_id':r['id'],'title':d.get('title') or 'Supporting Details','field':'answer','text':text[i:i+1200],'learning':False,'updated_at':r['updated_at']})
 return rows
def revision(rows):return hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
def matches(item,rows):
 key=canonical(item['name']);aliases=ALIASES.get(key,[item['name']]);direct=[];related=[]
 for row in rows:
  if key in ('installation','operations monitoring'):
   if any(phrase(term,row['text']) for term in CONTEXT.get(key,[])):related.append(row)
   continue
  if any(phrase(alias,row['text']) for alias in aliases):
   negated=bool(re.search(r'\b(?:not|never|without|no experience|unfamiliar)\b',row['text'],re.I))
   if not negated:
    target=related if row['learning'] or key in ('installation','operations monitoring') else direct;target.append(row)
  elif any(phrase(term,row['text']) for term in CONTEXT.get(key,[])):related.append(row)
 status='found' if direct else 'related' if related else 'unknown'
 label={'found':'Found in Profile','related':'Related evidence—review','unknown':'No supporting reference found'}[status]
 return {**item,'match_status':status,'profile_status':label,'profile_references':[{k:r[k] for k in ('id','record_id','title','field','text','learning')} for r in (direct or related)[:4]]}
def style(user):
 value=work_preferences.context(user)
 return {'enabled':bool(value['preferences']),'summary':'\n'.join(value['preferences']),'revision':value['revision']}
