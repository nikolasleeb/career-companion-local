"""Build the reviewed, versioned catalog; source-check failures never enter it."""
import collections,hashlib,json,re,unicodedata
from pathlib import Path
HERE=Path(__file__).parent
ROOT=HERE.parents[1]
def slug(value):return re.sub(r'[^a-z0-9]+','-',unicodedata.normalize('NFKD',value).encode('ascii','ignore').decode().lower()).strip('-')
checks={r['url']:r for name in ('source_checks.json','web_checks.json') for r in json.loads((HERE/name).read_text()) if r.get('valid')}
rows=json.loads((HERE/'sources.json').read_text())
# The curriculum roots below are real learning topics and keep earlier links working.
aliases={'Spark':['Apache Spark'],'PySpark':['Python on Spark'],'Structured Streaming':['Spark Structured Streaming'],'SQL':['Structured Query Language'],'Power BI':['PowerBI','Microsoft Power BI','dashboards'],'AWS':['Amazon Web Services','cloud infrastructure','aws infrastructure'],'Git':['version control'],'Linux':['command line'],'Statistics':['stats','statistical analysis'],'Networking':['computer networking','network troubleshooting'],'CAD':['computer aided design','autodesk'],'CSS':['Cascading Style Sheets'],'HTML':['Hypertext Markup Language'],'ETL':['extract transform load'],'Writing':['written expression'],'Research methods':['research methodology','literature review']}
# Existing reviewed resources, preserved by URL and ID at runtime.
legacy=json.loads((ROOT/'data/resources.json').read_text())
legacy_topics={'sql_lemur':['SQL'],'sql_bolt':['SQL'],'python':['Python'],'stats':['Statistics'],'powerbi':['Power BI'],'git':['Git'],'net':['Networking'],'linux':['Linux'],'support':['Troubleshooting'],'codecademy-python':['Python'],'codecademy-sql':['SQL'],'datacamp-python':['Python'],'datacamp-sql':['SQL']}
# Review the existing concrete resources with the same source checker on future refreshes.
rows=[r for r in rows if r['url'] not in {v['url'] for v in legacy}]
for r in legacy:
 if r['id'] in ('git','net'):continue  # Generic provider landing pages remain compatible, but do not count as coverage.
 for label in legacy_topics.get(r['id'],[]):
  rows.append(dict(label=label,url=r['url'],provider=r['title'].split(' — ')[0],field='Tech & Data',group='analytics' if label in ('Statistics','Power BI') else 'systems' if label in ('Linux','Networking','Troubleshooting') else 'databases' if label=='SQL' else 'programming',legacy=r))
# Keep root-level learning links supported with directly relevant reviewed material.
extra=[('AWS','IAM policies'),('Linux','Linux directory listing'),('Data modeling','SQL table constraints'),('Data validation','Python exceptions'),('ETL','Spark data sources'),('Communication','Written communication'),('Writing','Written communication'),('Lesson planning','Learning activity design'),('Research methods','The Process of Science'),('Experimental design','The Process of Science')]
by_label={r['label']:r for r in rows}
for label,reference in extra:
 if reference in by_label:
  ref=by_label[reference];rows.append({**ref,'label':label,'topic_id':slug(label)})
# Broad parent topics point only at resources whose scope includes that topic.
roots={'Python':['Python control flow','Python data structures','Python modules','Python file input and output','Python exceptions','Python classes'], 'SQL':['SQL SELECT queries','SQL joins','SQL aggregate functions','SQL window functions','SQL common table expressions'], 'Spark':['PySpark','Spark SQL','Structured Streaming'], 'AWS':['IAM policies','AWS Lambda','Amazon S3 object storage']}
skills={};resources={};groups={}
for row in rows:
 check=checks.get(row['url'])
 if not check:continue
 label=row['label'];id=row.get('topic_id',slug(label));group=row['group'];field=row['field']
 groups.setdefault(group,{'id':group,'label':group.replace('-',' ').title().replace('Ai Ml','AI / ML').replace('Devops','DevOps'),'field':field})
 skills.setdefault(id,{'id':id,'label':label,'description':('Study '+label.lower()+' through educational reference material.' if field=='Health & Medical' else 'Learn and practice '+label+' using the resources below.'),'field':field,'group':group,'aliases':aliases.get(label,[]),'related':[]})
 url=check.get('final_url',row['url']).split('#')[0].rstrip('/')
 rid=row.get('resource_id') or 'learn-'+hashlib.sha256(url.encode()).hexdigest()[:18]
 title=row.get('source_title') or check.get('heading') or check.get('title') or label
 title=re.sub(r'\s+',' ',title).strip()
 # Use an informative provider and the actual source heading, not a made-up activity title.
 if row.get('legacy'):title=row['legacy']['title']
 resource=resources.setdefault(url,{'id':rid,'title':row['provider']+' — '+title,'provider':row['provider'],'url':url,'description':row.get('legacy',{}).get('description') or (('Educational chapter on ' if field!='Tech & Data' else 'Documentation and examples for ')+label+'.'),'field':field,'learning_topics':[],'resource_type':'learning','format':'tutorial' if field!='Tech & Data' or 'tutorial' in row['url'] or 'quick' in row['url'] else 'documentation','access_kind':'free','access':'Public learning material. Check provider for any separate services or software costs.','level':'unspecified','reviewed_at':check['checked_at'],'source_title':check['title'],'review_method':check.get('review_method','HTTP content and destination check')})
 if label not in resource['learning_topics']:resource['learning_topics'].append(label)
 if row.get('legacy'):
  old=row['legacy'];resource['id']=old['id'];resource['title']=old['title'];resource['access']=old['access'];resource['format']='course' if 'codecademy' in old['id'] or 'datacamp' in old['id'] else resource['format'];resource['access_kind']='freemium' if 'codecademy' in old['id'] or 'datacamp' in old['id'] else 'free'
# Git's specific repository chapter covers the parent skill.
if 'git-repository-creation' in skills:
 source=skills['git-repository-creation'];skills['git']={**source,'id':'git','label':'Git','aliases':['version control'],'related':[]}
 for r in resources.values():
  if 'Git repository creation' in r['learning_topics']:r['learning_topics'].append('Git')
# Associate a small reviewed family of adjacent skills; direct results still require explicit tags.
for id,s in skills.items():
 peers=[v for v in skills.values() if v['group']==s['group']]
 pos=peers.index(s)
 s['related']=[p['id'] for p in peers[max(0,pos-1):pos+2] if p['id']!=id]
for parent,children in roots.items():
 if slug(parent) not in skills:continue
 for child in children:
  if slug(child) not in skills:continue
  for a,b in ((slug(parent),slug(child)),(slug(child),slug(parent))):
   if b not in skills[a]['related']:skills[a]['related'].append(b)
# Shared SQL/Python foundations connect Spark dialects and APIs without conflating their identities.
for a,b in [('Spark SQL','SQL'),('PySpark','Python'),('Structured Streaming','Spark')]:
 if slug(a) in skills and slug(b) in skills:
  for x,y in [(a,b),(b,a)]:
   if slug(y) not in skills[slug(x)]['related']:skills[slug(x)]['related'].append(slug(y))
descriptions={
 'programming':'Write, organize and test programs', 'databases':'Query and structure relational data', 'data-engineering':'Process data with distributed pipelines', 'analytics':'Transform, summarize and visualize data', 'cloud':'Configure and use cloud infrastructure', 'devops':'Build, ship and operate software', 'systems':'Work with operating-system files, commands and processes', 'cybersecurity':'Design and evaluate security controls', 'ai-ml':'Train, compare and evaluate machine-learning methods', 'patient-assessment':'Study how clinicians gather and interpret patient observations', 'patient-safety':'Study procedures that reduce infection and patient-handling risks', 'clinical-foundations':'Study clinical procedure principles in an educational setting', 'learning-design':'Design instruction around learning theories and teaching methods', 'educational-technology':'Choose and use media for teaching and learning', 'assessment-and-support':'Develop learning goals, assessments and learner support', 'cell-biology':'Explain cellular structures, energy and transport processes', 'genetics':'Explain inheritance and molecular genetic mechanisms', 'biology-and-ecology':'Investigate biological systems and scientific reasoning', 'strategy-and-operations':'Analyze business goals, strategy and operational controls', 'organization-and-leadership':'Evaluate organizational structures, leadership and change', 'people-and-teams':'Develop approaches to teams, motivation and human resources', 'writing-and-editing':'Develop and revise clear written communication', 'presentations-and-speaking':'Plan and deliver effective presentations', 'communication-practice':'Adapt communication to audiences and professional situations', 'engineering-mechanics':'Solve mechanics problems using forces, vectors and equilibrium', 'structures-and-statics':'Analyze structures, loads and static equilibrium', 'friction-and-inertia':'Calculate friction behavior and geometric or mass properties'}
for s in skills.values():s['description']=descriptions.get(s['group'],'Develop practical understanding')+'; focus on '+s['label']+'.'
for label,description in {'Spark':'Process large datasets using Apache Spark’s distributed execution and DataFrame APIs.','PySpark':'Use the Python API for Apache Spark to build distributed data transformations.','Spark SQL':'Query structured datasets with Spark SQL and understand DataFrame execution.','Structured Streaming':'Build incremental streaming queries with Spark’s structured-data engine.','SQL':'Read, combine and summarize relational data with Structured Query Language.','Python':'Write and test Python programs using core language features and libraries.'}.items():
 if slug(label) in skills:skills[slug(label)]['description']=description
catalog={'version':'2026-10-30.1','reviewed_at':'2026-10-30','groups':list(groups.values()),'skills':list(skills.values()),'resources':list(resources.values())}
(ROOT/'backend/app/skills_catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n')
print('skills',len(skills),dict(collections.Counter(s['field'] for s in skills.values())))
print('resources',len(resources),dict(collections.Counter(s['field'] for s in resources.values())))
