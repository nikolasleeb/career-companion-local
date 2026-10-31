"""Opt-in paired fictional resume evaluation. Never uses real applicant records.

The persisted ledger reserves a conservative maximum before every request, disables
retries, and retains unknown charges. --ceiling defaults to the approved $2 cap.
"""
import argparse,asyncio,base64,copy,importlib.util,json,os,shutil,sys,tempfile,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))

POSTINGS={
 'graduate':'''Graduate development program. Tracks include Information Digital Technologies, Commercial and Finance.
What you will do: Analyze problems and propose purposeful solutions. Share original ideas, collaborate with colleagues and explain results. Adapt to changing requirements and deliver practical projects.
Required qualifications: A relevant degree and minimum GPA of 3.20.
Preferred qualifications: Python, SQL and cloud technologies for the digital track.''',
 'data-engineering':'''Graduate Data Engineer
Required qualifications: Python, SQL and practical data pipeline experience.
Responsibilities: Design AWS ingestion pipelines, transform datasets using Spark, document data quality and collaborate with analytics colleagues.
Preferred qualifications: Cloud certification and clear stakeholder communication.''',
 'analyst':'''Operations Data Analyst
Required qualifications: Python or SQL and clear written communication.
Responsibilities: Clean and analyze operational datasets, visualize findings and explain limitations to stakeholders.
Preferred qualifications: Tableau or Power BI. Experience comparing demand and price trends.''',
 'transferable':'''Technology Graduate
Required qualifications: A relevant degree and analytical problem-solving.
Responsibilities: Learn new tools, communicate with nontechnical stakeholders and adapt solutions from feedback.
Preferred qualifications: Python or cloud familiarity.''',
 'software':'''Junior Software Developer
Required qualifications: Python or TypeScript, Git and experience building applications.
Responsibilities: Implement and test web features, debug defects and collaborate on code reviews.
Preferred qualifications: SQL and deployment experience.''',
 'cloud-support':'''Cloud Support Associate
Required qualifications: Linux, networking fundamentals and technical troubleshooting.
Responsibilities: Investigate incidents, document solutions and communicate with users.
Preferred qualifications: AWS familiarity and a cloud certification.''',
 'operations':'''Graduate Supply Chain Analyst
Required qualifications: A business-related degree and Excel analysis.
Responsibilities: Investigate stock discrepancies, improve reporting workflows and collaborate with warehouse teams.
Preferred qualifications: SQL or Power BI.''',
 'marketing':'''Marketing Insights Assistant
Required qualifications: Clear writing and spreadsheet analysis.
Responsibilities: Compare campaign results, build understandable visualizations and explain data limitations to nontechnical colleagues.
Preferred qualifications: Tableau or SQL.''',
}

def seed(db,user,kind):
 from app.models import ExperienceItem
 def record(**d):return db.save(user,'experience',ExperienceItem(confirmed=True,**d).model_dump())
 if kind in ('software','cloud-support','operations','marketing'):
  profiles={
   'software':('BS Computer Science','Computer Science','Software Intern','Example Software Studio','Implemented Python API endpoints and wrote unit tests. Participated in code reviews with two developers.','Inventory web application','Built a TypeScript web interface and a Python service using SQL queries. Deployed the application to a test environment.',['Python','TypeScript','SQL','Git']),
   'cloud-support':('BS Information Technology','Information Technology','Service Desk Technician','Example Campus IT','Investigated Linux workstation and networking incidents. Wrote troubleshooting notes and explained solutions to users.','AWS practice environment','Configured an AWS EC2 Linux instance, S3 storage and access policies. Tested backup restoration using practice files.',['Linux','Networking Fundamentals','AWS','Git']),
   'operations':('BS Business Administration','Business Administration','Warehouse Team Member','Example Distribution','Investigated stock discrepancies with supervisors. Built an Excel workbook to reconcile count sheets and document exceptions.','Inventory reporting coursework','Compared inventory trends in Excel and presented a reporting workflow to classmates. This was coursework rather than production deployment.',['Excel','Data Visualization']),
   'marketing':('BA Marketing','Marketing','Student Organization Coordinator','Example Campus Association','Prepared event communications and coordinated feedback from student volunteers. Wrote short summaries of attendance trends.','Campaign reporting coursework','Cleaned campaign practice data in Excel and created Tableau charts. Explained sampling limitations in a presentation; no causal uplift was established.',['Excel','Tableau','Written Communication'])}
  degree,major,title,org,work,project,description,skills=profiles[kind]
  record(category='education',title=degree,degree=degree.split()[0],major=major,organization='Example University',expected_graduation='May 2027',gpa='3.6',gpa_scale='4.0')
  record(category='employment',title=title,organization=org,start_date='June 2026',description=work)
  record(category='project',title=project,description=description,individual_project=True)
  record(category='skills',title='Tools and methods',skill_items=[{'name':n} for n in skills])
  if kind=='cloud-support':record(category='skills',title='AWS Certified Cloud Practitioner',certification_items=[{'name':'AWS Certified Cloud Practitioner','issuer':'AWS'}])
  return
 degree=record(category='education',title='MS Data Science',degree='Master of Science',major='Data Science',organization='Example University',expected_graduation='May 2027',gpa='4.0',gpa_scale='4.0',relevant_courses='Cloud Data Warehousing; SQL Databases; Big Data Technologies')
 intern=record(category='employment',title='Technology Intern',organization='Example Transport Agency',start_date='June 2026',end_date='August 2026',description='Demonstrated prototypes to planning stakeholders. Incorporated feedback into later iterations.',accomplishments='Collaborated with regional planners to compare three transportation scenarios.')
 record(category='employment',title='Operations Associate',organization='Example Distribution',description='Ranked in the top 5% for seasonal pick productivity. Assisted command-center operations supporting 900 autonomous robots.')
 prototype=record(category='project',title='Document QA review prototype',start_date='June 2026',description='Built an on-device Python and retrieval-augmented generation prototype for document review. Initially tested it on approximately 10 documents.',contribution='A colleague prepared the sample documents. The sponsors intended this proof of concept to inform future technology adoption.',linked_employment_ids=[intern['id']],individual_project=False)
 record(category='project',title='Transport weather data pipeline',description='Designed AWS infrastructure using EC2, Lambda, S3 and Glue to ingest transport and weather data. Built a Spark workload for distributed data cleaning.',contribution='Owned cloud architecture and data engineering while a teammate handled predictive analytics.',linked_education_ids=[degree['id']])
 record(category='project',title='Gasoline demand and price analysis',description='Used Python to clean, merge and visualize gasoline demand and pricing datasets. Documented time-series features and limitations for exploratory analysis.',contribution='Developed the analysis independently; a teammate edited the presentation.')
 record(category='skills',title='Programming and data',skill_items=[{'name':n} for n in ('Python','SQL','Apache Spark','ETL/ELT')])
 record(category='skills',title='Cloud platforms',skill_items=[{'name':n} for n in ('AWS','Git')])
 record(category='skills',title='Analytics',skill_items=[{'name':n} for n in ('Tableau','Power BI')])
 record(category='skills',title='AWS Certified Cloud Practitioner',certification_items=[{'name':'AWS Certified Cloud Practitioner','issuer':'AWS','earned_date':'2025-01-01','expiration_date':'2028-01-01'}])
 db.save(user,'profile_answer',{'status':'confirmed','answer_kind':'experience','experience_id':prototype['id'],'experience_ids':[prototype['id']],'text':'Selected for the prototype assignment because of previous practical AI experience.','title':'Assignment context','version':1,'sources':[]})
 if kind=='transferable':
  # This example deliberately has fewer technical sources; never infer a deficiency.
  for row in db.list_entities(user,'experience'):
   if row['data'].get('title') in ('Transport weather data pipeline','Gasoline demand and price analysis','Programming and data','Cloud platforms','Analytics'):
    db.save(user,'experience',{**row['data'],'confirmed':False},row['id'])


def main():
 p=argparse.ArgumentParser();p.add_argument('--key-file',required=True);p.add_argument('--output',required=True);p.add_argument('--baseline',required=True);p.add_argument('--model',default='gpt-6-luna');p.add_argument('--reasoning',default='low');p.add_argument('--cases',default=','.join(POSTINGS));p.add_argument('--ceiling',type=float,default=2);p.add_argument('--improved-only',action='store_true');args=p.parse_args()
 if not 0<args.ceiling<=2:raise SystemExit('The authorized evaluation ceiling is at most $2.')
 target=Path(args.output);ledger=json.loads(target.read_text()) if target.exists() else {'ceiling_usd':args.ceiling,'estimated_or_reserved_usd':0,'requests':[],'cases':[]}
 folder=Path(tempfile.mkdtemp(prefix='resume-live-'));os.chmod(folder,0o700)
 os.environ.update(DATA_DIR=str(folder),VAULT_KEY_FILE=str(folder/'vault.key'),JOB_SCHEDULER_ENABLED='false')
 from app import ai,ai_settings,auth,config,credentials,db,resume_conversation,resume_strategy,optimization,resume_layout
 from app.main import app
 from fastapi.testclient import TestClient
 from app.models import ConversationStart
 spec=importlib.util.spec_from_file_location('app.resume_optimization_baseline',args.baseline);baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
 original=ai.call_api
 original_structured=ai.structured;active_row=None
 async def capture(schema,payload,*a,**kw):
  result=await original_structured(schema,payload,*a,**kw)
  if active_row is not None:
   active_row.setdefault('stages',[]).append({'schema':schema.__name__,'output':copy.deepcopy(result[0]),'professional_evidence':payload.get('professional_evidence')});save()
  return result
 ai.structured=capture
 def save():
  target.parent.mkdir(parents=True,exist_ok=True);tmp=target.with_suffix('.pending');tmp.write_text(json.dumps(ledger,indent=2));os.chmod(tmp,0o600);tmp.replace(target)
 async def guarded(body,retry_allowed=False):
  rate=ai_settings.rates(body['model'],body.get('service_tier','default'))
  if not rate:raise RuntimeError('No verified rates; request was not dispatched.')
  reserved=((len(json.dumps(body).encode())+2048)*rate['input']+body.get('max_output_tokens',8000)*rate['output'])/1e6
  if ledger['estimated_or_reserved_usd']+reserved>args.ceiling:raise RuntimeError('Evaluation spending ceiling would be exceeded; no request dispatched.')
  ledger['estimated_or_reserved_usd']+=reserved;entry={'model':body['model'],'schema':body.get('text',{}).get('format',{}).get('name'),'reserved_usd':reserved,'state':'unknown'};ledger['requests'].append(entry);save()
  result=await original(body,retry_allowed=False)
  if isinstance(result.get('usage'),dict):
   actual=ai_settings.usage_cost(result.get('model',body['model']),result['usage'],service_tier=result.get('service_tier') or body.get('service_tier','default'))
   if actual is not None:ledger['estimated_or_reserved_usd']+=actual-reserved;entry.update(actual_usd=actual,state='reported',usage=result['usage'])
  save();return result
 ai.call_api=guarded
 with TestClient(app) as client:
  try:
   for kind in args.cases.split(','):
    if kind not in POSTINGS:raise ValueError('Unknown fictional case')
    auth.attempts.clear();response=client.post('/api/auth/register',json={'username':'resume_eval_'+db.uid()[:10],'password':'fictional-evaluation-password'});response.raise_for_status();user=response.json();uid=user['id'];client.headers['X-CSRF-Token']=user['csrf']
    seed(db,uid,kind);credentials.save(uid,Path(args.key_file).read_text().strip())
    db.update_settings(uid,{'name':'Example Student','custom_model':args.model,'custom_reasoning':args.reasoning,'custom_speed':'standard'})
    job=db.save(uid,'job',{'title':kind+' role','company':'Example Employer','description':POSTINGS[kind]});session=resume_conversation.start(uid,ConversationStart(job_id=job['id']));snapshot=resume_conversation.source(uid,session['data'])
    case={'source_version':__import__('hashlib').sha256(Path(resume_strategy.__file__).read_bytes()).hexdigest(),'name':kind,'model':args.model,'reasoning':args.reasoning,'variants':[]};ledger['cases'].append(case);save()
    for variant,fn in ([('improved',optimization.create)] if args.improved_only else [('baseline',baseline.create),('improved',optimization.create)]):
     row={'variant':variant};active_row=row;case['variants'].append(row);start=time.monotonic();token=ai.set_user_context(uid,process='resume_optimize')
     try:
      draft=asyncio.run(fn(uid,copy.deepcopy(snapshot),None,'custom',guided=True));data=draft['data'];rendered=data['rendered_snapshot'];row.update(completed=True,focus=data.get('strategy',{}).get('focus'),strategy=data.get('strategy'),sections=rendered['sections'],headline=rendered['headline'],pages=rendered['layout']['pages'],actual_cost_usd=data.get('actual_cost_usd'))
      prefix=target.parent/(target.stem+'-'+str(len(ledger['cases']))+'-'+kind+'-'+variant)
      for fmt,encoded in rendered['artifacts'].items():prefix.with_suffix('.'+fmt).write_bytes(base64.b64decode(encoded))
      row['artifact_prefix']=str(prefix)
     except Exception as error:row.update(completed=False,error=str(error))
     finally:ai.reset_user_context(token)
     row['seconds']=round(time.monotonic()-start,3);save();print(json.dumps({'case':kind,'variant':variant,'completed':row['completed'],'cost_total':round(ledger['estimated_or_reserved_usd'],6),'error':row.get('error')}),flush=True)
    credentials.remove(uid)
  finally:
   shutil.rmtree(folder/'credentials',ignore_errors=True)
   save()
 print(json.dumps({'estimated_or_reserved_usd':ledger['estimated_or_reserved_usd'],'ceiling_usd':args.ceiling,'cases':len(ledger['cases'])}))

if __name__=='__main__':main()
